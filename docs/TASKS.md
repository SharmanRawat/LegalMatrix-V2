# TASKS — where we are, what is next, how to parallelise

## 1. Done (in this commit)

- [x] FastAPI backend + Next.js PWA + Ollama compose; seeded admin; HMAC roles.
- [x] Fast CPU pipeline (RapidOCR + qwen2.5:3b SLM + regex) with VLM fallback/rescue
      (`ocr_engine.py`, `field_classifier.py`, `vlm_rescuer.py`, `preprocessing.py`).
- [x] Merge logic that survives real labels (price block, date block, care contact-gate).
- [x] 7-rule engine + USP math + font measurement with honesty gating + radar + heat-maps.
- [x] PDF/JSON/CSV/certificate exports, evidence hashing, history/dashboard/search,
      manual overrides with audit log.
- [x] 76 pytest tests (OCR mocked) + product-6 regression test.
- [x] Audit tooling: `scripts/pipeline_audit.py` (oracle diff, cached),
      `regex_audit.py`, `cascade_bench.py`.
- [x] Cleaned dead experiments (`training/`, `update1/`, `update2*.zip`, florence/qwen
      scratch tests) — deleted in this commit. `images/` stays local-only (gitignored).

## 2. Active ML loop (owner: ML pipeline, do NOT parallelise internally)

Goal: 10/10 fields correct per product, measured against the 7B oracle — not vibes.

```
# WSL: images live at /mnt/e/SIH_installation_files/images
cd backend
python scripts/pipeline_audit.py --images-dir /mnt/e/SIH_installation_files/images \
  --product 6 --oracle qwen2.5vl:7b --classifier qwen2.5:3b --out-dir /tmp/pipeline_audit
# read per-product diffs + per-field agreement + JSON/CSV in /tmp/pipeline_audit
# fix ONE thing (preprocessor variant? regex? SLM prompt in field_classifier.py?
#  merge rule in inspection_service.py?) then re-run (cached → near-free)
# next product only when 6 is green; keep products 1-2 skipped (deleted, poor quality)
```

Order: 6 → 8 → 10 → 14/15/18/20 (3-image products stress merge logic) → pairs →
65–68 (latest). Log each product: field agreement % + what fixed it (see MEMORY.md).
`--product` runs one product; omit for full sweep before a release.

Efficiency notes (read before "optimising"):
- Do NOT run images one-by-one through the UI for tuning — the audit script batches,
  caches OCR+oracle by mtime, and prints diffs. UI clicks are ~10× slower.
- Do NOT re-pull/re-run the 7B oracle per tweak — it is cached; only classifier+merge re-execute.
- Do NOT enable `OCR_PANE_ZOOM_ENABLED=1` globally (helps ~1/7 products, expensive).
  Same for `VLM_RESCUE_ENABLED=1` — measure the CPU+SLM path first (`=0`), escalate only.
- The 7B VLM is the oracle, not the runtime: shipping "just call 7B for everything"
  kills offline/CPU demo + latency + GPU cost. Keep `rapidocr + 3b` as default path.

## 3. Parallel workstreams for teammates (start now, no ML dependency)

| # | Stream | Files | First commit-sized task |
|---|---|---|---|
| A | Frontend polish | `frontend/app/page.tsx`, `inspection/[id]/`, `dashboard/`, `history/`, `components/RadarChart.tsx`, `lib/api.ts` | Empty/loading/error states; mobile camera CSS; dashboard charts wired to real `/dashboard/stats`; search filters wired to `/search` |
| B | Report/export UX | `backend/app/api/inspections.py::_build_pdf`, `services/certificate_generator.py`, frontend download buttons | Logo + header, QR to verify URL, Hindi font note (₹→Rs. is intentional in PDF), CSV column freeze |
| C | Auth + roles UX | `api/auth.py`, `login/`, `lib/api.ts` | Hide override buttons for VIEWER, redirect on 401, change-password screen, document seed creds rotation |
| D | Evidence integrity | `services/inspection_service._store_evidence`, evidence endpoints | Verify-hash display, tamper demo, storage-quota note |
| E | DevOps/docs | `docker-compose.yml`, Dockerfiles, `docs/` | `docker compose up --build` green on a clean machine; record GPU/CPU timings in MEMORY.md |
| F | QA dataset | `images/` (local), `/tmp/pipeline_audit` outputs | Build a `samples-private/` manifest: product → images → oracle JSON (never commit photos) |

Branch convention: `feat/<stream>-<short>` from `main`, PR with screenshot + `pytest -q`
output. Never commit `images/`, `backend/data/`, `venv/`, `node_modules/`, `.env`,
or any token (see MEMORY.md security note).

## 4. Backlog (after extraction is green)

- [ ] E-commerce listing URL input (needs new extractor, rules 2027 country filter).
- [ ] Hindi/Devanagari OCR evaluation (`OCR_LANG`, manner Rules language check).
- [ ] Placement free-area auto-check from boxes (rules.json has the spec).
- [ ] Postgres swap behind `repositories/` for multi-node.
- [ ] PWA offline queue (store photo, sync when online).
- [ ] Admin user-management UI.

## 5. Definition of done per task

Code + test (`backend/tests/` or manual UI steps) + docs line update + no secrets/
photos/binaries in diff (`git status --short`, `git diff --stat` clean of `venv`,
`node_modules`, `data/`, `images/`).
