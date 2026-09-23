# DeepSeek Handoff Prompt — LegalMatrix

Paste the block below into DeepSeek verbatim, along with any files you want it to act on.

---

```
You are now the lead engineer on a hackathon-to-production project called **LegalMatrix**
(SIH 2026, Problem Statement 26034 — Legal Metrology compliance checking for packaged consumer goods
in India). The enforcement angle matters: this tool is used by Legal Metrology inspectors in the field.
NEVER return a compliance verdict you cannot defend; when evidence is insufficient, return a
"REVIEW_REQUIRED" / manual-review result rather than guessing. A tool that generates false accusations
due to faulty assumptions is unusable and legally indefensible.

Read the repository at /home/sharman/project_ml_improved before answering. Prefer editing existing
files and matching the existing code style (no comments unless asked, keep the codebase lean, run
`backend/venv/bin/python -m pytest backend/tests -q` — currently 62 tests pass — and the frontend
`npx tsc --noEmit && npx eslint app --max-warnings=0 && npx next build` all clean).

=====================================================================
1. THE PRODUCT
=====================================================================
Field app (Next.js PWA on the inspector's phone) -> FastAPI backend -> central GPU Ollama server running
Qwen2.5-VL. Inspectors photograph a retail product's label (front, top, barcode, etc., several images
per product). The backend:

   1) Extracts structured declarations from the label images with a VLM
      (mrp, usp, net_quantity, product_name, manufacturer, manufacturing_date,
       expiry_date, consumer_care, dimensions).
   2) Runs those declarations through a deterministic Legal-Metrology (Packaged Commodities Rules)
      rule engine (data/rules.json + app/core/rule_engine.py), flagging missing/critical/format
      violations and computing a compliance score.
   3) Measures the printed numeral font size (Legal Metrology requires minimum numeral heights by
      net quantity) with a pixel->mm calibration that must be honest and traceable — never fabricated.
   4) Stores the record + SHA-256 evidence chain, serves PDF/JSON/CSV exports.

=====================================================================
2. CURRENT STACK (do not change arbitrarily)
=====================================================================
- Backend:  FastAPI (Python 3.12+), SQLite via stdlib sqlite3 (no ORM), OpenCV
            (barcode detection + font measurement), Pillow (EXIF), fpdf2 (PDF reports),
            httpx (VLM calls). No EasyOCR, no PaddleOCR, no Tesseract anywhere anymore.
- Vision:   Qwen2.5-VL 7B (qwen2.5vl:7b) through local Ollama. Supports optional localization
            (`regions`) in normalized 0-1000 coordinates for the MRP and net-quantity text.
- Frontend: Next.js 16 (App Router + Turbopack), React 19, Tailwind v4, axios, native PWA
            service worker (next-pwa was removed — it was never active). `output: 'standalone'`.
- Ops:      docker-compose runs 3 services (ollama + backend + frontend); production
            Dockerfile.frontend (multi-stage standalone) and Dockerfile.backend (python:3.12-slim).

=====================================================================
3. REPOSITORY LAYOUT
=====================================================================
backend/
  app/
    config.py                      # env-driven settings (paths resolve at call time for tests)
    main.py                        # FastAPI app, lifespan DB init + admin seed
    api/                           # routers: inspections, auth, dashboard, search, evidence
    services/
      ocr_service.py               # THE live VLM extraction path (Qwen via Ollama)
      inspection_service.py        # full pipeline orchestration + merging + font measure
      font_measurement.py          # calibration chain + cap-height measurement
      price_engine.py              # USP/MRP consistency helpers
      auth_service.py              # HMAC tokens, PBKDF2, roles ADMIN/INSPECTOR/VIEWER
    repositories/                  # users, inspections (SQL)
    database/models.py             # schema
    core/rule_engine.py            # deterministic compliance rules
  tests/                           # pytest — 62 passing (OCR is mocked in unit tests)
  data/rules.json                  # codified Legal Metrology rules incl. 2026 amendments
  requirements.txt / requirements-dev.txt
frontend/
  app/                             # / (inspect), /login, /dashboard, /history, /inspection/[id]
  app/lib/api.ts                   # axios wrapper, bearer-token injection, apiError helper
  app/components/Navbar.tsx, ServiceWorkerRegister.tsx
  public/sw.js + manifest.json     # PWA (registered in production only)
  next.config.ts                   # API_UPSTREAM env + /api rewrite to backend
Dockerfile.backend, Dockerfile.frontend, docker-compose.yml, .dockerignore
Modelfile                          # FROM qwen2.5vl:7b, num_ctx 8192
images/                            # 78 real label photos = validation dataset
                                   # (image{N}_{M}.jpg -> product N, view M; 32 products)
README.md                          # rewritten, submission-grade
```

=====================================================================
4. ENV CONFIG (backend/app/config.py + ocr_service.py)
=====================================================================
- OLLAMA_HOST            default http://localhost:11434
- QWN_MODEL              default qwen2.5vl:7b   (also used as inspection "method" string)
- OCR_TIMEOUT_SECONDS    default 180
- OCR_MAX_IMAGE_SIZE     default 896            (thumbnail long-edge px sent to the VLM)
- VLM_LOCALIZATION       default "1"            (prompt asks Qwen for `regions` boxes)
- LEGALMATRIX_DATA_DIR   default backend/data   (SQLite + evidence/)
- LEGALMATRIX_AUTH_SECRET, LEGALMATRIX_AUTH_TTL_HOURS (default 12h)
- ALLOWED_ORIGINS        default http://localhost:3000,http://127.0.0.1:3000
- Frontend: API_UPSTREAM (Next rewrite target, default http://localhost:8000)

=====================================================================
5. THE LIVE OCR PIPELINE (ocr_service.py)
=====================================================================
- extract_structured(image_path) sends the resized JPEG + one strict-JSON prompt to
  `{OLLAMA_HOST}/api/chat` (model = QWN_MODEL, temperature 0.0, num_ctx 8192), retries up to
  max_retries=3. On garbage output (all '?', too short, unparseable) it unloads the model with
  `ollama stop QWN_MODEL`, sleeps, retries. Returns EXACTLY the EXPECTED_KEYS strings, plus an
  optional `regions` dict {mrp|[x1,y1,x2,y2], net_quantity:[...]} — 4 floats, 0-1000 normalized,
  origin top-left — when VLM_LOCALIZATION is on and the model cooperated.
- IMPORTANT history: adding a concrete coordinate example to the prompt caused the 3B model to
  ECHO the example box verbatim on unrelated images, and an earlier 'regions REQUIRED' phrasing
  made Qwen emit unquoted JSON keys that broke the parser and cascaded into full retry loops.
  The current prompt has NO concrete numbers and says "derive values and boxes solely from THIS
  image" — do not reintroduce examples or strictly-required phrasing.

=====================================================================
6. FONT MEASUREMENT & CALIBRATION (font_measurement.py) — RULES WE LOCKED
=====================================================================
Calibration precedence (calibrate()):
  1. "barcode": cv2 barcode detector -> pixels-per-mm assuming BARCODE_WIDTH_MM=20.0. EAN-13
     magnification is 0.8-2.0x, so accuracy is <= ±15% — reported as uncertainty, never hidden.
  2. "exif": pure camera math, no reference object in frame. 35mm-equiv focal -> horizontal FOV,
     `ppm = image_width / (2 * D * tan(FOV/2))`. FocalLengthIn35mmFilm (0xA405) or FocalLength
     (0x9205); SubjectDistance (0x920A). GATED by plausibility bounds EXIF_MIN_PPM=1.0 /
     EXIF_MAX_PPM=300.0 — phone SubjectDistance is frequently garbage (we measured ~0.28 px/mm
     on real photos, i.e. "camera 11 m away"), and we DECLINE (return None) rather than emit a
     nonsense reading. uncertainty ±20%, result carries calibration_info.
  3. Neither -> measure() returns None. "Cannot calibrate, manual review" is a valid answer.
Measurement:
  - measure(image_path, required_mm, text_box=None). text_box = VLM `regions` box
    (normalized 0-1000 via _normalize_box; "auto" box_format was REMOVED — default is "normalized").
    When a box is given we measure CAP-HEIGHT: dominant capital/digit stroke cluster inside the
    cropped region via connected components on a binarized crop, so descenders never inflate the
    reading (method="cap_height"). Without a box we fall back to a median heuristic over the lower
    half of the image (method="heuristic_lower_half"), excluding the barcode bbox.
  - Status bands: lower_bound=mm-unc, upper=mm+unc -> COMPLIANT / POTENTIAL_VIOLATION /
    REVIEW_REQUIRED. Uncertainties come from calibration source (0.15 barcode, 0.20 exif).

DEFENSIBILITY GATES ADDED 2026-09-13 (review feedback from a CV+legal engineer — LOCKED):
  - measure() NEVER returns None: it returns {"status": "CANNOT_MEASURE", "calibration": "none",
    "calibration_rejected_reason": "barcode_not_detected; exif_implausible(ppm=0.28)"} instead.
    barcode detection is further gated: >=4 corner points AND convex hull required (false-positive
    reject). EXIF reasons are granular (tags_missing / focal_missing / implausible(ppm)).
  - VLM box sanity gate _box_geometry_ok + _box_is_plausible: box >=10px, area fraction in
    [0.002, 0.15], aspect 1.2-12, >=3 glyphs, and stroke-height stdev/mean <= 0.4 (rejects
    multi-line/logo regions). A rejected box FALLS BACK to the heuristic and records
    `box_rejected_reason` (e.g. "area_too_large", "multimodal_heights", "no_glyphs_found").
  - measured_mm outside [0.3, 10.0] x required_mm -> REVIEW_REQUIRED + "implausible": true.
    (Kills the 0.18mm / 6.35mm outliers from section 7.)
  - heuristic_lower_half results are FORCED to REVIEW_REQUIRED (informational only) until validated
    on real data — an automated COMPLIANT/POTENTIAL_VIOLATION font verdict now REQUIRES a clean VLM
    box + barcode/EXIF calibration + plausible mm.
  - cap_height_px bins RELATIVE to median stroke height (median//10) instead of fixed 2px (a 5px
    digit at low ppm used to be quantized ±40%). Morphological open is skipped for regions <40px
    tall (a fixed (2,2) open shatters ~10px glyphs). Double imread removed; _glyph_heights_in_region
    accepts a loaded array.
  - run_inspection records image_index/image_path of the measured photo, prioto EXIF capture time
    (DateTimeOriginal 0x9003), and extraction_prompt_hash (SHA-256 of the exact VLM prompt) for
    chain of custody. Frontend renders CANNOT_MEASURE + implausible + traceability lines.
  - Result carries traceable extras: calibration_info (exif), calibration_bbox (barcode), height_px,
    glyph_count, method, ppm. Tests: 76 green (14 new font/gating/synthetic-GT tests).
- inspection_service.run_inspection now iterates ALL product images and uses the FIRST image that
  yields a calibrated measurement (previously it only ever tried the first image — a real bug).

=====================================================================
7. VALIDATED BEHAVIOUR ON REAL DATA (test bench, images/ = 32 products / 78 photos)
=====================================================================
Run the same bench with:  backend/venv/bin/python /tmp/opencode/testbench_full_products.py
(that script groups images by product and calls run_inspection per product). Results:

- qwen2.5vl:3b (retired): ~15 products with missing or hallucinated MRP ("100% PURE COFFEE",
  "15 MINS"), ~12 complete '?????' garbage-crash sequences, many parse-fail retry loops,
  model resets between images. Unusable at scale.
- qwen2.5vl:7b (current): ZERO garbage, ZERO crash/retry loops across all 78 images; realistic
  MRP strings with currency markers ("Rs. 265", "₹ 47.00", "₹150/-", "Rs. 109.00"); cap-height
  font measurement activates on ~11 products (e.g. 3.49mm, 1.79mm, 6.35mm); most products are
  REVIEW_REQUIRED only because "dimensions_where_relevant" is (correctly) absent. Full bench ~13
  min on the hardware below. The 3B->7B swap is the single biggest quality fix and is non-negotiable.

=====================================================================
8. HARDWARE ENVIRONMENT
=====================================================================
- RTX 4060 8 GB VRAM, system RAM only ~7 GB (tight — be careful with memory-heavy changes),
  NVIDIA driver 592.82 / CUDA 13.1. Ollama already has qwen2.5vl:3b and qwen2.5vl:7b pulled locally.
- Live at: backend uvicorn :8000, frontend :3000, Ollama :11434.
- FRONTEND RUN (IMPORTANT): the build is `output: 'standalone'`, so run
  `node .next/standalone/server.js` (from `frontend/`), NOT `npm run start`/`next start`
  (Next 16 prints "next start does not work with standalone"). After every build you must
  re-copy assets into standalone: `cp -r .next/static .next/standalone/.next/static &&
  cp -r public .next/standalone/public`. Launch detached with
  `setsid bash -c 'exec node .next/standalone/server.js </dev/null >>/tmp/opencode/next-run.log 2>&1' &`
  (a `next start` server restarted across a rebuild serves HTML pointing at chunks that no
  longer exist → 500 → Chrome shows "This page couldn't load", reproduced headlessly 2026-09-13).
- PROXY TIMEOUT: Next 16's rewrite proxy (rewrites → API_UPSTREAM) hard-kills upstream
  responses after **30 s** (`node_modules/next/dist/server/lib/router-utils/proxy-request.js`:
  `proxyTimeout ?? 30000`). AI scans take ~30-40 s → every scan 500'd until
  `experimental.proxyTimeout: 300000` was added to `frontend/next.config.ts` (2026-09-13).
  If backend work gets slower, raise it again — the knob is baked into the standalone build,
  so it requires a rebuild + restart + static re-copy.
- SERVICE WORKER: `public/sw.js` is now a SELF-DESTRUCTING worker (registers → clears caches →
  unregisters). Do NOT re-add precaching of '/' while iteration churn is high: a cached shell
  references old chunk hashes after a rebuild and produces the same black screen.

=====================================================================
9. KNOWN LIMITATIONS / OPEN ISSUES (acknowledge, don't paper over)
=====================================================================
1. merge_extractions uses "longest string wins" per key. It can couple fields from different
   photos of the same product (e.g. it once merged netqty "250 ml (228 g)" with an MRP taken from
   a different-angle photo). Needs a smarter per-field selection (prefer numeric-MRP candidates,
   prefer the net_qty that parses with a unit, etc.).
2. Some products legitimately yield no MRP (Hindi/Devanagari numeral labels, text-only faces,
   marks only on another panel) — the pipeline correctly returns empty->REVIEW_REQUIRED. Do not
   force a value there.
3. VLM MRP strings are label-realistic, not normalized ("Rs. 265", "119/-", "₹ 40.00"). The rule
   engine REQUIRES the ₹/Rs/INR marker (legal: MRP must show currency), so normalization that strips
   the marker would fight the law — only strip/parse when comparing numeric prices (price_engine
   already extracts numbers). Do not "clean" MRP below the currency marker.
4. EXIF fallback is gated and therefore rarely active on this dataset — most font measurements rest
   on the barcode leg, which is fine because labels carry EAN-13 barcodes in the same focal plane.
5. heuristic_lower_half median can return tiny readings (~0.2 mm) when the product name dominates
   the lower half — it is now FORCED to REVIEW_REQUIRED (informational) until validated. Prefer
   cap_height via VLM boxes when available.
6. Backend currently has NO rate limiting / brute-force protection on auth (out of scope for SIH,
   flagged in README as a production TODO).
7. The default seeded admin is admin/admin@123 (must change in prod; auth is PBKDF2 + HMAC, no
   external deps).

=====================================================================
10. WHAT HAS BEEN DONE (summary for your context)
=====================================================================
- Fixed all 4 previously-failing tests -> 76 green. Repos tests use distinct ids
  (LGM-TEST-0001/2/3/4); font tests rewritten as gating + real-label tests.
- Added auth-protected evidence endpoint GET /api/inspect/{id}/evidence/{index} with
  path-traversal guard + tests.
- ocr_service env-configurable (OLLAMA_HOST/QWN_MODEL/OCR_TIMEOUT_SECONDS/OCR_MAX_IMAGE_SIZE/
  VLM_LOCALIZATION), Modelfile -> qwen2.5vl:7b.
- requirements.txt pinned (incl. numpy 2.5.3, opencv-contrib-python-headless 5.0.0.93) +
  requirements-dev.txt (pytest, python-barcode) — python-barcode is dev/test-only.
- Full frontend: login, dashboard (stats/status/trend/violations/recent), history (search+filter+CSV),
  inspection/[id] (evidence via auth blob, JSON/CSV/PDF export), Navbar, lib/api.ts, native PWA sw.js.
- Docker: production multi-stage frontend (standalone), backend python:3.12-slim
  (numpy 2.5 dropped py3.10), compose 3 services, .dockerignore.
- Root README rewritten (architecture, PS coverage, quickstart, tests, deployment, security).
- Root duplicate Next scaffold removed — frontend/ is the only source of truth.
- Purged ALL dead OCR code: backend/app/services/paddle_ocr.py, vision_extractor_qwen.py,
  core/ocr_engine.py, services/measurement.py, root vision_extractor_qwen.py,
  backend/test_qwen_simple.py, backend/debug_qwen.py. Tests still green.
- Model default 3B->7B everywhere (ocr_service, config.py, Modelfile, README) + resolution 600->896.
- Font measurement now scans every product image until one calibrates (not just the first).
- Implemented the full defensibility-gate review (see section 6): CANNOT_MEASURE + reasons, VLM box
  sanity gate + fallback, implausibility bounds, heuristic forced to REVIEW_REQUIRED, relative bin
  sizing, adaptive morphology, barcode convexity, image_index / capture-time / prompt-hash
  traceability, frontend CANNOT_MEASURE + implausible rendering, synthetic ground-truth tests.
  Dataset smoke over 78 images: 61 CANNOT_MEASURE (uncalibrated), 17 barcode-calibrated heuristic
  -> all REVIEW_REQUIRED, image11_2/image8_2 flagged implausible (0.21/0.26mm). CLAUDE_FONT_BRAINSTORM.md
  holds the review that drove this.

=====================================================================
11. SIH SUBMISSION CONTEXT (deadline 15 Sep 2026, theme PS 26034)
=====================================================================
~22 of 500 ideas submitted, we want one strong entry. Planned differentiators to lead with:
(1) barcode-calibrated font-size measurement with HONEST reported uncertainty (not a fixed figure),
(2) immutable SHA-256 evidence chain per inspection,
(3) fully deterministic codified Legal-Metrology rule engine (no LLM judgment on compliance),
(4) one central GPU LLM + fully offline-capable field PWA (cheap field devices).
Candidate new features under discussion: human-in-loop correction->recompute, GTIN/barcode quick-check
mode, Hindi-declaration presence check, GPS+inspector identity+timestamp on scans, report QR linking
to the stored record, and an accuracy benchmark table on the 78-image dataset for the submission.

=====================================================================
12. YOUR JOB NOW (when asked, pick up here — don't redesign what we locked)
=====================================================================
Suggested next tasks, in rough priority:
1. Fix the merge_extractions cross-photo coupling with a field-aware candidate picker (+ tests)
   (STILL OPEN — not done in the 2026-09-13 round).
2. Re-run the full 78-image bench through run_inspection (VLM on) and produce the accuracy/quality
   benchmark table for the SIH deck (by product: status, score, missing, font mm, calibration
   source; aggregate counts). Expect far fewer cap_height readings now (gates + REVIEW_REQUIRED
   heuristic); that is the correct, defensible outcome — report it as such.
3. Draft the SIH 6-slide idea deck content (PDF), leading with the differentiators above and the
   honest validation story from section 7.
4. Optionally: GTIN quick-check mode using the decoded barcode + Hindi-panel presence check.
5. Anything you change must keep backend pytest green (76) and the frontend build clean.

Ask before making architectural changes to the locked items (section 6 calibration rules,
single VLM extraction, custom-dead-code-free stack, test counts).
```