# LegalMatrix (MetrIQ)

**AI-powered Legal Metrology compliance inspection for packaged commodities** — SIH 2026
Problem Statement **PS 26034** (Ministry of Consumer Affairs, Food & Public Distribution,
Department of Consumer Affairs). A field inspector photographs a product label with their
phone; the platform extracts the declarations with CPU OCR + a lightweight on-device
classifier, checks them
against the **Legal Metrology (Packaged Commodities) Rules, 2011** (as amended through 2026),
measures font readability, flags missing or misleading declarations, and produces an evidence-backed
report (PDF, JSON, CSV). Every scan is persisted with cryptographic evidence hashes for future
enforcement action.

## Architecture

```
┌─────────────┐   HTTPS/browser   ┌──────────────┐   /api proxy   ┌───────────────────┐
│ Inspector   │ ◄──────────────► │ Next.js 16   │ ────────────►  │ FastAPI backend   │
│ phone/PWA   │   (PWA, offline) │ frontend :3000│                │ :8000             │
└─────────────┘                  └──────────────┘                └─────────┬─────────┘
                                                                           │
                                       ┌───────────────────────────────────┼──────────────┐
                                       ▼                                   ▼              ▼
                               ┌──────────────┐                    ┌────────────┐  ┌──────────────┐
                               │ Ollama       │  (CPU classifier  │ legalmatrix│  │ evidence/    │
                               │ qwen2.5:3b   │   for field map)  │ .db        │  │ dir (photos, │
                               │ text-only    │                    │            │  │ sha-256)     │
                               └──────────────┘                    └────────────┘  └──────────────┘
```

Key design decision: inference stays **CPU-first** — RapidOCR (PP-OCRv3, ONNX) reads the
label, and a small `qwen2.5:3b` classifier maps the OCR lines to declaration fields, so the
whole pipeline runs on a field inspector's laptop with no GPU. An optional Qwen2.5-VL
vision-model rescue exists for hard labels (env vars below) but is **off by default** — the
demo and submission run the CPU path. Users only need a browser/PWA — no model download or
mobile compute on the device.

## Stack

- **Backend** — FastAPI (Python 3.12+), SQLite (stdlib), OpenCV (barcode + font measurement),
  fpdf2 (PDF reports). No ORM, no heavy frameworks.
- **Inference (CPU-first, by design)** — RapidOCR (PP-OCRv3, ONNX) for detection +
  recognition, then a small Ollama classifier (`qwen2.5:3b`) maps OCR lines to the 9
  declaration fields. Runs on a field inspector's laptop with no GPU. An optional Qwen2.5-VL
  vision-model rescue exists for hard labels and is disabled by default (see `README` env
  vars) — it is not required for the demo path.
- **Frontend** — Next.js 16 (App Router, Turbopack), React 19, Tailwind v4, PWA service worker.
- **Compliance engine** — rule set in `data/rules.json` consuming the extracted declarations.

## Directory layout

```
backend/
  app/
    config.py                      # settings (paths resolve at call-time for easy test isolation)
    main.py                        # FastAPI app, lifespan DB init + admin seed
    api/                           # inspections, auth, dashboard, search endpoints
    services/                      # inspection pipeline, price engine, rule engine, auth, OCR, font
    repositories/                  # users, inspections (SQL)
    database/models.py             # schema (users, inspections, inspection_images)
    core/rule_engine.py            # compliance rules & evaluation
  tests/                           # pytest suite (OCR mocked) — 62 tests
  data/rules.json                  # codified rules incl. 2026 amendments
  requirements.txt                 # runtime deps
frontend/
  app/                             # pages: / (inspect), /dashboard, /history, /inspection/[id], /login, /admin, /verify, /font-measurement
  app/lib/api.ts                   # axios wrapper with bearer-token injection
  public/sw.js + manifest.json     # PWA
docker-compose.yml                 # ollama + backend + frontend
Modelfile                          # Ollama model definition (qwen2.5vl:7b)
images/                            # 70+ real label photos used for validation/demo
```

## Feature coverage vs PS 26034

| Requirement | Where |
|---|---|
| Photo upload / capture (1–3 images) | `frontend/app/page.tsx`, `POST /api/inspect` |
| OCR extraction + classifier mapping of 9 declarations | `backend/app/services/ocr_engine.py` (CPU RapidOCR + `qwen2.5:3b`) |
| Mandatory declaration checks (7 fields) | `core/rule_engine.py` |
| MRP / USP math, net quantity parsing | `services/price_engine.py` |
| Font size & readability measurement | `services/font_measurement.py` (barcode-calibrated PPM, cap-height via VLM boxes, honesty gating) |
| Misleading-declaration heuristics | `services/inspection_service.py` |
| PDF report with embedded evidence photos | `GET /api/inspect/{id}/report` (stored, corrected row) + `POST /api/inspect/report` |
| Editable exports (JSON / CSV) | `GET /api/inspect/{id}/export` |
| Evidence photo attachment + SHA-256 hashing | `services/inspection_service.py`, `/api/inspect/{id}/evidence/{i}` |
| Evidence Planner (auto-flags declarations still required for a defensible decision) | `core/rule_engine.py` `missing_declarations`, REVIEW_REQUIRED reasons + calibration exclusions in `inspection_service.py` |
| Certificate QR + public verification | `GET /api/inspect/{id}/certificate`, `GET /api/inspect/verify`, `/verify` page |
| Report repository / inspection history | `repositories/inspections.py` |
| Role-based auth (ADMIN/INSPECTOR/VIEWER) | `api/auth.py`, `services/auth_service.py` |
| Admin user management (search / scans / password reset) | `frontend/app/admin`, `/api/auth/users*` |
| Dashboard (stats, trends, recent) | `GET /api/dashboard/stats` |
| Search (id, product, manufacturer, dates, status) | `GET /api/search` |
| Technical documentation | this file + `backend/tests/` |

## Quickstart (development)

Prerequisites: Python 3.12+, Node 20+, and [Ollama](https://ollama.com) with the small
classifier model.

```bash
# 1. ollama model (CPU path needs only the small classifier)
ollama pull qwen2.5:3b

# 2. backend
python -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
LEGALMATRIX_DATA_DIR=backend/data backend/venv/bin/uvicorn app.main:app --app-dir backend --port 8000

# 3. frontend
cd frontend && npm install && npm run dev

# 4. open http://localhost:3000 — sign in with the admin credentials set in
#    backend/.env (see LEGALMATRIX_ADMIN_USERNAME / LEGALMATRIX_ADMIN_PASSWORD)
```

Environment variables (backend): `OLLAMA_HOST` (default `http://localhost:11434`),
`FIELD_CLASSIFIER_MODEL` (default `qwen2.5:3b` — the small classifier used by the CPU
path), `QWN_MODEL` (default `qwen2.5vl:7b` — the optional vision model), `VLM_RESCUE_ENABLED`
(default `0` — set to `1` to enable the vision rescue for hard labels), `VLM_RESCUE_MODEL`
(default `qwen2.5vl:7b`), `LEGALMATRIX_AUTH_SECRET`, `LEGALMATRIX_DATA_DIR`,
`OCR_TIMEOUT_SECONDS`, `OCR_MAX_IMAGE_SIZE` (default `896`), `VLM_LOCALIZATION` (default `1`),
`ALLOWED_ORIGINS`.

## Tests

```bash
cd backend && venv/bin/python -m pytest -q        # 76 passed (OCR mocked)
```

The test suite exercises: rule evaluation, USP/MRP math and exemptions, repositories,
dashboard/search statistics, HMAC auth + role gating, the full inspect pipeline, PDF bytes,
JSON/CSV exports, evidence serving, font-measurement calibration/gating/VLM-box-sanity and
synthetic ground-truth cap-height recovery on rendered labels.

## Deployment

Three services run as containers (see `docker-compose.yml`): an Ollama server (CPU for the
classifier; the optional vision-rescue model can be pinned to an NVIDIA runtime),
the FastAPI backend, and the Next.js frontend resting behind a
production server. The backend container must be able to reach Ollama
(`OLLAMA_HOST=http://ollama:11434`). SQLite paths and evidence storage are mounted as
volumes; swap the repositories layer for Postgres when scaling beyond a single node.

> **Security note:** change `LEGALMATRIX_AUTH_SECRET` and the seeded admin password
> (`LEGALMATRIX_ADMIN_PASSWORD`, in `backend/.env`) before any production deployment.

## Built vs. Next

### Built and submitted (this release)

- End-to-end label inspection: photo upload/capture → CPU OCR + classifier extraction of 9
  declarations → rule evaluation against the 2011 Rules (as amended through 2026) → status
  + score.
- Evidence-backed, tamper-evident outputs: every scan is persisted with per-image SHA-256
  hashes; PDF reports, JSON/CSV exports, and a compliance certificate with a QR code whose
  payload (`inspection_id|evidence_hash`) can be verified on the public `/verify` page.
- Instructor corrections: an ADMIN/INSPECTOR can fix a wrong AI reading; rules are
  re-evaluated on the corrected value and the original is retained in `meta.manual_overrides`
  for audit. The PDF report renders the corrected row (not a re-run of OCR), so what you
  printed is what you saved.
- Evidence Planner: the platform never just reports a verdict — it lists what evidence is
  still needed for a *defensible* decision. Missing mandatory declarations appear as
  `missing_declarations`, low-confidence reads are flagged back to the inspector for
  physical verification, and unmeasurable axes (font size without a calibration reference)
  are excluded rather than guessed. Every flagged item traces to its source rule, field,
  OCR token, image region, and original package image.
- Role-based access control: ADMIN / INSPECTOR / VIEWER, seeded from `backend/.env`;
  admin user management (search users, view their scans, reset passwords — passwords are
  one-way hashed and never recoverable).
- Font readability with honest gating: calibration chain (credit card → barcode → EXIF),
  explicit uncertainty when calibrated, REVIEW_REQUIRED (never a fabricated verdict) when
  uncalibrated. Font size is measured in mm only when a defensible reference exists.

### Next (roadmap)

- **Guided calibration-card capture** in the capture UI — the inspector is prompted when a
  reference object is missing, instead of discovering it in the report.
- **CPU OCR engine upgrade** — bench-verified on hard labels: PP-OCRv6 (`rapidocr` 3.9)
  recovers text PP-OCRv3 misses (e.g. net quantity `5 Fl. Oz. e 150m` on a curved glossy
  can). Roadmap only — swapping the engine is a pipeline change that must pass the same
  0-hit merge gate as any other change before it ships. Extraction quality on blurry or
  curved labels is an honest model-budget limit of the current CPU path.
- **Per-field numeral-height rendering** on the PDF report and compliance radar, sourced
  from the calibrated measurement axis.
- **Quantitative regression set** of synthetic labels with known pixel heights, so every
  font-measurement change is validated against ground truth.
- Tenant / user-level data scoping for the dashboard (stats are global today).
- Postgres swap for the repositories when scaling beyond a single node.

More detail on the font-measurement roadmap lives on the in-app page
[`/font-measurement`](frontend/app/font-measurement/page.tsx).

## Judge-facing demo walkthrough

The demo is sequenced to show what a weekend team **cannot** replicate, and every paid
demo product below is one of the 70+ real photos that the CPU pipeline extracts reliably
(verified — not assumed):

1. **Audit, not demo-magic** — run `backend/scripts/pipeline_audit.py` in front of the
   panel: the compliance rule engine is checked cell-by-cell against the frozen
   golden-statutory oracle of the 2011 Rules (as amended through 2026) before any merge.
   The panel sees *proof of correctness*, not a screenshot.
2. **Inspect a demo-safe product** — verified on the CPU pipeline across all 72 photos,
   the top extractors are `image1_*`, `image3_*`, `image8_*` (9/9 declarations) and
   `image11_*` (8/9). Complete the 1–3 photo upload flow, watch the declarations extract,
   rules evaluate, and the status + evidence-backed score appear.
3. **Evidence Planner** — open the report and trace a flagged item end-to-end: rule →
   field → OCR token → image region → original photo, plus anything still
   `missing_declarations` or holding at REVIEW_REQUIRED.
4. **QR verification** — open the certificate, scan the QR to the public `/verify` page,
   and show `hash_match: true` for an untouched scan.
5. **Instructor correction** — fix one field, show rules re-evaluate, then download the PDF
   and show it renders the corrected row while the original stays in `manual_overrides`.

Keep the risky or blurry captures (curved glossy cans) out of the live demo — extraction
quality on those is an honest model-budget limit, and the audit + evidence story is where
the submission wins. For reference, the sweep ranked all 29 products: 3 at 9/9, 5 at 8/9,
7 at 7/9, 6 at 6/9, and the bottom quarter at ≤5/9 — demo only the top group.

## Team

SIH 2026 submission — PS 26034. Sourced as a legal-metrology field-assist platform.