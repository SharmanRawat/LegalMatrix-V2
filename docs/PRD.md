# PRD — LegalMatrix (MetrIQ), SIH PS 26034

> Problem Statement 26034, Ministry of Consumer Affairs, Food & Public Distribution,
> Department of Consumer Affairs (DoCA), Category Software.
> Title: Software System to check compliance of Packaged Commodities under
> Legal Metrology (Packaged Commodities) Rules, 2011 by scanning products, images and labels.

## 1. Problem

Packaged commodities sold via retail / supermarkets / e-commerce must carry mandatory
declarations under the Legal Metrology Act 2009 + Packaged Commodities Rules 2011:
manufacturer/packer/importer name+address, generic commodity name, net quantity,
month+year of manufacture/pack/import, MRP, consumer-care details, dimensions (where
relevant), in a prescribed format/manner.

Manual inspection does not scale (volume × variety). Typical violations: missing
declarations, wrong font size, improper MRP (`265` without `Rs./₹`), missing USP,
wrong units, misleading claims.

## 2. Users

| Persona | Needs |
|---|---|
| Field Inspector (phone/PWA) | Photograph 1–3 label sides, get pass/fail + evidence PDF in seconds, correct a misread field, work on flaky network |
| Enforcement Officer / Admin | Dashboard (inspections, violations, trends), search/retrieve past scans, role management, export JSON/CSV/PDF |
| Viewer (auditor) | Read-only history, evidence photos, certificates |
| Developer / ML engineer | Reproducible extraction pipeline, per-product audit harness, prompt fingerprinting |

Auth roles in code: `ADMIN / INSPECTOR / VIEWER` (`backend/app/api/auth.py`,
`services/auth_service.py`, HMAC token, default seed `admin / admin@123` — change in prod).

## 3. What the system does (scope = this repo)

1. **Scan** — upload/capture 1–3 images (`POST /api/inspect`, max 3; frontend `app/page.tsx`).
2. **Extract** — 10 fields per image, merged across images:
   `mrp, usp, net_quantity, product_name, manufacturer, manufacturing_date,
   expiry_date, consumer_care, dimensions, edible`
   (`services/inspection_service.py::EXPECTED_KEYS`, `merge_extractions`).
3. **Validate** — 7 statutory declarations from `data/rules.json` via
   `core/rule_engine.py::evaluate_compliance` (+ `price_engine` USP math,
   `font_measurement` readability, `inspection_service._check_misleading`).
4. **Report** — status `COMPLIANT / REVIEW_REQUIRED / POTENTIAL_VIOLATION`,
   compliance score, per-rule violations with rule_no + severity + remediation,
   extraction confidence, font measurement, heat-map overlays, radar grade.
5. **Persist + retrieve** — SQLite (`users, inspections, inspection_images`),
   evidence photos SHA-256 hashed, heat-maps on disk, history/search/dashboard
   endpoints, PDF report, JSON/CSV export, compliance certificate, manual-override
   correction (`PATCH /api/inspect/{id}`).
6. **Dashboards** — stats/trends/recent (`GET /api/dashboard/stats`),
   search by id/product/manufacturer/date/status (`GET /api/search`).

Out of scope for SIH demo: e-commerce listing scraper, mobile native app
(PWA instead), multi-node Postgres (repos layer is swappable), Hindi OCR.

## 4. Functional requirements → implementation

| PS requirement | Where it lives | Notes |
|---|---|---|
| Image upload / scanning | `POST /api/inspect`, `POST /api/inspect/report`, `frontend/app/page.tsx` | 1–3 JPEGs, temp files, EXIF transpose |
| Extract + detect mandatory declarations | `services/ocr_engine.py` (RapidOCR + `field_classifier.py` qwen2.5:3b SLM + regex), fallback `services/ocr_service.py` (qwen2.5vl:7b VLM) | Same interface: `extract_structured / verify_currency_symbol / prompt_fingerprint` |
| Correctness / completeness / placement | `merge_extractions` (MRP/USP/net-qty block from one photo; mfg+expiry block; consumer-care contact-channel preference), `compute_missing` | Longest-string-wins is NOT used for price/dates/care (poison cases documented) |
| Missing / non-compliant detection | `rule_engine.evaluate_compliance` → `MISSING` vs `FORMAT_ISSUE` | 7 rules, see `docs/RULES.md` |
| Readability / font size | `services/font_measurement.py` + `scale_calibrator.py` | Barcode-calibrated px/mm, cap-height from OCR token boxes, honesty gating → `CANNOT_MEASURE` instead of lying |
| Compliance report + violation summary | `GET /api/inspect/{id}`, PDF builder in `api/inspections.py::_build_pdf`, `certificate_generator.py`, CSV/JSON export | fpdf2, evidence photos embedded, prompt-hash for chain-of-custody |
| Photo + evidence attachment | `_store_evidence` (SHA-256, dedup by hash), `GET /api/inspect/{id}/evidence/{i}` | Path-traversal safe |
| Repository + history | `repositories/inspections.py`, `GET /api/inspect`, `/history` page | Indexed by date/status/product/manufacturer |
| Role-based auth | `api/auth.py`, `require_roles`, frontend bearer injection `app/lib/api.ts` | Seed admin only if users table empty |
| Dashboard | `api/dashboard.py`, `frontend/app/dashboard/*` | Stats, trends, recent |
| Search | `api/search.py`, `frontend/app/history/*` | id / product / manufacturer / dates / status |
| Tech docs | `README.md`, `docs/`, `backend/tests/` (76 tests, OCR mocked) | This PRD + ARCHITECTURE + RULES + DESIGN + TASKS + MEMORY |

## 5. The 10 extraction fields (current contract)

VLM prompt (`ocr_service._build_prompt`) and SLM classifier output share these keys.
`usp` = unit sale price verbatim (`Rs. 5.89 per g`); empty if not printed.
`edible` = `yes/no/""` (drives dimensions relevance). `dimensions` only required when
`edible=no` (non-edible sold by dimensions). Currency glyph (`₹/Rs./INR`) must be
preserved verbatim — RapidOCR misreads it as `于/¥/天/舌/曰`, normalized in `ocr_engine.py`.

## 6. Acceptance criteria (demo)

- 3 photos of a compliant pack → `COMPLIANT`, score 100, PDF with photos + hashes.
- Pack missing MRP symbol → `FORMAT_ISSUE` on Rule 6(1)(e) + misleading `mrp_format` HIGH.
- Pack missing manufacturer → `POTENTIAL_VIOLATION` (critical missing).
- Small pack (≤10 g/ml, non-pan-masala) → exemption path documented, not a crash.
- Offline-ish: `VLM_RESCUE_ENABLED=0` still runs fully on CPU; `=1` escalates low-confidence scans to 7B VLM.
- `cd backend && pytest -q` → 76 passed.
- Prompt change → `extraction_prompt_hash` changes (evidence chain).

## 7. Current focus (Sep 2026)

Per-product extraction-accuracy loop: feed all images of one product
(e.g. product 6: `image6_1/2/3.jpg`) through
`preprocessing → OCR → SLM classification`, compare field-by-field against the
`qwen2.5vl:7b` oracle, fix preprocessor/regex/SLM prompt, repeat.
Harness: `backend/scripts/pipeline_audit.py` (cached, near-free reruns) +
`regex_audit.py` + `cascade_bench.py`. See `docs/TASKS.md` for the exact loop and
`docs/MEMORY.md` for known failure modes. Product 1–2 images were deleted (poor
quality); use products 3–28, 65–68 from `E:\SIH_installation_files\images`.
