"""Publish frontend/dist to Firebase Hosting through the REST API (same result as `firebase deploy --only hosting`).

Usage: python hosting_deploy.py <repo root> <site id> <gcp project>   (access token in env FV_TOKEN)
Translates firebase.json: source -> glob, destination -> path, run -> run, headers list -> map,
trailingSlash false -> REMOVE. Files matching the ignore list (dotfiles) are skipped.
"""

import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

import httpx

root, site, project = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
API = "https://firebasehosting.googleapis.com/v1beta1"
headers = {"Authorization": f"Bearer {os.environ['FV_TOKEN']}", "x-goog-user-project": project}
cfg = json.loads((root / "firebase.json").read_text(encoding="utf-8"))["hosting"]
public = root / cfg["public"]


def rewrite(r: dict) -> dict:
    out = {"glob": r["source"]}
    if "run" in r:
        out["run"] = {"serviceId": r["run"]["serviceId"], "region": r["run"]["region"]}
    else:
        out["path"] = r["destination"]
    return out


config = {
    "rewrites": [rewrite(r) for r in cfg.get("rewrites", [])],
    "headers": [{"glob": h["source"], "headers": {x["key"]: x["value"] for x in h["headers"]}}
                for h in cfg.get("headers", [])],
}
if cfg.get("trailingSlash") is False:
    config["trailingSlashBehavior"] = "REMOVE"

files: dict[str, bytes] = {}
for f in sorted(public.rglob("*")):
    rel = f.relative_to(public).as_posix()
    if f.is_file() and not any(part.startswith(".") for part in rel.split("/")):
        files["/" + rel] = gzip.compress(f.read_bytes(), mtime=0)
hashes = {path: hashlib.sha256(data).hexdigest() for path, data in files.items()}
print(f"{len(files)} files: {', '.join(files)}")

with httpx.Client(headers=headers, timeout=60) as c:
    def ok(r: httpx.Response) -> dict:
        if r.status_code >= 400:
            sys.exit(f"HTTP {r.status_code} {r.request.method} {r.request.url}: {r.text[:500]}")
        return r.json() if r.content else {}

    version = ok(c.post(f"{API}/sites/{site}/versions", json={"config": config}))["name"]
    print("version", version)
    pop = ok(c.post(f"{API}/{version}:populateFiles", json={"files": hashes}))
    need = set(pop.get("uploadRequiredHashes", []))
    for path, digest in hashes.items():
        if digest in need:
            ok(c.post(f"{pop['uploadUrl']}/{digest}", content=files[path],
                      headers={"Content-Type": "application/octet-stream"}))
            print("uploaded", path)
    ok(c.patch(f"{API}/{version}", params={"update_mask": "status"}, json={"status": "FINALIZED"}))
    release = ok(c.post(f"{API}/sites/{site}/releases", params={"versionName": version}))
    print("released", release.get("name"), release.get("type"))
