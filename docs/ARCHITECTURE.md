# ARCHITECTURE — LegalMatrix

## 1. Runtime topology

```
Inspector phone/PWA --HTTPS--> Next.js 16 frontend (:3000) --/api proxy--> FastAPI (:8000)
                                                                                 |
                        +---------------------------+----------------------------+----------------+
                        |                           |                            |                |
                        v                           v                            v                v
                  Ollama GPU server          SQLite legalmatrix.db          evidence/ dir     heatmaps/
                  qwen2.5vl:7b (VLM)         users/inspections/             photos +          overlays
                  qwen2.5:3b (SLM)           inspection_images              SHA-256           per photo
                  (one central server;
                   phones need only a browser)
```

- `docker-compose.yml`: `ollama` (nvidia runtime) + `backend` + `frontend`.
- Backend must reach Ollama at `OLLAMA_HOST` (`http://ollama:11434` in compose,
  `http://localhost:11434` in dev). `Modelfile`: `FROM qwen2.5vl:7b, num_ctx 8192`.
- Frontend is a PWA (`public/sw.js`, `manifest.json`), App Router + Turbopack,
  React 19, Tailwind v4, axios with bearer injection.

## 2. Backend layout (`backend/app/`)

| Path | Responsibility |
|---|---|
| `main.py` | FastAPI app, lifespan DB init + admin seed, CORS, routers, `GET /rules /health /` |
| `config.py` | All settings from env, call-time `get_data_dir()/get_database_path()/get_evidence_dir()` so tests can isolate |
| `api/auth.py` | login, `optional_auth`, `require_roles` |
| `api/inspections.py` | `POST /inspect`, `POST /inspect/report` (PDF), `GET/PATCH /inspect/{id}`, evidence/heatmap/certificate serving, JSON/CSV export |
| `api/dashboard.py`, `api/search.py` | stats/trends/recent; search filters |
| `core/rule_engine.py` | 7-rule evaluation + format checks, loads `data/rules.json` |
| `services/inspection_service.py` | **Pipeline orchestrator** (`run_inspection`): extract per image → merge → missing → confidence → optional VLM rescue → compliance → font → misleading → heatmaps → radar → persist |
| `services/ocr_engine.py` | **Fast path (default)**: enhance → RapidOCR (onnxruntime, word boxes+conf) → `field_classifier` (SLM qwen2.5:3b, regex fallback) → tokens + field_map + regions. 742 lines; includes ₹-glyph fixes, glued-date splitting, month-glyph repair, multi-pass escalation |
| `services/field_classifier.py` | 1015-line LLM + regex classifier (address-line, company-strip, edible support) |
| `services/ocr_service.py` | **Legacy/oracle path**: direct qwen2.5vl:7b extraction + `regions` boxes + currency re-verify + prompt fingerprint. Used as ground-truth oracle in audits and as VLM rescue |
| `services/vlm_rescuer.py` | Rescue low-confidence CPU results with VLM (only if `VLM_RESCUE_ENABLED=1`) |
| `services/preprocessing.py` | EXIF transpose, resize (`OCR_ENHANCE_MAX_SIDE=1920`), grayscale/Otsu/inverted/CLAHE/2x variants, capture-time |
| `services/font_measurement.py`, `scale_calibrator.py` | Barcode→credit-card→EXIF calibration chain, cap-height from token boxes, required-mm lookup, `CANNOT_MEASURE` gating |
| `services/price_engine.py` | MRP/net-qty → expected USP math + exemption logic |
| `services/compliance_scorer.py` | Radar axes + grade A–D + merge across photos |
| `services/heatmap_generator.py` | Field-box + calibration-box overlays per photo |
| `services/post_processor.py` | Value canonicalization |
| `services/certificate_generator.py` | Tamper-evident certificate PDF |
| `repositories/users.py`, `inspections.py` | Raw SQL (no ORM); `save/get/list/update_overrides/add_image` |
| `database/models.py` | Schema + idempotent `_migrate` |
| `models/schema.py`, `utils/` | Pydantic schemas, helpers |
| `scripts/pipeline_audit.py` | **Product-by-product oracle audit** (see §4) |
| `scripts/regex_audit.py`, `cascade_bench.py` | Regex-only ablation; CPU vs VLM cost/accuracy bench |
| `tests/` | 76 pytest tests, OCR mocked (`conftest.py`); covers rules, USP math, repos, dashboard/search, auth gating, pipeline, PDF/exports, evidence, font calibration/gating, synthetic cap-height recovery, product-6 regression (`test_product6_fixes.py`) |

## 3. Inspection pipeline (single request)

1. `_save_uploads` — 1–3 images to temp files (400 on 0/>3/empty).
2. Per image: `ocr.extract_structured(path)` → `{10 fields, tokens, field_map, regions, ocr_meta}`.
3. `merge_extractions` — price block (mrp/usp/net_qty, need ≥2) and date block (mfg/expiry, need 2) each taken from the single best photo; other fields longest-wins; `consumer_care` prefers contact-channel match (`@|toll free|1800|10-digit`), else blank (kills disclaimer-poisoning).
4. `compute_missing` (skips `dimensions_where_relevant` when `edible != no`) → `compute_overall_status` (critical missing → `POTENTIAL_VIOLATION`, else `REVIEW_REQUIRED`, else `COMPLIANT`).
5. `_extraction_confidence` — 0–100 overall + per-field (engine class × boxed-evidence × coverage ratio).
6. Optional rescue: if `VLM_RESCUE_ENABLED=1` and overall < `VLM_RESCUE_CONFIDENCE_THRESHOLD` (55) → `vlm_rescuer` re-reads.
7. `_verify_mrp_currency` — bare-number MRP gets a second VLM look for a dropped ₹/Rs. glyph before failing Rule 6(1)(e).
8. `rule_engine.evaluate_compliance` (+ currency_verified) → violations, score `passed/total*100`.
9. Font: net-qty → required mm → per-photo `_measure_font_for_image` (OCR tokens preferred, VLM box fallback), first measurable wins, `CANNOT_MEASURE` kept aside honestly.
10. `_check_misleading` — mrp_format, usp==mrp, usp vs computed mismatch.
11. Heat-maps rendered into evidence dir; radar built/merged; prompt fingerprint + engine labels recorded; evidence SHA-256 chained; everything persisted with `user_id`.

`PATCH /inspect/{id}` (`apply_manual_overrides`) re-runs steps 4+8+10+radar on corrected values and logs `{original, corrected, by_user_id, at}` in `meta.manual_overrides`.

## 4. Oracle audit loop (how extraction accuracy is improved)

`backend/scripts/pipeline_audit.py` runs the REAL web pipeline per product group and
diffs every field against the `qwen2.5vl:7b` oracle read of the same photos:

```
python scripts/pipeline_audit.py --images-dir /mnt/e/SIH_installation_files/images \
    --product 6 --oracle qwen2.5vl:7b --classifier qwen2.5:3b --out-dir /tmp/pipeline_audit
```

- OCR tokens + oracle reads are disk-cached by image mtime → re-runs after tuning
  preprocessor/regex/SLM prompt are near-free (classifier+merge only).
- Outputs per-product diffs + per-field agreement + JSON/CSV reports.
- One product at a time (start with 6), all its images together — never single-image cherry-picking.

## 5. Configuration (env)

| Var | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | VLM/SLM server |
| `QWN_MODEL` | `qwen2.5vl:7b` | Legacy VLM extraction model |
| `VLM_RESCUE_MODEL` | `qwen2.5vl:7b` | Rescue model |
| `FIELD_CLASSIFIER_MODEL` | `qwen2.5:3b` | SLM classifier |
| `FIELD_CLASSIFIER_ENABLED` | `1` | `0` = regex only |
| `VLM_RESCUE_ENABLED` | `0` | `1` = escalate low-confidence to VLM (needs GPU) |
| `VLM_RESCUE_CONFIDENCE_THRESHOLD` | `55` | Rescue trigger |
| `OCR_ENGINE` | `auto` | `rapidocr/paddleocr/vlm` override |
| `OCR_ENHANCE_ENABLED` / `OCR_ENHANCE_MAX_SIDE` | `1` / `1920` | Preprocessing |
| `OCR_MULTI_PASS_ENABLED` / `ON_FAIL` | `1` / `1` | Extra variants fused on missing mrp/mfg/expiry |
| `OCR_PANE_ZOOM_ENABLED` | `0` | Expensive per-region 3× re-read (helps ~1/7 products) |
| `VLM_LOCALIZATION` | `1` | VLM returns `regions` boxes |
| `OCR_TIMEOUT_SECONDS` / `OCR_MAX_IMAGE_SIZE` | `180` / `896` | VLM call budget / resize |
| `FONT_CALIBRATION` | `auto` | `credit_card/barcode/exif` override |
| `LEGALMATRIX_DATA_DIR` | `backend/data` | SQLite + evidence root (tests override per-test) |
| `LEGALMATRIX_AUTH_SECRET` / `_TTL_HOURS` | `change-me…` / `12` | Token signing — **change in prod** |
| `ALLOWED_ORIGINS` | `localhost:3000…` | CORS |

## 6. Deployment

- Dev: Ollama + `uvicorn app.main:app --app-dir backend` + `npm run dev` (see setup guide).
- Prod: `docker-compose up --build` (Ollama with NVIDIA runtime, backend volume
  `legalmatrix_data:/app/backend/data`, frontend standalone). Swap `repositories/`
  for Postgres beyond single node. Change auth secret + admin password.
