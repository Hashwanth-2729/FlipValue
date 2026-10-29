"""Start a throwaway FlipValue server for end-to-end tests: fresh SQLite database, catalogue, synthetic data,
built website. Keys come from the environment (generated per run by playwright.config.ts)."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

db = Path(tempfile.mkdtemp(prefix="flipvalue-e2e-")) / "e2e.db"
os.environ["FLIPVALUE_DATABASE_URL"] = f"sqlite:///{db.as_posix()}"
os.environ.setdefault("FLIPVALUE_PUBLIC_RATE_LIMIT_PER_MIN", "600")

import uvicorn  # noqa: E402

from flipvalue.cli import main as cli  # noqa: E402

if cli(["setup-dev"]) != 0:
    raise SystemExit("setup failed")
uvicorn.run("flipvalue.app:create_app", factory=True, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
