# Contributing to SpecLedger

SpecLedger started as a UniHack 2026 hackathon submission, not a long-running open-source project — but the codebase, tests, and CI are structured so it can be picked up and extended like one. This guide covers the mechanics of getting a change in; see the [README](README.md) for what the project actually does and its known limitations.

---

## Development setup

```bash
git clone https://github.com/Yashasm18/specledger.git
cd specledger

# Backend (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Frontend (Node 18+)
cd frontend
npm install
npm run dev   # http://localhost:5174
```

Without `DATABASE_URL` set, the backend falls back to local SQLite automatically — no external services required to get started.

---

## Before opening a pull request

Run the full verification pass locally; CI runs the same checks and will fail the same way.

```bash
# Backend
.venv/bin/python -m pytest tests/ -q                          # 475 passed, 1 skipped
pylint --rcfile=.pylintrc --fail-under=8.5 backend/            # currently 9.82/10

# Frontend
cd frontend
npm run typecheck
npx vitest run
npm run build
```

A pull request that drops the Pylint score below 8.5 or breaks any test will fail CI (`.github/workflows/pylint.yml`).

---

## Code conventions

- **Backend:** PEP 8, type hints on public functions, no bare `except:`. Match the existing pattern of frozen dataclasses for pipeline data (`EnrichedField`, `DiscoveredSource`, etc.) — avoid mutable shared state outside the process-local caches already documented in `catalogue_api.py`.
- **Determinism by default:** anything that makes real network calls (source discovery, PDF fetch/extraction) must stay opt-in behind `live_fetch=true` so the test suite remains fast and offline.
- **No fabricated data:** this project's whole premise is honest, evidence-backed enrichment. New enrichment or scoring logic should fail safe — return nothing or mark a field unverified rather than guess a plausible-looking value. See `source_discovery.py`'s `extract_pdf_attributes()` for the pattern (conservative regex, empty result over a false positive).
- **Frontend:** TypeScript strict mode (already enforced by `npm run typecheck`), functional components, keep new state additions typed rather than `any` where practical.

## Adding tests

New normalization, validation, or extraction logic should ship with tests in `tests/` (backend) or `frontend/src/*.test.ts` (frontend). Look at `tests/test_source_discovery.py`'s `PdfAttributeExtractionTests` for the expected shape: cover the real-match case, the false-positive-rejection case, and edge cases (invalid input, dedup/caps).

## Pull request process

1. Fork the repository and create a feature branch (`git checkout -b feature/your-feature-name`).
2. Make your change, keeping it scoped — this repo favors small, reviewable diffs over broad refactors.
3. Add or update tests for any new behavior.
4. Run the full verification pass above before pushing.
5. Open a pull request describing what changed and why, referencing any related issue.

## License

By contributing to SpecLedger, you agree that your contributions are licensed under the project's [MIT License](LICENSE).
