# MEMORY — decisions, gotchas, pointers (read before touching the pipeline)

## 1. Why the pipeline looks like this

- **One central GPU, dumb phones.** LLM runs once on an Ollama server
  (`qwen2.5vl:7b` oracle/rescue, `qwen2.5:3b` SLM classifier). Phones need only a
  browser/PWA — no on-device model. Do not "simplify" by calling the 7B per request
  from every client; latency + GPU + offline story all regress.
- **Fast path = RapidOCR + SLM + regex; 7B = oracle + rescue.** `ocr_engine.py`
  (`SmartOCRService`) implements the same interface as `ocr_service.py`
  (`extract_structured/verify_currency_symbol/prompt_fingerprint`) so
  `inspection_service.run_inspection` and all tests work unchanged with either.
- **Resource-adaptive cascade.** Default `VLM_RESCUE_ENABLED=0` (pure CPU demo).
  With `=1`, overall confidence < 55 escalates to VLM. Measure CPU path first.

## 2. Gotchas that already bit us (do not reintroduce)

1. `consumer_care` longest-wins poison — disclaimer boilerplate
   ("All pictures shown are for illustration…") out-lengths the real contact.
   Fix: contact-channel regex gate (`@|toll free|1800|10-digit`); no contact → blank.
2. MRP/USP/net-qty mixing across photos — front-panel "Rs. 265" + back-panel USP
   block merged into a chimera. Fix: price block (need ≥2 of 3) from single best photo.
3. Mfg/expiry overwrite — side-panel lone date (usually expiry) overwrote the batch
   sticker year. Fix: date block (need 2) from single best photo.
4. ₹ glyph drop — RapidOCR returns `于/¥/天/舌/曰/元` for ₹; VLM sometimes drops it
   entirely though printed. Fix: glyph normalisation + `_verify_mrp_currency`
   second look before failing Rule 6(1)(e).
5. Glued dates (`07/04/2606/04/27`) and mangled months (`JHN→JAN`, `JU1→JUL`,
   `FE8→FEB`, `AU6→AUG`) — fixed in `ocr_engine.py` pre-classifier; add new cases there.
6. Font honesty — no calibration object / no token boxes → return `CANNOT_MEASURE`,
   never a fake mm number. Calibration chain: credit-card → barcode → EXIF (`auto`).
7. `edible` drives dimensions: `yes` (food/meds) → dimensions skipped; `no` →
   required. VLM prompt forces exactly `yes/no/""`.
8. Prompt fingerprint (`sha256(_build_prompt)`) is stored per inspection — changing
   the prompt invalidates old evidence comparisons. Intentional.
9. Tests isolate storage via call-time `get_data_dir()` — never hardcode
   `backend/data` paths in new code or tests will pollute each other.

## 3. File pointers (where to fix what)

- Wrong field value → `services/field_classifier.py` (SLM prompt + regex) then
  `services/ocr_engine.py` (glyph/date normalisation, multi-pass variants).
- Wrong merge across the 2–3 photos → `services/inspection_service.py::merge_extractions`.
- Wrong pass/fail → `core/rule_engine.py` + `data/rules.json` (see RULES.md change recipe).
- Wrong font mm → `services/font_measurement.py` + `scale_calibrator.py`.
- Wrong USP verdict → `services/price_engine.py`.
- Slow/expensive → `OCR_MULTI_PASS_*`, `OCR_PANE_ZOOM_ENABLED`, `VLM_RESCUE_*` in `config.py`.
- UI shows stale/wrong → `frontend/app/page.tsx` (inspect), `inspection/[id]/page.tsx`,
  `dashboard/`, `history/`, client `lib/api.ts`.

## 4. Commands

```bash
# backend dev
python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
LEGALMATRIX_DATA_DIR=backend/data backend/venv/bin/uvicorn app.main:app --app-dir backend --port 8000
cd backend && venv/bin/python -m pytest -q   # 76 passed, OCR mocked

# audit one product against 7B oracle (WSL images path)
python scripts/pipeline_audit.py --images-dir /mnt/e/SIH_installation_files/images --product 6
python scripts/regex_audit.py --help; python scripts/cascade_bench.py --help

# frontend dev
cd frontend && npm install && npm run dev   # http://localhost:3000, admin/admin@123
```

Ollama: `ollama pull qwen2.5vl:7b qwen2.5:3b`; `Modelfile` sets `num_ctx 8192`.
Products: `image{N}_{k}.jpg`, N in 3–28,65–68 (1–2 deleted, crappy); always feed ALL
k of one N together.

## 5. Security — READ THIS

- A classic token starting `ghp_` was pasted in chat to set up this repo. **It is
  compromised: revoke it NOW at github.com → Settings → Developer settings →
  Tokens, then create a fresh fine-grained token (contents:read/write, pull
  requests) per teammate.** Never paste tokens in chat/issues/docs again.
- Never commit: `.env*`, `*.pem/*.key`, `backend/data/` (db+evidence), `images/`
  (copyrighted, 224 MB), `venv/`, `node_modules/`, `*.db`. This repo's `.gitignore`
  already excludes them — keep it that way. Repo remote must stay
  `https://github.com/SharmanRawat/LegalMatrix-V2.git` with NO embedded token;
  authenticate via `gh auth login` or `GIT_ASKPASS`/credential helper.
- Default creds `admin / admin@123` + `LEGALMATRIX_AUTH_SECRET=change-me…` are
  demo-only. Rotate before any deployment or shared demo with real data.

## 6. Open questions

- Hindi-label accuracy target vs English (manner rules need both)?
- PDP-area source for length/area font tier (currently weight/volume path only)?
- Evidence retention/quota policy for enforcement deployment?
