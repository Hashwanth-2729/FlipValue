# Implementation status

**As of 2026-10-19, version 0.3.0** (agent 0.3.0). Only what was actually run is reported as verified.

## Works and is verified

| Feature | How verified |
|---|---|
| Source-attributed repair prices (Samsung India official parts + labour, before GST) | **Live ingestion** from samsung.com/in 3× (last 07:07 UTC): 179 models, 1,075 part prices, 15 labour charges, 0 rejected; parser tests on saved excerpts; UI shows source text, link, retrieval and page dates |
| No invented prices | Brands/markets/repairs without evidence return `insufficient_pricing_data` (tests + browser) |
| Price scopes kept apart; exact / regional-variant model matching; inspection fee; freshness | unit + integration tests |
| Polite ingestion: robots.txt, rate limit, retries, site-change detection, dedup, reports | unit tests + live runs |
| Production gates: demo pricing refused, explicit source allowlist required | config tests |
| Guided tests: phone page (colours, touch grid, speaker, microphone, cameras, vibration, motion), manual tests, agent connector test; provenance; `not_run` never evidence | integration tests; **browser on an emulated touch phone with fake camera/microphone** (Edge) |
| Opt-in bug-report summary (counted on the PC, file deleted) | unit + agent API tests with a fixture archive |
| New ADB checks: sensors, storage I/O, software integrity | parser/collector tests on documented formats |
| Diagnosis: next step, remaining uncertainty, ranking basis, suggested tests, note-only findings | unit/integration tests, browser |
| Question strategies + baseline + safety/inspection stops | tests; simulation (11/11, 11/11, 10/11 personas; 6.0 / 4.9 / 4.4 questions) |
| Decision engine: plain language, input warnings, no-profit and tax caveats | unit tests, browser |
| Migrations, `/ready`, DB failure → 503, JSON logs, backup script | tests |
| UI: all routes at 390 px, no console errors in full journeys | browser |
| 0.3.0: separate Tests and Questions steps; tests page "complete" state and step check marks; questions skipped when a test already answered them (7 questions) and a "no questions needed" stop | unit + integration + browser tests |
| 0.3.0: Google Pixel official repair estimates (IN 27 models, US 28) | **Live ingestion** 10:28 UTC, 988 records, 0 rejected; Pixel 6a screen ₹7,080 shown in the browser |
| 0.3.0: light/dark/system theme toggle, redesigned pages | browser (theme persists; screenshots at 1280 and 390 px in both themes, no horizontal scroll) |
| 0.3.0: agent checks before the deeper check / connector test (running, version, pairing, phone), live charging readout, pairing shared across tabs | agent API tests; browser |

**Test results (0.3.0):** **273 passed** including 7 browser tests; `pytest -m hardware` **skipped (no device)**. ruff clean; mypy clean (52 files). Earlier (0.2.0): `pip-audit` on the lockfile and on the full environment: no
known vulnerabilities.

## Real prices vs demo data

* **Real (source-attributed):** Samsung India official spare-part prices and labour charges; Google Store official repair estimates for Pixel phones (India and US; tax treatment not stated by Google). Stored in
  `var/pricing/` (not in git); every deployment runs `python -m fixmytech.pricing.ingest`.
* **Demo:** `src/fixmytech/data/demo_repair_prices.csv`, only with `FIXMYTECH_PRICING_DEMO=true`, labelled DEMO,
  refused in production. Off by default.
* **None:** Apple (terms prohibit collection; customers get Apple's estimator link), Motorola (robots disallow;
  manual curation possible), OnePlus, OPPO and Xiaomi (403 to bots, not bypassed), realme (terms prohibit scraping).

## Hardware verification

**Partly verified on the customer's own Pixel 6a (Android 17, API 37), from their stored sessions:** all phone-browser tests ran; the connector test passed (45 samples, charging seen, battery 93%); battery capacity (87%, 1,310 cycles), 30 sensors and software integrity were read. Storage failed on that phone's `df` output, so 0.3.0 adds a parser fix plus a `dumpsys diskstats` fallback (**not yet re-run on the phone**). The bug report never completed there (most likely the older 0.1 agent or a lost per-tab pairing); 0.3.0 changes that flow, but it **still needs a run on the phone**. Earlier sessions had no device connected. Verified so far without a phone: the real agent with real ADB 35.0.2 (v0.1). Phone-page tests
ran in Edge on an emulated phone with fake media devices. Outstanding on real hardware: every ADB check, the connector
test, the bug report, `adb reverse` + opening the page, and camera/microphone/touch/vibration/sensors.

## Faults that cannot be confirmed remotely

Internal liquid damage/corrosion, display panel vs glass damage, which speaker/microphone/camera component failed,
charging-port wear vs debris vs board faults, battery capacity on phones that hide it, water-seal integrity,
antenna/signal faults, mainboard faults. See docs/DIAGNOSTIC_LIMITATIONS.md.

## Blocked or partial

| Item | State | Blocker |
|---|---|---|
| Samsung price display in production | implemented, gated | legal review / Samsung permission |
| Other brands' prices | registry entries only | terms (Apple), robots (Motorola), review pending (OnePlus) |
| FlipValue live | client + contract ready | partner API and key |
| ML | pipeline only, disabled | no real labelled data |
| Docker image | Dockerfile written | not built (Docker daemon not running) |
| PostgreSQL | expected to work via SQLAlchemy | untested |
| Physical-phone validation | test exists | no device connected |

## Known limitations

See docs/DIAGNOSTIC_LIMITATIONS.md and docs/PRICING_SOURCES.md. The one flaky full-suite run observed early in this
session (1 failure in a slow 37 s run) did not reproduce in 18 further runs; it is unresolved and being watched.

## Reproduce

```powershell
.\.venv\Scripts\python -m pip install -r requirements.lock.txt; .\.venv\Scripts\python -m pip install -e ".[ml,dev]"
$env:FIXMYTECH_PRICING_CONTACT="you@example.com"; .\.venv\Scripts\python -m fixmytech.pricing.ingest
.\scripts\check.ps1
.\scripts\run-dev.ps1 -Port 8010            # open http://127.0.0.1:8010
.\.venv\Scripts\python -m pytest -m browser tests\browser     # needs: pip install playwright
.\.venv\Scripts\python -m pytest -m hardware -s tests\hardware   # with an authorized phone
```

## Next actions

1. Connect a real Android phone: run the hardware test, a full UI scan, the connector test, the bug report and the
   phone test page via "Open on my phone (USB)".
2. Obtain legal clearance (or Samsung's permission) for displaying Samsung prices; set the production allowlist.
3. Agree the FlipValue contract and connect its staging API.
4. Add price sources with acceptable terms; build the manual-curation workflow.
5. Build/test the Docker image and PostgreSQL; package the agent.
