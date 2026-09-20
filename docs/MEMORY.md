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

## 3b. Label-type routing — measured impact (golden sweep, 29 products)

Per-label-type capture/merge (front/back/side/other; `_FIELD_LABEL_TYPES` in
`inspection_service.py`) measured on the DeepSeek golden set. Both runs below use
the SAME frozen per-photo extraction (audit pipe cache) so the delta is pure routing.

| run | config | ok/238 | recall |
|-----|--------|--------|--------|
| run4 | pre-tagging heuristics (old extraction state) | 158 | 66.4% |
| run5 | routed, no gates (fresh extraction state) | 159 | 66.8% |
| run7 | heuristics + date/name hygiene (current state) | 160 | 67.2% |
| run6 | **label-routed + hygiene (current state)** | **165** | **69.3%** |

- **Routing alone: +5 fields (product_name 7→12 = 24.1%→41.4%), zero regressions**
  on byte-identical data. Front-only reads recovered: Premia (p19), PREMIUM FARD
  DATES (p25), Munching (p5), AMRIK SUKHDEV (p7), NESCAFE CLASSIC (p8).
  All other fields measure identical routed vs heuristic.
- **Gates that made routing safe** (run6 vs run5: +6, 159→165):
  - `_date_component`/`_clean_date_pair` (merge-level, applies to unlabeled too):
    MFG/EXP must parse as a date — kills '6 MONTHS', 'Anso Certified Company',
    'Mig. Date:' — and splits classifier-glued ranges `SEP/2025-MAR/2027` → mfg
    `SEP/2025` + exp `MAR/2027` (p8: both dates now ok).
  - `_name_plausible` junk-prefix gate: 'With TULSI…', 'Suggested Carnishing'
    don't beat the side/back name (p15/p22 stay ok — never below run4).
  - `manufacturer` is **not** label-routed: back short-name 'Sito' lost to side
    legal name 'Bhavani Pharmaceuticals'; heuristic longest-wins kept.
  - **`top` face is now a first-class label type** (cap/roof: batch no, use-by,
    MRP/USP on EVEREST-style snack packs). Routing order for declarations is
    back → top → side → other → front; top still ranks last for name/edible (a
    cap is never the PDP). UI card + tagger key 4 + audit filename/manifest all
    accept it. Measured on the frozen cache (run11_top): **165/238, 0 cells
    changed vs run10** — score-neutral on this dataset because no-back packs
    (27/28/29) already fed their cap data through the 'other' fallback, but it
    is the correct model for unseen rectangular products and removes the
    misleading 'other' labeling.
  - Audit caches per-photo extraction (`PIPE_CACHE_PATH`, key path+mtime+size+model),
    so merge/routing re-runs are deterministic + instant; `--no-labels` measures the
    feature against pure heuristics; `--no-extract-cache` when tuning the SLM prompt.
- Known-not-fixed: p25 expiry (`05.10.2026` vs golden `05/08/2027` — classifier
  content read, not merge/routing), p29 dates (implausible-year flow), care phone
  never OCR'd on 6/10/11/17/18/23. Next lever is the classifier prompt, not routing.

### 3b-ii. Prompt + gate hardening sweep (run8/run9/run10)

Two layers pulled after run6; measured on the same golden set:

| run | config | ok/238 | recall |
|-----|--------|--------|--------|
| run6 | label-routed + hygiene (baseline) | 165 | 69.3% |
| run8-gate | + **sep-regex hardening** (frozen run6 cache) | 165 | 69.3% |
| run9 | + **classifier prompt edits** (fresh extraction) | 158 | 66.4% |
| run10 | prompt edits **reverted**, gate kept (frozen cache) | 165 | 69.3% |
| run13-dates | + **fuse date-completeness + bare-year upgrade** (fresh extraction) | 166 | 69.7% |

- **run8-gate (deterministic, KEPT):** `_SEP_DATE_RE` no longer treats a bare
  space as a date separator, bare years restricted to 19xx/20xx, and numeric
  sep-groups must be a plausible dd/mm pair (`_numeric_pair_ok`). This kills the
  `'85 8'` false positive inside `U280656485 8`, so p29's batch code is dropped
  from expiry (garbage → blank; still wrong vs `JAN27`, but no implausible-year
  output). Diff vs run6: exactly 1 cell changed, 0 regressions across 238.
- **run9-prompt (net-negative, REVERTED):** fresh extraction with two prompt
  bullets — (a) batch/lot/EAN codes are never dates, (b) output BOTH care phone
  AND email. The batch-code bullet hit its target (p29 expiry `JAN/2027` — the
  only product-29 improvement) plus p20 expiry and a p2 nq drift flip (+3 total),
  but the reword made the 3B over-drop valid dates (p10 mfg+exp, p25 mfg →
  blank) and threw collateral garbage (p9 mrp `MRP RS.:`, p29 nq `NET WEIGHT`,
  p29 mrp blank): −10. +3/−10 = −7 → 158/238. Rule: keep only if net-positive;
  reverted, byte-identical back to 165/238 (run10). Lesson: one-line semantic
  constraints can shift a 3B's whole field distribution; only merge-level gates
  (deterministic) survived this sweep.
- **Still blocked (OCR-loss, no prompt can help):** p25 expiry — printed
  `05/08/2027` was OCR-destroyed to `051087202` (unrecoverable); care phones on
  6/10/11/17/18/23 are absent from every RapidOCR line (the label phone lines
  never OCR'd at all); p29 mfg `AUG25` never OCR'd on any photo; p4/p8/p22 care
  emails are present but OCR-degraded (`wecarec`, `WECAREQIN.NESTLE.COM`,
  `@IN.NESTLE.COM`).

### 3b-iii. Top label type + extraction care-phone guard (run11/run12)

- **`top` is a first-class label type** (run11_top, frozen cache — see §LABEL
  TYPES): cap/roof face carries batch no + use-by + MRP/USP on no-back packs
  (EVEREST 27/28/29). Declaration routing order back → top → side → other →
  front; top stays last for name/edible. UI card, tagger key 4, API + audit
  resolution all accept it. Measured: **165/238, 0 cells changed** — the
  no-back packs already fed their cap data through the 'other' fallback; the
  value is the correct 6-face taxonomy (rectangular prisms) + killing the
  misleading 'other' tag.
- **Extraction-time care-phone guard fixed** (run12_care): `_merge_classifiers`
  kept a raw `1?\d{10}` contact-channel test that blanked hyphenated phones
  (`91-22-25259915` = 2/2/8 digit runs) at EXTRACTION time, even though the
  routing gate `_care_contact_like` already strips separators. Synchronised to
  `@ | toll free | 1800 | 10-12 digits after \D-strip`. Result: p27
  consumer_care `'' → '91-22-25259915'` (missing → wrong), **exactly 1 cell
  changed, 0 regressions across 238, score still 165/238**. The p27 care email
  (`customercare@everestspices.com`) is on the un-photographed back face, so it
  stays unrecoverable from the current 4 photos.
- **p27 diagnosis (user's 4-image upload):** 5 of 10 cells blank — cap photo
  OCR-mangled the whole MRP/USP/net-wt/use-by block into one glued line
  (`FEB25HPR26 U13059628968.00:1.369`, `MRPR`, `NETWEIGHT`), so only `FEB/25`
  (mfg) survived; care phone was the guard bug above; care email needs the back
  face. Not routing/tagging — an OCR-quality + missing-face problem (see TASKS
  "still to do").

### 3b-iv. Escalated-date upgrade (run13_dates)

- **Product-2 diagnosis (user's re-upload):** report showed MRP Not detected
  (CRITICAL 6(1)(e)), mfg `2020`, net qty `1 kg`, care ok. Golden: mrp `₹ 440.00`,
  mfg `08/2020`, nq `1 kg`. MRP line OCR'd as literally `'MRP:₹'` + `'(incl., of
  all ax)'` — the `440.00` digits never appear in any of the 4 preprocessing
  variant passes (`MRP:R`, `MRP:₹`, `MRP?`, `MRP:`+`888`); escalation confirmed
  running (`escalated: True`). Price is genuinely unrecoverable on that photo —
  needs a crisper MRP close-up, not code.
- **Bare-year date upgrade (deterministic, KEPT):** the invert pass read the mfg
  line as `'8 / 2020'` but two code paths dropped it — (a) `_token_quality` gave a
  bare high-conf `2020` more weight than informative `8 / 2020`, and (b) the
  escalator only filled EMPTY fields, and its SLM re-read on 47 fused lines is
  flaky (`mfg: ''`, hallucinated `mrp: ₹47.00`). Fix: fuse rewards `m/yyyy`
  (+0.35), and the escalator upgrades a bare `19xx/20xx` date deterministically
  from the fused token stream at the same line index the first-pass line_map
  points to (`_date_has_month` validates month 1-12). Result (run13, fresh
  extraction of all 72): p2 mfg `2020 → 8/2020` (wrong → ok), **1 cell changed,
  0 regressions, 166/238**. Other 5 changed cells score-neutral drift (p11 care
  phone found fresh; p12 mfg garbage→blank; p13 mfg case-only; p29 expiry
  blank→bad read; p2 nq `100 g`→`kg` — stale run6 cache vs fresh SLM).
- **p2 MRP pixel-verified unrecoverable:** tight crop (x780-1020, y1490-1590 —
  the slot right after `'MRP:₹'`) read as `88888`/`81883`/`81881`/`88838` under
  ALL 11 enhancement/upscale combos (up3/up6 cubic+lanczos, otsu, clahe,
  contrast-stretch, gamma, morph-open, unsharp+otsu). The price glyphs are
  smudged at pixel level in the photo itself — no preprocessing can recover
  `₹ 440.00`, and injecting the `88888` read as MRP would be actively wrong.
  Re-photo of the MRP line is the only fix; do NOT add an MRP-blob pass (run9
  lesson: loss-prone paths go wrong elsewhere).

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
