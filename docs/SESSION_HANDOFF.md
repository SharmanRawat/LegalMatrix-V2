# Session Handoff — Big Pickle (paste into a fresh opencode conversation)

## Project
LegalMatrix-V2 — SIH 2026 PS 26034 (Hindi OCR + web UI + PDF compliance report for
packaged food labels). Repo `/home/sharman_rawat/LegalMatrix-V2` (git, main).
FastAPI backend in `backend/`; Next.js frontend in `frontend/`.
**The Next.js in this repo is NOT training-data Next — read
`node_modules/next/dist/docs/` before ANY frontend edit.**

## Non-negotiables (read these files FIRST)
- `docs/MEMORY.md`, `docs/TASKS.md`, `docs/RULES.md`, `docs/ARCHITECTURE.md`.
- Golden-audit discipline: every change measured on the golden answers
  (238 cells, 29 products in `backend/data/answers_golden.json`) at
  **0 regressions**, preferably a deterministic merge-only diff vs the FROZEN
  OCR+SLM cache. Never hand-tune/hallucinate; unreadable fields stay
  NOT DETECTED → inspector manual entry. Keep the 3B SLM (qwen2.5:3b), NO VLM
  rescue; default OCR path stays byte-identical.
- DO NOT touch: `backend/data/` (SQLite + evidence), `images/` (copyrighted),
  `new_images/` (**user's unlabelled non-edible product photos — do NOT touch
  until the user labels them and commands it**).
- Gates: `cd backend && ./venv/bin/python -m pytest -q` (currently
  **239 passed, 2 skipped**); frontend `npx tsc --noEmit`.
- Never commit `.env*`, `*.db`, `backend/data/`, `images/`, `venv/`,
  `node_modules/` (all gitignored — keep it that way).

## Current state (verified 2026-09-22, pre-shutdown)
- HEAD: `9e5429b` (run23 docs). Working tree clean except untracked
  `new_images/`.
- Shipped golden baseline: **175/238 (73.5%)**, deterministic merge-only diff
  on the frozen pipe cache.
- Run arc: run13=166 → run19 reconcile gate=171 → run20 date-token repair=175
  → run21 corrupt-year reject=175 (p7 mfg WRONG→NOT DETECTED) → run22
  None-component crash fix=175 (suite 239+2) → **run23 2× upscale+sharpen
  REJECTED**: pp2x 154 vs pp2ctrl 168 vs frozen 175 (27 regressions / 27
  recoveries in the clean A/B; target sub-resolution dates did NOT recover,
  good dates were lost; scaffolding fully reverted).
- **Big finding (§3b-ix):** onnxruntime CPU OCR is NON-deterministic run-to-run
  (same image → `Di Mart` vs `DEMart`, box drift). Two identically-configured
  full runs differ ~90 cells / net −7, so **175/238 is one draw — quote the
  envelope (~168–175) for any claim**, never the single number.

## Frozen-cache discipline / commands
- Frozen caches + baseline backed up at `~/legalmartix_audit_artifacts/`
  (`pipeline_audit_ocr_cache.json`, `_pipe_cache.json`, `_oracle_cache.json`,
  `pipeline_audit_v2/pipeline_vs_oracle.csv`, pp0/pp2x/pp2ctrl CSVs,
  `pp_compare.py`). If `/tmp` copies are gone after reboot, restore:
  `cp ~/legalmartix_audit_artifacts/pipeline_audit_*.json /tmp/`.
  If any cache must be regenerated, RE-ANCHOR the baseline first (a fresh
  default run may land ~168± — record that draw) before claiming 175/238.
- Full audit (omit `--answers` = live diagnostic, NEVER the shipped metric):
  `cd backend && ./venv/bin/python scripts/pipeline_audit.py --images-dir
  /home/sharman_rawat/LegalMatrix-V2/images --classifier qwen2.5:3b
  --answers data/answers_golden.json --out-dir <dir>`
- Fresh-run isolation: `AUDIT_CACHE_PREFIX=<pfx>-` namespaces cache files;
  `OCR_UPSCALE2X_SHARPEN=1` is the REJECTED experiment — leave OFF.
- Date state (shipped draw): mfg 17 ok / 4 wrong / 7 missing; exp 20 ok /
  1 wrong / 8 missing. Details incl. per-product list in the chat record:
  wrongs are honest year-only partials (p3/p14/p18) + irreducible noise
  (p29 mfg, p25 exp); misses are the sub-resolution cluster (p4/p16/p17/
  p22/p23/p28 ± p7 mfg, p14/p27 exp) → NOT DETECTED by design. p23's golden
  pair is physically impossible (exp before mfg) — audit warns, warn-only.
- Precedent for rejected experiments (run15/17/18/23): measure → reject →
  FULLY revert scaffolding → document. Never leave experiment code uncommitted
  after the verdict.

## Pending work queue (ask the user; do NOT start without go-ahead)
1. **Rotate seeded admin credentials** before any demo: `admin / admin@123`,
   `LEGALMATRIX_AUTH_SECRET=change-me…`. User go-ahead was pending.
2. **Diagnose 4-image upload failure** — needs the user to supply the product
   name + returned error/output.
3. **`new_images/` audit** — WAIT for user to label manually, then build golden
   answers for non-edible products and audit. The next real metric lever.
4. Optional (user-approved-only): p23 golden visual check; Devanagari
   shaping/CTC decoding; Devanagari web font; Hindi-label accuracy target vs
   English.
5. Demo readiness: user records with clean images; font-measurement axis only
   lights up when a calibration reference (credit card/barcode/EXIF) is in-shot
   — show it only then. Mobile/web already Next.js-responsive; OCR stays on
   the FastAPI backend.

## Key files
- `backend/app/services/inspection_service.py` — merge gate:
  `_reconcile_date_ordering`, `_corrupt_single_digit_year`, `_full_key`,
  `merge_extractions`.
- `backend/app/services/ocr_engine.py` — CPU OCR (RapidOCR / PP-OCRv3).
- `backend/app/services/field_classifier.py` — 3B SLM (temperature 0).
- `backend/app/services/font_measurement.py`, `scale_calibrator.py`,
  `compliance_scorer.py` — font axis (needs calibration ref).
- `backend/app/services/certificate_generator.py`, `backend/app/api/inspections.py`
  — PDF report (Unicode/Deva font routing).
- `backend/scripts/pipeline_audit.py`, `backend/data/answers_golden.json`,
  `backend/tests/test_date_reconcile.py`.
- `docs/MEMORY.md` (§3b-i…ix), `docs/TASKS.md`, `docs/RULES.md`.

## First actions for the new session
1. `git status` + `git log --oneline -5` — expect clean at `9e5429b`, only
   untracked `new_images/`.
2. Restore frozen caches to /tmp from `~/legalmartix_audit_artifacts/` if /tmp
   was wiped by the reboot.
3. Run the pytest gate (`cd backend && ./venv/bin/python -m pytest -q`) to
   prove the environment works — expect 239 passed, 2 skipped.
4. Read `docs/MEMORY.md` + `docs/TASKS.md`.
5. Stall for the user's command (credential rotation / 4-image upload /
   new_images labels / demo support). Do NOT touch `new_images/`.