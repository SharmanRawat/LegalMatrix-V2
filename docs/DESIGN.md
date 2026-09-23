# DESIGN — UX, API, data

## 1. Pages (Next.js App Router)

| Route | File | What it does |
|---|---|---|
| `/` (Inspect) | `frontend/app/page.tsx` (43 KB, the main workhorse) | 1–3 image picker + camera, inspect → violations, declarations with per-field evidence (`via regex/llm` + quoted OCR text), confidence %, radar (`components/RadarChart.tsx`), heat-maps, font panel, PDF/JSON/CSV download, manual-override editor |
| `/dashboard` | `frontend/app/dashboard/*` | Stats, trends, recent inspections (`GET /api/dashboard/stats`) |
| `/history` | `frontend/app/history/*` | Filterable table + search (`GET /api/search`, `GET /api/inspect?limit=`) |
| `/inspection/[id]` | `frontend/app/inspection/[id]/page.tsx` | Single report: declarations, violations+remediation, misleading checks, evidence photos, certificate link |
| `/login` | `frontend/app/login/*` | Token login, `localStorage lm_token/lm_user` |
| PWA | `public/sw.js`, `manifest.json`, `layout.tsx` | Installable, offline shell |

API client: `frontend/app/lib/api.ts` — axios (600 s timeout for VLM), bearer
injection, `apiError`, `downloadBlob`, `RadarResult/HeatmapInfo` types.
Backend base URL via `API_UPSTREAM` build arg / proxy.

## 2. API contracts (all under `/api`, see `backend/app/api/`)

| Method + path | Auth | Body / query | Returns |
|---|---|---|---|
| `POST /inspect` | optional | multipart `images[1..3]` | Full result (see §3) |
| `POST /inspect/report` | optional | multipart `images[1..3]` | PDF bytes (`LegalMatrix-Report-{id}.pdf`) |
| `GET /inspect?limit=` | ADMIN/INSPECTOR/VIEWER | `limit≤200` | Inspection summaries |
| `GET /inspect/{id}` | optional | — | Stored inspection + images meta + heatmaps + radar |
| `PATCH /inspect/{id}` | ADMIN/INSPECTOR | `{overrides:{field:value}}` | Re-evaluated inspection; originals in `meta.manual_overrides` |
| `GET /inspect/{id}/evidence/{i}` | ADMIN/INSPECTOR/VIEWER | — | JPEG, traversal-safe |
| `GET /inspect/{id}/heatmap/{i}` | optional | — | JPEG overlay |
| `GET /inspect/{id}/certificate` | optional | — | Tamper-evident certificate PDF |
| `GET /inspect/{id}/export?format=json\|csv` | ADMIN/INSPECTOR/VIEWER | — | Editable export |
| `POST /auth/login` | — | `{username,password}` | `{token,user}` |
| `GET /dashboard/stats` | (see `api/dashboard.py`) | — | Counts, score distribution, trends, recent |
| `GET /search` | (see `api/search.py`) | `id/product/manufacturer/dates/status` | Matches |
| `GET /rules`, `/health`, `/` | — | — | Rule version + declarations; health |

Error shape: `{status:"ERROR", message}` (500) or FastAPI `detail` (4xx).

## 3. Inspection result JSON (what the frontend renders)

```
inspection_id (LGM-YYYYMMDD-HHMMSS-XXXXXX), timestamp, method ("rapidocr + qwen2.5:3b"),
images_processed, declarations{10}, missing_declarations[rule_ids], status,
compliance_score, passed_count, total_rules, violations[{rule_id,rule_no,severity,
status,field,extracted_value,description,remediation}], misleading_checks[],
extraction_prompt_hash, compliance_radar{overall,grade,axes[]}, grade,
heatmaps[{filename,image_index,field_boxes}],
evidence{hash,images[{filename,sha256,original_name}]},
field_evidence{field:{source,text,image_index}}, extraction_confidence{overall,
coverage_ratio,fields_present/required,by_field{}}
```

## 4. Database (SQLite, `database/models.py`)

`users(id,username UNIQUE,name,role[ADMIN|INSPECTOR|VIEWER],password_hash,salt,is_active,created_at)` —
HMAC auth (`auth_service.py`), seeded admin iff table empty.

`inspections(id PK TEXT, product_name, manufacturer, status, compliance_score,
passed_count, total_rules, declarations_json, missing_json, violations_json,
misleading_json, meta_json{compliance_radar,grade,heatmaps,
ocr_engine,classifier,field_evidence,extraction_confidence,manual_overrides},
evidence_hash, images_count, model, user_id FK, created_at)` — indexed on
created_at/status/product/manufacturer; `_migrate` adds new columns idempotently.

`inspection_images(id, inspection_id FK CASCADE, filename, original_name, sha256, sort_order)`.

Evidence files: `{sha16}_{order}_evidence.jpg` under `LEGALMATRIX_DATA_DIR/evidence/`
(dedup by content hash); heat-maps under `evidence/heatmaps/{id}_{i}_heatmap.jpg`.
Combined `evidence.hash = sha256(concat per-image sha256)`.

## 5. Visual language

Blue primary (#2563EB), status colours green/amber/red (`COMPLIANT/REVIEW_REQUIRED/
POTENTIAL_VIOLATION` + score bands 80/50), severity chips
CRITICAL/HIGH/MEDIUM/LOW, radar grade A–D, per-field green value vs red
`NOT DETECTED`, grey `[via engine] "quoted OCR text"` provenance line, heat-map
field boxes. PDF mirrors the same sections (report header,
confidence, photos, declarations+provenance, violations+fix, footer
disclaimer + timestamp). Fonts: system/Helvetica in PDF (₹ sanitized to `Rs.`).
