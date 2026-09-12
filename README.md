# LegalMatrix (MetrIQ)

**AI-powered Legal Metrology compliance inspection for packaged commodities** — SIH 2026
Problem Statement **PS 26034** (Ministry of Consumer Affairs, Food & Public Distribution,
Department of Consumer Affairs). A field inspector photographs a product label with their
phone; the platform extracts the declarations with a vision-language model, checks them
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
                              │ Ollama       │                    │ SQLite     │  │ evidence/    │
                              │ qwen2.5vl:7b │  (VLM, one central│ legalmatrix│  │ dir (photos, │
                              │ GPU server   │   server)         │ .db        │  │ sha-256)     │
                              └──────────────┘                    └────────────┘  └──────────────┘
```

Key design decision: the LLM runs **once, centrally** on a GPU server (via Ollama). Users only
need a browser/PWA — no model download or mobile compute on the device.

## Stack

- **Backend** — FastAPI (Python 3.12+), SQLite (stdlib), OpenCV (barcode + font measurement),
  fpdf2 (PDF reports). No ORM, no heavy frameworks.
- **Vision model** — Qwen2.5-VL (7B) via Ollama; fits a single 8 GB GPU, strong
  at reading natural-scene label text and returning structured JSON plus
  localization boxes.
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
  app/                             # pages: / (inspect), /dashboard, /history, /inspection/[id], /login
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
| VLM text extraction of 9 declarations | `backend/app/services/ocr_service.py` |
| Mandatory declaration checks (7 fields) | `core/rule_engine.py` |
| MRP / USP math, net quantity parsing | `services/price_engine.py` |
| Font size & readability measurement | `services/font_measurement.py` (barcode-calibrated PPM, cap-height via VLM boxes, honesty gating) |
| Misleading-declaration heuristics | `services/inspection_service.py` |
| PDF report with embedded evidence photos | `POST /api/inspect/report` |
| Editable exports (JSON / CSV) | `GET /api/inspect/{id}/export` |
| Evidence photo attachment + SHA-256 hashing | `services/inspection_service.py`, `/api/inspect/{id}/evidence/{i}` |
| Report repository / inspection history | `repositories/inspections.py` |
| Role-based auth (ADMIN/INSPECTOR/VIEWER) | `api/auth.py`, `services/auth_service.py` |
| Dashboard (stats, trends, recent) | `GET /api/dashboard/stats` |
| Search (id, product, manufacturer, dates, status) | `GET /api/search` |
| Technical documentation | this file + `backend/tests/` |

## Quickstart (development)

Prerequisites: Python 3.12+, Node 20+, and [Ollama](https://ollama.com) with a vision model.

```bash
# 1. ollama model
ollama pull qwen2.5vl:7b

# 2. backend
python -m venv backend/venv
backend/venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
LEGALMATRIX_DATA_DIR=backend/data backend/venv/bin/uvicorn app.main:app --app-dir backend --port 8000

# 3. frontend
cd frontend && npm install && npm run dev

# 4. open http://localhost:3000 — sign in with admin / admin@123
```

Environment variables (backend): `OLLAMA_HOST` (default `http://localhost:11434`),
`QWN_MODEL` (default `qwen2.5vl:7b`), `LEGALMATRIX_AUTH_SECRET`, `LEGALMATRIX_DATA_DIR`,
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

Three services run as containers (see `docker-compose.yml`): a GPU-backed Ollama server
(NVIDIA runtime), the FastAPI backend, and the Next.js frontend resting behind a
production server. The backend container must be able to reach Ollama
(`OLLAMA_HOST=http://ollama:11434`). SQLite paths and evidence storage are mounted as
volumes; swap the repositories layer for Postgres when scaling beyond a single node.

> **Security note:** change `LEGALMATRIX_AUTH_SECRET` and the seeded default password
> (`admin / admin@123`) before any production deployment.

## Team

SIH 2026 submission — PS 26034. Sourced as a legal-metrology field-assist platform.