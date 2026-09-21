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
| run14-v3fresh | **PP-OCRv3 fresh baseline on NEW host** (no caches; SLM draw differs) | 149 | 62.6% |
| run15-v4mobile | **PP-OCRv4 mobile det+rec swap** (fresh, same new host, GPU SLM) | 151 | 63.4% |
| run16-v3gpu | **PP-OCRv3 CPU + GPU-SLM fresh baseline** (GPU shifts 3B draws → not comparable to run14) | 166 | 69.7% |
| run17-v4srv | **PP-OCRv4 SERVER det+rec swap on GPU** (fresh, same host, GPU SLM) | 169 | 71.0% |
| run18-mrp | **v3 + MRP-only guarded VLM rescue** (fresh, same host, GPU SLM, `VLM_RESCUE_ENABLED=1`) — **measured, NOT adopted** → see §3b-iv | 172 | 72.3% |
| run19-dates2 | **v3 + raw-OCR two-date reconciliation gate** (`_reconcile_date_ordering`, frozen run16 pipe cache — deterministic merge change) → see §3b-v | **171** | **71.8%** |
| run20-repair | **v3 + date-token OCR repair** (`_repair_date_token` in `_collect_token_dates`: NO/N0→NOV in `dd-mon-yyyy`, glued `JUN25AUG26`→2 short dates, 2-digit-year expansion; frozen pipe cache — deterministic merge-only diff) → see §3b-vi | **175** | **73.5%** |

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
- **p2 MRP — awaiting OCR-upgrade decision (CORRECTED):** RapidOCR (PP-OCRv3)
  cannot read the price — the tight slot (x780-1020, y1490-1590, right after
  `'MRP:₹'`) reads `88888`/`81881`/`88838` under ALL 11 enhancement/upscale
  combos tried. **BUT a fresh qwen2.5vl:7b read of the SAME photo returns
  `mrp: '₹ 440.00'`** — the digits ARE on the photo; the limit is the CPU OCR
  stack, not the image, so the earlier 're-photo' advice was wrong. The app's
  built-in rescue (`VLM_RESCUE_ENABLED=1`, threshold 55; p2 confidence 39.4)
  takes p2 to **COMPLIANT 7/7, Grade A, MRP ₹440.00** — but the rescue
  mis-files p2's expiry as `08/2020` (PKD date; golden expiry '') and turns
  manufacturer/care into the full registered-office blob, so the naive rescue
  is NOT golden-clean and needs a date/contact mis-file guard before it can be
  enabled. OCR inventory: rapidocr-onnxruntime 1.2.3 = PP-OCRv3 mobile, 13.1 MB
  total onnx (det 2.4 + rec 11 + cls 0.6), CPU via onnxruntime 1.30.
  **Decision open: PP-OCRv4 drop-in swap (same engine, ~2× rec model) measured
  against 166/238, or guarded VLM rescue, or both.**
- **run15-v4mobile — MEASURED, REJECTED (17 regressions).** Fresh A/B on this
  host: bundled PP-OCRv3 = 149/238, PP-OCRv4 *mobile* det+rec swap = 151/238
  (net +2). Field math: mrp 15→13 (!!), expiry 13→11, product_name 12→12,
  net_quantity 16→18, manufacturer 3→5, mfg_date 11→12, care 16→17, usp 16→16,
  edible 18→18. 70/70 photos have v4 tokens differing from v3, so every cell
  delta is genuinely OCR-driven (not SLM noise). Headline fix hit: p2 MRP
  `₹ 440.00` now read by v4 (`MRP Rs. 440.00`, ok). But 4 MRP regressions:
  p3 `599→1599`, p4 `410→400021`, p10 `47→''`, p14 `230→''` — the most
  legally-required field went NET NEGATIVE. Also: p2 mfg `8/2020→''` (v4 reads
  `82020` glued, breaking the run13 bare-year path), p18 expiry `''→18-07-2026`
  (phantom read), p20 nq `100g→17.10g`, p22 name `MAGGI→Guideline Daily`,
  p5 mfr `SAHRIDAY→SAHRIDAYFOOD`. Fixes worth noting if revisited: p9/10/26
  mfr+name cleanup, p12 care, p15/21 usp, p26 mfg `JUN/2025`, p8/22 care emails.
  Result: **do NOT ship v4-mobile as default**. Next candidates: (a-2) PP-OCRv4
  **server** models (larger, usually more accurate than mobile) re-measured the
  same way; (b) guarded VLM rescue; (c) both.
- **run16/run17 — v4 server measured on GPU, REJECTED (22 regressions).**
  On this host the 3B SLM runs on the RTX 5060 and GPU shifts its draws, so
  every GPU-era run needs its own baseline: run16 = bundled PP-OCRv3 CPU + GPU
  SLM = **166/238**; run17 = PP-OCRv4 **server** det+rec (GPU, ORT CUDA12 +
  cuDNN 9.26) + GPU SLM = **169/238** (net +3). True fixes 25 vs true
  regressions 22 → fails the **0-regression** bar → **REJECTED, scaffolding
  reverted (tree byte-identical to committed v3)**. Headline regressions: p3
  MRP `599.00→92.40`, p4 MRP `410→''`, p29 MRP `85.00→''`, p2 mfg
  `8/2020→''` — the server weights show the SAME date-glue failure as v4
  mobile (`8X2020`), so the bare-year upgrade path (run13) breaks on v4 too.
  Also: server convs on this GPU hit ORT "Fallback mode" (~53k warnings;
  products 7 & 14 took 14.5/12 min vs ~30s normally) — slower AND not more
  accurate on this stack. **CLOSED: keep bundled PP-OCRv3 as the shipped OCR
  (deterministic 166/238 baseline). Remaining open lever = guarded VLM rescue
  (option b), needs the date/contact mis-file guard first.**
- **run18 — MRP-only guarded VLM rescue, MEASURED then NOT ADOPTED (product
  decision).** A single-field escalation was built and tested:
  `vlm_rescuer.guarded_mrp_rescue` fires ONLY when merged MRP is empty or
  sub-rupee, probes photos in declaration-face order, asks the 7B VLM ONLY
  for the printed price (strict `NONE`-when-absent escape), accepts only a
  validated `Rs/₹` amount ≥ ₹1, and writes ONLY the mrp cell. Isolated A/B on
  identical cached extraction: 166/238 → 172/238 (mrp 17→23/28; fixed p2
  ₹440, p6 ₹119, p7 ₹180, p22 ₹35, p23 ₹109, p26 ₹83; 0 cells outside mrp,
  0 regressions). **However: decided NOT to ship any VLM rescue path.** The
  product flow keeps an unreadable statutory field as **NOT DETECTED** and
  the **inspector manually enters the value** after eyeballing the photo
  (manual override API + UI + PDF "NOT DETECTED" cell; `apply_manual_overrides`
  re-scored against the rules). Rationale: no automated re-read of a field
  the OCR stack cannot see (MRP was OCR-lost on p2/p6/p7/p17/p22/p26/p27/p28)
  beats a trained human inspector for legal evidence, and it keeps the demo
  fully offline/CPU. The MRP-rescue code is reverted; shipped OCR stack is
  byte-identical to the run16 baseline. NOTE for anyone re-litigating: the
  raw run16-vs-run18 diff also showed p29 expiry +1 / p23 manufacturer −1,
  both reproduced WITHOUT the rescue (3B GPU draw noise) — always A/B on a
  shared cached extraction to isolate a change from SLM draw variance.

### 3b-v. Raw-OCR two-date reconciliation gate (run19_dates2) — SHIPPED

- **Idea (user):** "identify text written in `//` brackets as a date in
  general; if two such dates are extracted, the earlier one is the
  manufacturing date and the later is the expiry date (expiry is always way
  ahead)." Measured first against the real cached OCR token streams, per the
  golden-audit discipline: only 3 of the 14 failing products actually have
  BOTH dates readable in the raw OCR while the SLM mis-assigns or drops them.
  The other 11 misses are OCR-blindness (the date text never reaches the
  token stream at all — glare/angle/mangled glue like `UN25AU626U13D…`,
  `FEB25HPR26…`) → no assignment gate can recover them; they stay
  NOT DETECTED → inspector manual entry (by design). **(run20 corrected part
  of this: p9's `N0`/`NO`-for-NOV and p26's glued `JUN25AUG26` ARE recoverable
  via merge-level glyph repair — see §3b-vi; the remainder — p4/p14/p16/p17/
  p22/p28 etc. — stay sub-resolution.)**
- **Implementation (`inspection_service.py`):** `_collect_token_dates` walks
  every `result["tokens"]` across all photos and keeps only dates that
  resolve via `parse_date` to a real month and a 2000-2099 year AND qualify
  by carrying a 4-digit year, a date keyword (MFG/PKD/USE BY/BEST BEFORE/EXP/
  …), or a month-name form. Nutrition decimals (`0.71`, `2.68g`), times
  (`10:00am`), batch glues (`0626LC…`) and impossible day/month pairs
  (`85/8`) never qualify. `_reconcile_date_ordering` (wired into
  `merge_extractions` after routing, so it is final for mfg/exp in BOTH the
  API and the audit path) orders the clean pair earlier→mfg/later→exp and
  applies it ONLY to: an inverted pair (mfg > exp — p15 `12/2025`+`01/2025`),
  a mis-filed expiry sitting in mfg with expiry blank (p24
  `mfg 15/05/2026`, raw OCR has `16/02/2026`+`15/05/2026`), or a blank
  expiry next to a matching earlier mfg (p20). Healthy ordered pairs are
  never touched; manual overrides are applied post-merge so inspector values
  win.
- **Measured (frozen run16 pipe cache → deterministic merge-only diff):**
  **166 → 171/238 (71.8%)**, exactly the 5 predicted cells — p15 mfg+exp +2,
  p20 expiry +1, p24 mfg+exp +2 — and NOTHING else moved. Expiry recall
  `12 missing + 2 wrong → 10 missing + 1 wrong`. +11 tests
  (`tests/test_date_reconcile.py`); full suite **224 passed, 2 skipped**.
- **p23 golden flag:** golden answers say mfg `25/12/26` / exp `28/06/26`
  (expiry BEFORE manufacturing — physically impossible; looks like a swapped
  entry). The gate stays silent there (its numeric dates lack 4-digit years/
  keywords under the qualification rules) rather than force-ordering
  evidence — do not treat as a fixable cell until the label photo is
  re-read.

### 3b-vi. Date-token OCR repair (run20_repair) — SHIPPED

- **Idea (measured, same discipline as 3b-v):** some "OCR-blind" date misses
  are really recognizer *month-mangling* or *short-date glue* that already
  sits in the token stream. `_repair_date_token` (called from
  `_collect_token_dates`, so the OCR layer stays byte-identical) fixes,
  deterministically, before date evidence is grouped:
  - `14-N0-2025` / `13-NO-2026` → `14-NOV-2025` / `13-NOV-2026` (0-for-O /
    V-drop in NOV inside a `dd-mon-yyyy` shape — day kept). The fix is
    day-glued anchored (`\d{1,2}[-/.:]N[O0]V?[-/.:]\d{2,4}`) so English
    `No.` abbreviations ("KHASRA NO.66-72…" land-parcel line → p2 false
    `NOV.66` = 2066) can NEVER rewrite — that regression, caught by the
    full-CSV diff, is pinned by `test_number_abbreviation_never_repaired_to_nov`.
  - glued short dates `UN25AU626U13059…` (p26 lid: `JUN25AUG26` run into a
    barcode line) → `JUN/2025 AUG/2026`, via boundary-anchored
    `UN→JUN` / `AU6→AUG` glyph fixes + a `month+2digits+month+2digits` pair
    rewrite into two 4-digit-year groups. `FUN25`-style substrings can't fire
    (anchored).
  - standalone short forms `FEB25` → `FEB/2025` (2-digit year expansion);
    a single short form is one candidate → gate still needs an ordered
    second date to write (p27 `FEB25HPR26` stays silent — the sibling is
    mangled beyond repair).
  - month-name grouping now uses `_MONTH_YEAR_GLUE_RE` (optional leading day
    `14-NOV-2025`, month word, 2-4 digit year) + `_MONTH_BARE_RE`, replacing
    `_SINGLE_MONTH_RE` at the collector with identical qualification
    (real month + 2000-2099 year via `parse_date`).
- **Measured (frozen run16 pipe cache → deterministic merge-only diff):**
  **171 → 175/238 (73.5%)**, exactly the 4 predicted cells — p9 mfg+exp +2
  and p26 mfg+exp +2 — and NOTHING else moved. A full-CSV diff (not just
  golden-present cells) caught the p2 `NOV.66` over-read before shipping.
  +8 tests (`tests/test_date_reconcile.py`); full suite **232 passed,
  2 skipped**.
- **p4 ROI pass — MEASURED then NOT ADOPTED:** a date-zone ROI pass (crop
  right of detected `Manufacture Dat`/`Expiry / Use by` headers, upscale
  3-6×, CLAHE/adaptive-threshold/otsu/sharp variants, re-OCR) was dry-run on
  all 72 images before touching code. CPU-v3 best reads are fragments only —
  p4 mfg `17.`+`11`, exp `16/05.`/`16/05` (year always missing), confidence
  ≤0.73. The recognizer cannot resolve a full date at any practical
  preprocessing, so the ROI pass would write nothing honest. Remaining
  sub-resolution date cells (p4/p14/p16/p17/p22/p28, plus p27's mangled
  `HPR26`) stay NOT DETECTED → inspector manual entry, by design.

## 4. Commands

```bash
# backend dev
python -m venv backend/venv && backend/venv/bin/pip install -r backend/requirements.txt -r backend/requirements-dev.txt
LEGALMATRIX_DATA_DIR=backend/data backend/venv/bin/uvicorn app.main:app --app-dir backend --port 8000
cd backend && venv/bin/python -m pytest -q   # 232 passed, 2 skipped, OCR mocked

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

## 7. Recent shipped changes

- **Raw-OCR two-date reconciliation gate (2026-09-22)**: `merge_extractions`
  now repairs inverted/mis-filed/missing mfg-exp pairs from clean date tokens
  read anywhere in the raw OCR streams (earlier → mfg, later → expiry), with
  strict qualification (real month + 2000-2099 year + 4-digit year / date
  keyword / month-name) so nutrition decimals, times and batch glue never
  qualify. **Golden audit 166 → 171/238, +5 cells (p15/p20/p24), 0
  regressions**; suite 224 passed, 2 skipped. See TASKS.md + MEMORY.md §3b-v.
- **Date-token OCR repair (2026-09-22, run20)**: `_collect_token_dates` now
  runs `_repair_date_token` (merge-level) fixing recognizer month-mangling —
  `NO/N0 → NOV` in `dd-mon-yyyy` (day preserved), glued short dates
  `UN25AU626… → JUN25AUG26 → JUN/2025 AUG/2026`, standalone `FEB25 → FEB/2025`.
  **Golden audit 171 → 175/238, +4 cells (p9/p26), 0 regressions** (full-CSV
  diff; a p2 `KHASRA NO.66` false `NOV.66` = 2066 over-read was caught and
  pinned by test before shipping). p4 date-zone ROI pass measured and NOT
  adopted (CPU-v3 reads fragments only). Suite 232 passed, 2 skipped. See
  MEMORY.md §3b-vi.
- **PDF report redesigned (2026-09-22)**: `_build_pdf` now produces 2 pages for 2
  images (was 4) with richer detail — status chip + meta grid (engine/lang/
  classifier/grade/hash), compliance strip, declarations table with OK / NOT
  DETECTED / OVERRIDDEN chips + evidence snippets + extraction coverage, manual
  override audit trail, violations with severity chips, 2-up photos with per-image
  SHA-256, page-number footer. Bundled **Hind** (Latin+Devanagari, OFL) in
  `backend/app/assets/fonts/`; `_font_for` routes Devanagari strings to it and
  `_sanitize` stopped latin-1-mangling non-Latin text. Extraction pipeline untouched
  (166/238 baseline unaffected); suite 205 passed, 2 skipped.
- **Hindi OCR (2026-09-22)**: `OCR_LANG` is functional in `ocr_engine.py` — `en`
  (default; byte-identical bare `RapidOCR()`), `hi`/`hindi`/`devanagari`
  (Devanagari-only swap), `bilingual`/`both`/`bi` (Chinese PP-OCRv3 main engine +
  Devanagari rec pass over the SAME detection boxes, fused into tokens by iou>0.5
  dedup, appending only new readings). Devanagari recognizer: ONNX
  `tobiichioriguchi/devanagari_PP-OCRv3_mobile_rec_onnx` (9 MB, vendored
  `backend/app/assets/models/`; char dict extracted from its `inference.yml`, 167
  chars incl. देवनागरी digits ०-९). RapidOCR 1.2.3 cannot construct a dict-less
  Devanagari rec, so `_build_deva_recognizer()` builds `TextRecognizer` directly
  with `keys_path`. +8 tests (`tests/test_hindi_ocr.py`): suite **213 passed, 2
  skipped**, default path verified byte-identical. **Live-dataset bilingual scan
  (all 72 `images/*.jpg`): Devanagari tokens found on 10 of 72 real labels** —
  e.g. image15_back `आधकतमाखुदरमूलय` (≈ अधिकतम खुदरा मूल्य / MRP), image4_back
  `भार्तमािनिमत` (≈ भारत में निर्मित / Made in India), image14_front `डाबर`
  (Dabur). Reads are noisy (no shaping/CTC-decode polish) but prove the bilingual
  path genuinely fires on dual-script Indian packs and enriches the English token
  stream; env-gated so the shipped default English path is untouched. Bilingual is
  the recommended demo mode for dual-script labels.
- **Hindi web app UI (2026-09-22)**: client-side i18n in `frontend/app/lib/i18n.tsx`
  — `I18nProvider` (root layout, imported from the server layout) + `useI18n()`
  hook (`t(key, vars)` interpolation + `tStatus` for COMPLIANT / REVIEW_REQUIRED /
  POTENTIAL_VIOLATION), EN/HI dictionaries with English-key fallback, preference in
  `localStorage` (`lm_lang`), `<html lang>` kept in sync; hydration-safe (defaults
  to `en` until mount). Language toggle (हिंदी/EN) in `Navbar`. Translated: capture
  flow, live results (declarations + overrides, radar, heat-map, violations,
  consistency, font measurement, evidence hash, PDF/certificate/New Inspection),
  full report page, dashboard, history, login. `npx tsc --noEmit` green.
