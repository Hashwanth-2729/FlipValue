"""Smoke-test a running FlipValue deployment (local, Cloud Run, or through Firebase Hosting).

Standard library only, so it runs anywhere Python 3.11+ is installed:

    python scripts/smoke_test.py --api-url https://<cloud-run-url> [--site-url https://<project>.web.app]

The partner key is read from the FLIPVALUE_SMOKE_API_KEY environment variable (never a command-line argument, so it
does not land in shell history). Without it, only the unauthenticated checks run.

Exit code 0 = every check passed; 1 = at least one failed. Nothing secret is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

VALID = {
    "device": {"manufacturer": "samsung", "model": "SM-G991B", "storage_gb": 128},
    "region": "IN", "currency": "INR",
    "condition": {"grade": "good", "faults": []},
    "repair_scenario": {"repair_type": "battery_replacement"},
}


class Result:
    def __init__(self) -> None:
        self.failures = 0

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
        self.failures += 0 if ok else 1
        return ok

    def note(self, name: str, detail: str) -> None:
        print(f"INFO  {name}  ({detail})")


def call(method: str, url: str, body: dict | None = None, headers: dict | None = None,
         timeout: float = 20) -> tuple[int, dict | str, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Accept": "application/json", **({"Content-Type": "application/json"} if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status, raw, hdrs = resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as err:
        status, raw, hdrs = err.code, err.read(), dict(err.headers)
    except (urllib.error.URLError, TimeoutError, ConnectionError) as err:
        return 0, f"unreachable: {getattr(err, 'reason', err)}", {}
    text = raw.decode("utf-8", errors="replace")
    try:
        return status, json.loads(text), {k.lower(): v for k, v in hdrs.items()}
    except json.JSONDecodeError:
        return status, text, {k.lower(): v for k, v in hdrs.items()}


def error_code(payload: dict | str) -> str | None:
    return payload.get("error", {}).get("code") if isinstance(payload, dict) else None


def contract_ok(v: dict, currency: str, allow_mock: bool) -> tuple[bool, str]:
    try:
        assert v["currency"] == currency, "currency"
        assert v["status"] in ("ok", "partial"), "status"
        for band in (v["as_is"], v.get("after_repair")):
            if band:
                assert 0 <= band.get("low", band["value"]) <= band["value"] <= band.get("high", band["value"]), "range"
        assert isinstance(v["valuation_id"], str) and len(v["valuation_id"]) <= 100, "valuation_id"
        assert v.get("mock", False) is False or allow_mock, "mock: true from this deployment"
        return True, f"value {v['as_is']['value']} {currency}, status {v['status']}, mock {v.get('mock')}"
    except (AssertionError, KeyError, TypeError) as exc:
        return False, f"contract violation: {exc}"


def partner_checks(r: Result, base: str, key: str | None, label: str, allow_mock: bool) -> None:
    url = f"{base}/v1/valuations"
    status, body, headers = call("POST", url, VALID)
    r.check(f"[{label}] no API key -> 401", status == 401 and error_code(body) == "unauthorized", f"HTTP {status}")
    status, body, _ = call("POST", url, VALID, {"X-API-Key": "not-a-real-key-" + uuid.uuid4().hex})
    r.check(f"[{label}] invalid API key -> 401", status == 401 and error_code(body) == "unauthorized", f"HTTP {status}")
    if not key:
        r.note(f"[{label}] authenticated checks", "skipped: FLIPVALUE_SMOKE_API_KEY not set")
        return
    auth = {"X-API-Key": key, "FlipValue-API-Version": "1"}
    request_id = f"smoke-{uuid.uuid4().hex[:12]}"
    status, body, headers = call("POST", url, VALID, {**auth, "X-Request-ID": request_id})
    if status == 200:
        ok, detail = contract_ok(body, "INR", allow_mock)
        r.check(f"[{label}] valid valuation -> 200 within contract", ok, detail)
    else:
        r.check(f"[{label}] valid valuation -> 200, or 404 no_data_for_condition while no real data exists",
                status == 404 and error_code(body) == "no_data_for_condition", f"HTTP {status} {error_code(body)}")
    r.check(f"[{label}] X-Request-ID echoed", headers.get("x-request-id") == request_id)
    bad_grade = {**VALID, "condition": {"grade": "mint", "faults": []}}
    status, body, _ = call("POST", url, bad_grade, auth)
    r.check(f"[{label}] invalid grade -> 422",
            status == 422 and error_code(body) == "validation_error", f"HTTP {status}")
    unknown = {**VALID, "device": {"manufacturer": "samsung", "model": "SM-X999Z"}}
    status, body, _ = call("POST", url, unknown, auth)
    r.check(f"[{label}] unknown model -> 404",
            status == 404 and error_code(body) == "unsupported_model", f"HTTP {status}")
    status, body, _ = call("POST", url, {**VALID, "currency": "USD"}, auth)
    r.check(f"[{label}] currency not matching region -> 422",
            status == 422 and error_code(body) == "unsupported_currency", f"HTTP {status}")
    status, body, _ = call("POST", url, VALID, {**auth, "FlipValue-API-Version": "9"})
    r.check(f"[{label}] unsupported API version -> 400", status == 400, f"HTTP {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", required=True, help="API base URL, e.g. the Cloud Run service URL")
    parser.add_argument("--site-url", help="Website URL (Firebase Hosting) to check the site and its rewrites")
    parser.add_argument("--allow-mock", action="store_true", help="accept mock: true (development deployments only)")
    args = parser.parse_args(argv)
    api, site = args.api_url.rstrip("/"), (args.site_url or "").rstrip("/")
    key = os.environ.get("FLIPVALUE_SMOKE_API_KEY", "").strip() or None
    r = Result()

    status, body, _ = call("GET", f"{api}/health")
    r.check("health -> 200 ok",
            status == 200 and isinstance(body, dict) and body.get("status") == "ok", f"HTTP {status}")
    status, body, _ = call("GET", f"{api}/ready")
    r.check("ready -> 200 (database migrated, catalogue loaded)", status == 200, f"HTTP {status} {body}")
    if isinstance(body, dict) and not body.get("checks", {}).get("partner_keys", True):
        r.note("partner keys", "no partner key configured yet")
    status, body, headers = call("GET", f"{api}/api/meta")
    r.check("public /api/meta -> 200", status == 200 and isinstance(body, dict), f"HTTP {status}")
    if isinstance(body, dict):
        r.note("data status", f"{body.get('environment')}, {body.get('data_status')}, "
                              f"{body.get('real_observations')} real observations")
        if body.get("environment") == "production":
            r.check("production never reports mock data in use", body.get("mock_data_in_use") is False)
    r.check("API responses are not cacheable", "no-store" in headers.get("cache-control", ""))
    status, body, _ = call("GET", f"{api}/admin/api/sources")
    r.check("admin API without key -> 401", status == 401, f"HTTP {status}")
    partner_checks(r, api, key, "api", args.allow_mock)

    if site:
        status, html, headers = call("GET", f"{site}/")
        is_app = isinstance(html, str) and 'id="root"' in html
        r.check("website / -> 200 HTML", status == 200 and is_app, f"HTTP {status}")
        r.check("website has a Content-Security-Policy",
                (isinstance(html, str) and "Content-Security-Policy" in html) or "content-security-policy" in headers)
        status, html, _ = call("GET", f"{site}/value")
        r.check("deep link /value -> 200 (SPA fallback)",
                status == 200 and isinstance(html, str) and 'id="root"' in html, f"HTTP {status}")
        status, body, _ = call("GET", f"{site}/api/catalogue")
        r.check("website /api rewrite reaches the API", status == 200 and isinstance(body, list), f"HTTP {status}")
        save = {"device": {"model_id": "google-pixel-6a"}, "region": "IN", "currency": "INR", "assessment": {
            "powers_on": "yes", "usable_normally": "yes", "screen": "perfect", "body": "like_new", "battery": "normal",
            "charging": "normal", "cameras": "working", "audio": "working", "buttons": "working",
            "connectivity": "working", "liquid_damage": "no"}}
        status, body, _ = call("POST", f"{site}/api/saved", save)
        if r.check("website can save a valuation", status == 201 and isinstance(body, dict), f"HTTP {status}"):
            sid, token = body["id"], body["delete_token"]
            status, _, _ = call("DELETE", f"{site}/api/saved/{sid}", headers={"X-Delete-Token": token})
            r.check("delete through the website (custom header passes the rewrite)", status == 204, f"HTTP {status}")
        partner_checks(r, site, key, "via website rewrite", args.allow_mock)

    print(f"\n{'ALL CHECKS PASSED' if r.failures == 0 else f'{r.failures} CHECK(S) FAILED'}")
    return 0 if r.failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
