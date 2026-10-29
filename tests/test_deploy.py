"""Deployment behaviour: production settings, proxies, logging, the serve entry point and the smoke-test script."""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from flipvalue import cli
from flipvalue.app import create_app
from flipvalue.config import ConfigError, Settings
from flipvalue.observability import JsonFormatter

ROOT = Path(__file__).resolve().parents[1]
SALT = "s" * 32


# --- production settings -----------------------------------------------------------------------


def test_production_refuses_sqlite():
    with pytest.raises(ConfigError, match="SQLite is not allowed"):
        Settings(environment="production", hash_salt=SALT, database_url="sqlite:///x.db")
    Settings(environment="production", hash_salt=SALT, database_url="postgresql+psycopg://u:p@/db?host=/cloudsql/x")


def test_production_requires_salt():
    with pytest.raises(ConfigError, match="HASH_SALT"):
        Settings(environment="production", database_url="postgresql+psycopg://u:p@h/db")


@pytest.mark.parametrize("origins, env", [(("*",), "development"), (("example.com",), "development"),
                                          (("http://site.example",), "production")])
def test_cors_origins_must_be_exact_https_in_production(origins, env):
    with pytest.raises(ConfigError, match="CORS"):
        Settings(environment=env, hash_salt=SALT, cors_origins=origins, database_url="postgresql+psycopg://u:p@h/db")


def test_secret_values_are_stripped(monkeypatch):
    """Secret Manager values created with `echo` or PowerShell pipes end with a newline."""
    monkeypatch.setenv("FLIPVALUE_DATABASE_URL", "postgresql+psycopg://u:p@/db?host=/cloudsql/x\n")
    monkeypatch.setenv("FLIPVALUE_HASH_SALT", f"{SALT}\r\n")
    monkeypatch.setenv("FLIPVALUE_API_KEYS", f"{'k' * 40}\n")
    monkeypatch.setenv("FLIPVALUE_ENV", "production\n")
    monkeypatch.setenv("FLIPVALUE_CORS_ORIGINS", "https://a.web.app, https://a.firebaseapp.com")

    s = Settings.from_env()

    assert s.database_url.endswith("/cloudsql/x") and s.hash_salt == SALT and s.api_keys == ("k" * 40,)
    assert s.cors_origins == ("https://a.web.app", "https://a.firebaseapp.com")


# --- proxies, CORS, abuse limits ---------------------------------------------------------------


@pytest.mark.parametrize("trust, hops, xff, expected", [
    (False, 1, "1.1.1.1, 2.2.2.2", "testclient"),
    (True, 1, "1.1.1.1, 2.2.2.2", "2.2.2.2"),
    (True, 2, "6.6.6.6, 1.1.1.1, 2.2.2.2", "1.1.1.1"),   # left-most entry (spoofable) is never used with hops
    (True, 3, "1.1.1.1", "1.1.1.1"),
])
def test_client_ip_from_forwarded_header(make_client, admin_headers, trust, hops, xff, expected):
    client = make_client(trust_proxy=trust, proxy_hops=hops)

    data = client.get("/admin/api/diagnostics/forwarding", headers={**admin_headers, "X-Forwarded-For": xff}).json()

    assert data["client_ip_used_for_rate_limits"] == expected


def test_forwarding_diagnostics_need_an_admin_key(client, headers):
    assert client.get("/admin/api/diagnostics/forwarding").status_code == 401
    assert client.get("/admin/api/diagnostics/forwarding", headers=headers).status_code == 401


def test_global_public_cap_applies_across_clients(make_client):
    client = make_client(trust_proxy=True, public_rate_limit_per_minute=100, public_global_rate_limit_per_minute=2)
    body = {"currency": "INR", "as_is_value": 1}

    codes = [client.post("/api/decision", json=body, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
             for i in range(3)]

    assert codes == [200, 200, 429]


def test_cors_allows_only_configured_origins(make_client):
    client = make_client(cors_origins=("https://flipvalue-demo.web.app",))
    preflight = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}

    ok = client.options("/api/valuations", headers={"Origin": "https://flipvalue-demo.web.app", **preflight})
    bad = client.options("/api/valuations", headers={"Origin": "https://evil.example", **preflight})

    assert ok.headers.get("access-control-allow-origin") == "https://flipvalue-demo.web.app"
    assert "access-control-allow-origin" not in bad.headers


def test_api_without_frontend_returns_json_404(make_client):
    response = make_client(frontend_dist=None).get("/")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"


# --- logging and entry point -------------------------------------------------------------------


def test_logs_are_cloud_logging_json():
    record = logging.LogRecord("flipvalue", logging.WARNING, __file__, 1, "hello", None, None)
    record.fields = {"request_id": "r1"}

    line = json.loads(JsonFormatter().format(record))

    assert line["severity"] == "WARNING" and line["message"] == "hello" and line["request_id"] == "r1"


def test_serve_binds_all_interfaces_on_platform_port(monkeypatch):
    calls = {}
    monkeypatch.setenv("PORT", "9123")
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: calls.update(kw))

    assert cli.serve() == 0
    assert calls["host"] == "0.0.0.0" and calls["port"] == 9123 and calls["factory"] is True
    assert calls["access_log"] is False


# --- smoke-test script against a live server ---------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(seeded_db, api_key):
    def _start(**overrides):
        settings = Settings(**{"api_keys": (api_key,), "database_url": seeded_db, "frontend_dist": None, **overrides})
        port = _free_port()
        server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        servers.append((server, thread))
        return f"http://127.0.0.1:{port}"

    servers: list = []
    yield _start
    for server, thread in servers:
        server.should_exit = True
        thread.join(timeout=5)


def _smoke():
    sys.path.insert(0, str(ROOT / "scripts"))
    import smoke_test

    return smoke_test


def test_smoke_script_passes_against_production_mode(live_server, api_key, monkeypatch, capsys):
    url = live_server(environment="production", hash_salt=SALT, allow_sqlite_in_production=True)
    monkeypatch.setenv("FLIPVALUE_SMOKE_API_KEY", api_key)

    code = _smoke().main(["--api-url", url])

    out = capsys.readouterr().out
    assert code == 0, out
    assert "PASS  [api] valid valuation" in out  # production: no real data yet, so the 404 path is the expected one
    assert "PASS  production never reports mock data in use" in out
    assert api_key not in out  # the key is never printed


def test_smoke_script_fails_on_mock_data_unless_allowed(live_server, api_key, monkeypatch, capsys):
    url = live_server()  # development: synthetic data, mock: true
    monkeypatch.setenv("FLIPVALUE_SMOKE_API_KEY", api_key)
    smoke = _smoke()

    assert smoke.main(["--api-url", url]) == 1
    assert "mock: true from this deployment" in capsys.readouterr().out
    assert smoke.main(["--api-url", url, "--allow-mock"]) == 0


def test_smoke_script_reports_a_down_deployment(capsys):
    assert _smoke().main(["--api-url", f"http://127.0.0.1:{_free_port()}"]) == 1
    assert "FAIL  health" in capsys.readouterr().out


def test_dockerfile_and_firebase_config_are_consistent():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    firebase = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
    assert 'CMD ["python", "-m", "flipvalue", "serve"]' in dockerfile
    assert "COPY data/catalogue/" in dockerfile and "requirements-deploy.txt" in dockerfile
    hosting = firebase["hosting"]
    assert hosting["public"] == "frontend/dist"
    runs = [r for r in hosting["rewrites"] if "run" in r]
    assert {r["source"] for r in runs} >= {"/api/**", "/v1/**", "/admin/api/**"}
    assert len({(r["run"]["serviceId"], r["run"]["region"]) for r in runs}) == 1
    assert hosting["rewrites"][-1] == {"source": "**", "destination": "/index.html"}
    for ignore_file in (".gcloudignore", ".dockerignore"):
        lines = (ROOT / ignore_file).read_text(encoding="utf-8").splitlines()
        assert "frontend/" in lines and ".env" in lines  # no node_modules upload, no local secrets
        assert not any(line.startswith(("src", "data")) for line in lines)  # runtime code and catalogue stay in


def test_release_command_is_idempotent(catalogue_db, monkeypatch, capsys):
    monkeypatch.setenv("FLIPVALUE_DATABASE_URL", catalogue_db)
    assert cli.main(["release"]) == 0 and cli.main(["release"]) == 0
    assert capsys.readouterr().out.count("catalogue: 31 models loaded") == 2
