# TASKS — where we are, what is next, how to parallelise

> **PROJECT BACKGROUND (read before anything else):**
> LegalMatrix (MetrIQ) — SIH 2026 Problem Statement **PS 26034** (Ministry of
> Consumer Affairs, Dept. of Consumer Affairs): a field inspector photographs a
> packaged-food label with a phone; the platform extracts the statutory
> declarations (MRP, USP, net qty, name, manufacturer, mfg/exp dates, consumer
> care, dimensions, edibility), checks them against the **Legal Metrology
> (Packaged Commodities) Rules, 2011** (as amended), measures font readability,
> and produces an evidence-backed compliance report. Full context:
> `README.md` (problem statement + architecture), `docs/PRD.md` (requirements),
> `docs/ARCHITECTURE.md`, `docs/DESIGN.md`, `docs/MEMORY.md` §1 (why the
> pipeline is shaped this way), `docs/RULES.md`. The golden-accuracy program
> (measured vs `data/answers_golden.json` via `scripts/pipeline_audit.py`)
> exists because the compliance reports the demo produces are only as good as
> the 10 extracted fields per product.

## 1. Done (in this commit)

- [x] FastAPI backend + Next.js PWA + Ollama compose; seeded admin; HMAC roles.
- [x] Fast CPU pipeline (RapidOCR + qwen2.5:3b SLM + regex) with VLM fallback/rescue
      (`ocr_engine.py`, `field_classifier.py`, `vlm_rescuer.py`, `preprocessing.py`).
- [x] Merge logic that survives real labels (price block, date block, care contact-gate).
- [x] 7-rule engine + USP math + font measurement with honesty gating + radar + heat-maps.
- [x] PDF/JSON/CSV/certificate exports, evidence hashing, history/dashboard/search,
      manual overrides with audit log.
- [x] 76 pytest tests (OCR mocked) + product-6 regression test.
- [x] Audit tooling: `scripts/pipeline_audit.py` (oracle diff, cached),
      `regex_audit.py`, `cascade_bench.py`.
- [x] Typed oracle audit: per-component comparison with notes + disagreement
      triage (pipeline_wrong / oracle_wrong / ambiguous) in `pipeline_audit.py`.
- [x] Canonical normalizers `app/services/value_normalizers.py` — legal
      equivalence (₹=Rs=INR, JAN 2028=01/2028, Ltd=Limited, grams=g) defined in
      ONE place, used by the audit, unit-tested (`tests/test_value_normalizers.py`).
      Adoption candidates: `compliance_scorer` currency check, `price_engine`
      USP unit, `inspection_service._verify_mrp_currency`.
- [x] Cleaned dead experiments (`training/`, `update1/`, `update2*.zip`, florence/qwen
      scratch tests) — deleted in this commit. `images/` stays local-only (gitignored).
- [x] PDF report redesigned (this session, `inspections.py::_build_pdf`): 4 pages for
      2 images → **2 pages**, with *more* detail: status-chip header, meta grid
      (inspection id, date, method, OCR engine + lang, classifier, evidence SHA-256,
      grade), compliance strip (score / rules passed / extraction confidence),
      declarations **table** with OK / NOT DETECTED / OVERRIDDEN chips + per-field
      evidence snippets + extraction coverage, manual-override **audit trail**,
      font-measurement line, rule-violations with severity chips + extracted values,
      2-up photos with per-image SHA-256 hashes, page-number footer. Bundled **Hind**
      (Latin+Devanagari, OFL) so Hindi field values render correctly in the PDF
      (`backend/app/assets/fonts/` + `_font_for` script routing; `_sanitize` no longer
      latin-1-mangles non-Latin). PDF e2e test green; full suite 205 passed, 2 skipped.
- [x] Hindi OCR wired end-to-end (`OCR_LANG` in `ocr_engine.py`): `en` default is
      byte-identical bare RapidOCR; `hi` swaps to a Devanagari-only recognizer;
      `bilingual` runs the Chinese PP-OCRv3 main engine + a Devanagari rec pass over
      the SAME detection boxes, fused into tokens by iou>0.5 dedup (appends only new
      readings). Devanagari model + char dict vendored in
      `backend/app/assets/models/`. +8 tests (`tests/test_hindi_ocr.py`); full suite
      **213 passed, 2 skipped**. **Live-dataset bilingual scan: Devanagari tokens
      found on 10 of 72 real labels** (e.g. `आधकतमाखुदरमूलय` ≈ MRP, `भार्तमािनिमत` ≈
      Made in India, `डाबर` = Dabur) — noisy but real bilingual value for dual-script
      packs; recommended demo mode is bilingual.
- [x] Hindi web-app UI: client-side i18n provider + hook (`frontend/app/lib/i18n.tsx`,
      EN/HI dictionaries, `localStorage` persistence, hydration-safe), language toggle
      in `Navbar`, and translated capture flow / live results / report / dashboard /
      history / login. `npx tsc --noEmit` green.

## 2. Active ML loop (owner: ML pipeline, do NOT parallelise internally)

Goal: 10/10 fields correct per product, measured against the 7B oracle — not vibes.

```
# WSL: images live at /mnt/e/SIH_installation_files/images
cd backend
python scripts/pipeline_audit.py --images-dir /mnt/e/SIH_installation_files/images \
  --product 6 --oracle qwen2.5vl:7b --classifier qwen2.5:3b --out-dir /tmp/pipeline_audit
# read per-product diffs + per-field agreement + JSON/CSV in /tmp/pipeline_audit
# fix ONE thing (preprocessor variant? regex? SLM prompt in field_classifier.py?
#  merge rule in inspection_service.py?) then re-run (cached → near-free)
# next product only when 6 is green; keep products 1-2 skipped (deleted, poor quality)
```

Order: 6 → 8 → 10 → 14/15/18/20 (3-image products stress merge logic) → pairs →
65–68 (latest). Log each product: field agreement % + what fixed it (see MEMORY.md).
`--product` runs one product; omit for full sweep before a release.

Efficiency notes (read before "optimising"):
- Do NOT run images one-by-one through the UI for tuning — the audit script batches,
  caches OCR+oracle by mtime, and prints diffs. UI clicks are ~10× slower.
- Do NOT re-pull/re-run the 7B oracle per tweak — it is cached; only classifier+merge re-execute.
- Do NOT enable `OCR_PANE_ZOOM_ENABLED=1` globally (helps ~1/7 products, expensive).
  Same for `VLM_RESCUE_ENABLED=1` — measure the CPU+SLM path first (`=0`), escalate only.
- The 7B VLM is the oracle, not the runtime: shipping "just call 7B for everything"
  kills offline/CPU demo + latency + GPU cost. Keep `rapidocr + 3b` as default path.

### Label-type routed capture & merge (Front/Back/Side/Other) — DONE & MEASURED

Every dataset product has ≥2 photos, so per-photo label-type routing (front=PDP,
back=declarations, side, other) is applicable everywhere. Expected wins: product_name
(only read the front photo — the worst field), manufacturer (back-only), MRP/USP/
net-qty (back block), mfg/exp swaps (photo-authoritative date routing), consumer_care
(restrict care union to back/side — also kills date-line false phones). Pure-OCR gaps
(care phones never read on any photo, e.g. products 6/10/11/17/18/23) are NOT fixed
by tagging.

Shipped (this session):
- All 72 dataset photos tagged: `backend/data/label_types.json` (gitignored, built as
  filename-embedded + manual overrides; 29 front / 25 back / 11 side / 5 top / 2 other;
  every product has a front photo, products 13/27/28/29 have no back → top/side/other
  fallback). Tagging UI: `backend/scripts/label_tagger.py` (:8765, keys 1-5, auto-advance;
  `_top`/`_Top` filenames are first-class `top` types).
- `merge_extractions(results, label_types)` in `inspection_service.py` — per-field
  routing (`_FIELD_LABEL_TYPES`: front→name/edible; back→declarations; top→declaration
  back-up right below back; side/other as further back-ups), block coherence kept
  (stats & dates travel together, care contact-gated), unlabeled uploads fall back to
  the original heuristics byte-for-byte.
- API: `/inspect` & `/inspect/report` accept `label_types` (repeated form field,
  aligned with `images`; 400 on length mismatch; any of front/back/side/top/other).
  Image cap raised 3 → 6.
  `run_inspection(..., label_types=...)` forwards into both merge call sites.
- Frontend: `page.tsx` upload refactored into per-label-type cards (Front/Back/Side/
  Top/Other), each with camera + upload; FormData sends images + aligned label_types;
  same-product confirmation still gating analyze.
- Audit: `pipeline_audit.py` resolves each photo's label type (manifest + filename,
  case-insensitive, `_top` → `top`) and labels the pipeline merge only; `_group_images`
  now accepts label-named files.
- Tests: +13 routing (`tests/test_label_routing.py`), +2 API label_types e2e
  (`test_inspection_api.py`), max-image test updated. Full suite 184 passed.

Measured (run5, full 29-product golden sweep): total recall 66.4% → 66.8%.
product_name 24.1% → 34.5% (front-only read won 5 garbage names); mrp +1;
net_quantity −1 & expiry −2 (routing regressions). Tuning (run6, this session):
- Date gate + range split (`_date_component`/`_clean_date_pair`): MFG/EXP cells
  must read as real dates — '6 MONTHS', 'Anso Certified Company', 'Mig. Date:'
  are dropped (heuristic AND routing); classifier-glued ranges
  ('SEP/2025-MAR/2027') split into mfg-first/exp-last. Fixes p13/p7/p8 classes.
- Junk-name gate (`_name_plausible`): front promo/boilerplate lines ('With
  TULSI…', 'Suggested Carnishing', 'CONTENTS…', 'Newltem', 'Fewmmended…') don't
  beat the side/back name. Fixes p15/p22 (falls back, never below run4).
- manufacturer removed from label routing (back short-name 'Sito' was beating
  the side legal name 'Bhavani Pharmaceuticals'); heuristic longest-wins stays.
- Audit per-photo extraction cache (`pipeline_audit_pipe_cache.json`, keyed by
  path+mtime+size+model): re-runs of merge/routing are deterministic and near-free;
  `--no-extract-cache` when tuning the SLM prompt, `--no-labels` to measure the
  routing against the pure heuristics on frozen per-photo data.
- **`top` label type** added end-to-end (UI card, tagger key 4, API accepts it,
  audit filename/manifest): cap/roof faces carry batch no + use-by + MRP/USP on
  no-back packs (EVEREST 27/28/29). Routed back → top → side → other → front for
  declarations; top stays last for name/edible. Measured on the frozen cache
  (run11_top): 165/238, **0 cells changed** — neutral here (no-back packs already
  used their cap via the 'other' fallback) but it's the correct taxonomy for
  rectangular 6-face products and kills the misleading 'other' tag.
- Tests: +10 (date gate, range split, name gate, manufacturer heuristic).
  Full suite 194 passed.

Next sweep (this session, run8/run9/run10 — prompt + gate hardening):
- run8-gate (frozen cache, deterministic): `_SEP_DATE_RE` separator must be real
  punctuation (bare space was matching as a date — '85 8' inside `U280656485 8`),
  bare years 19xx/20xx only, numeric sep-groups must pass day/month plausibility
  (`_numeric_pair_ok`). Result: p29 expiry garbage→blank, exactly 1 cell changed,
  0 regressions across 238. KEPT.
- run9-prompt (fresh extraction): classifier prompt tried (a) batch/lot/EAN codes
  never dates, (b) both care phone+email. Net-negative: +3 wins (p29 expiry
  `JAN/2027` — the bullet hit its target — p20 expiry, p2 nq drift) vs −10 losses
  (p10 mfg+exp and p25 mfg dropped to blank, p9 mrp `MRP RS.:`, p29 nq `NET
  WEIGHT`, p29 mrp blank, 3 name/format flips) = 158/238. REVERTED; run10
  byte-identical 165/238. Doors: keep only deterministic gates, treat 3B prompt
  edits as loss-prone.
- Suite: 197 passed, 2 skipped (gate tests kept, prompt-content tests removed).
- Top-type sweep (this turn): `top` first-class label type shipped end-to-end
  (UI card, tagger key 4, API + audit resolution, routing back→top→side→other→front
  for declarations). Measured on the frozen cache (run11_top): 165/238, 0 cells
  changed — ships as the correct 6-face taxonomy, score-neutral on the existing
  dataset.
- Care-phone extraction guard (this turn, run12_care): `_merge_classifiers`
  blanked hyphenated phones (`91-22-25259915` — 2/2/8 digit runs) because its
  contact-channel test was the old raw `1?\d{10}`; synced to the digit-strip
  rule `_care_contact_like` already uses at routing. Re-extracted only product 27
  (4 cached keys dropped, ~40s): p27 care `'' → '91-22-25259915'`, 1 cell
  changed, 0 regressions, 165/238. p27's care email prints on the un-photographed
  back face → still unrecoverable from the current photos.
- Tests: +2 (care-phone merge guard). Full suite 203 passed, 2 skipped.

- Date-upgrade sweep (this turn, run13_dates, fresh extraction of all 72):
  product 2's back photo OCR'd the mfg line as only `2020` while an algorithm
  pass read `8 / 2020` (golden `08/2020`). Two code paths dropped the better
  read: `_token_quality` scored the bare high-conf year above the informative
  month+year, and the multi-pass escalator only fills EMPTY fields (refused to
  upgrade a present-but-degenerate date; its SLM re-read on fused lines is flaky
  anyway — returned `mfg: ''`, hallucinated `mrp: ₹47.00`). Fix (deterministic):
  fuse now rewards `m/yyyy` reads (+0.35), and the escalator upgrades a bare-year
  date from the fused token stream at the SAME line index the first pass used
  (verified plausible month 1-12 via `_date_has_month`). Result: p2 mfg
  `2020 → 8/2020` (wrong → ok), **1 cell changed, 0 regressions, 166/238**.
  Other 5 changed cells are score-neutral drift (p11 care phone found fresh,
  p12 mfg garbage→blank, p13 mfg case-only, p29 expiry blank→bad read).
- Tests: +2 (`_date_has_month`, fuse `_token_quality` date bonus). Full suite
  205 passed, 2 skipped.

Still to do:
- **DONE (this session, run19_dates2): Raw-OCR two-date reconciliation gate
  (`_reconcile_date_ordering` in `inspection_service.py`, wired into
  `merge_extractions` after routing).** The idealisation behind the user's
  'two dates → earlier is mfg, later is expiry' idea was measured first on the
  real cached OCR token streams: only 3 products have BOTH dates readable in
  the raw OCR while the SLM mis-assigns them. The gate scans the raw tokens
  across all photos (`_collect_token_dates`), keeps only dates that resolve to
  a real month + 2000-2099 year AND carry a 4-digit year or a date keyword
  (MFG/PKD/USE BY/BEST BEFORE/EXP) or are month-name forms, then orders the
  clean pair (earlier→mfg, later→exp) and applies it ONLY to: an inverted pair
  (mfg>exp), a mis-filed expiry sitting in mfg with expiry blank (p24), or a
  blank expiry next to a matching earlier mfg (p20). Healthy ordered pairs are
  never touched; nutrition decimals / times / batch glues (`0626LC…`,
  `10:00am`, `0.71`, `85/8`) never qualify. Golden audit (run19_dates2):
  **166 → 171/238, exactly the 5 predicted cells (p15 +2, p20 +1, p24 +2),
  0 regressions**; expiry recall 12M→10M+1W. +11 tests
  (`tests/test_date_reconcile.py`); suite now 224 passed, 2 skipped. The
  remaining expiry misses (p4/9/14/16/17/22/26/27/28) were assessed as
  OCR-blindness at the time — run20 (below) recovered p9 and p26 from the
  token stream after all; the rest (p4/14/16/17/22/27/28) remain
  sub-resolution → NOT DETECTED → inspector manual entry. p23's golden row is
  physically impossible (exp 28/06/26 BEFORE mfg 25/12/26) — flagged suspect,
  the gate rightly stays silent rather than force-ordering it.
- **DONE (this session, run20_repair): Date-token OCR repair.** The
  full-CSV-diff discipline used for run19 was extended to golden-*blank* cells
  (an over-read is as much a regression as a miss). `_collect_token_dates` now
  runs `_repair_date_token` (merge-level — the OCR layer stays
  byte-identical): `NO/N0 → NOV` inside `dd-mon-yyyy` (p9 `14-N0-2025` /
  `13-NO-2026` → recovered, day preserved; anchored to the day-glue so
  "KHASRA NO.66" can't become `NOV.66`=2066 — a false over-read the diff
  caught on p2 and is pinned by a test), glued short dates `UN25AU626… →
  JUN25AUG26 → JUN/2025 AUG/2026` (p26 lid; boundary-anchored so `FUN25`
  can't fire), and standalone 2-digit years `FEB25 → FEB/2025` (p27 stays
  silent — one mangled sibling, no ordered pair). Golden audit
  (run20_repair, frozen pipe cache): **171 → 175/238, exactly the 4 predicted
  cells (p9 +2, p26 +2), 0 regressions**; room-level diff is exactly those
  4 rows. Suite now **232 passed, 2 skipped**. The p4 date-zone ROI pass was
  built and dry-run on all 72 images — CPU-v3 reads are fragments only
  (`17.`/`11`, `16/05.`), full dates (`17/11/2025`, `16/05/2027`) never
  resolve at any sensible preprocessing → **ROI pass NOT adopted**; p4's
  dates stay NOT DETECTED → inspector entry, per honesty-over-accuracy. See
  MEMORY.md §3b-vi.
- **DONE (this session, run21_clean): Corrupt single-digit-year reject +
  golden sanity check.** Scanned every date field in the frozen pipe cache —
  exactly one corrupt value exists (`image7_back` mfg `14.04.0`, from p7's
  `14.04.24` label; pre-verified the primary raw read is `14.04.22`, so the
  true year is unrecoverable by any deterministic rule). New merge-level gate
  `_corrupt_single_digit_year` blanks a date whose trailing numeric token is
  a single digit inside a punctuation-joined date ("unreadable, not partial")
  — parse_date's 2-digit fallback would otherwise emit a fake `14/04/2020`.
  Real 2/4-digit years, month-name/month-year, year-only partials
  (`2026` — kept, they're honest partials), shelf-life (`6 MONTHS`) and
  batch/nutrition lines all provably untouched (tested). Audit tool also now
  warns (warn-only, never fixes) on impossible golden pairs at `--answers`
  load: p23's `exp 28/06/26 < mfg 25/12/26` surfaces every run as a suspected
  entry swap. Golden audit (frozen pipe cache): **175/238 unchanged, 0
  regressions**; p7 mfg flips WRONG→NOT DETECTED (manual entry, by design).
  Suite now **237 passed, 2 skipped**. Per Claude-consult conclusions: only
  7's corrupt emission was deterministically fixable; the other wrongs are
  honest partials (`2026` year-only) or noise (`05.10.2026`, `JAN/2027`) and
  were left alone; p1 `Pkd.10/08/26` is a real printed read mis-filed into
  mfg (golden blank) — kept, NOT a hallucination to suppress. See MEMORY.md
  §3b-vii.
- **DONE (this session, run23_upscale): whole-image 2× upscale + sharpen —
  MEASURED AND REJECTED.** To settle Claude's final suggestion, ran a
  full-field A/B: `pp2x` (`OCR_UPSCALE2X_SHARPEN=1`, fresh 2× OCR + fresh
  SLM) vs `pp2ctrl` (`=0`, fresh native OCR + fresh SLM), both on the run22
  fixed code, all 72 images / 290 rows. **Result: pp2x 154/238 vs pp2ctrl
  168/238 vs frozen baseline 175/238.** A/B shows 27 regressions vs 27
  recoveries (net −14); the sub-resolution date cells did NOT recover (p4
  exp→garbage `410.00`, p16/p22/p28 dates unchanged-or-missing, p27 exp
  `APR/2026` wrong vs golden) and previously-good dates were LOST (p10 mfg
  `07/04/26`→blank, p10 exp `06/04/27`→`07/04/26`, p25 exp→blank, p14/p18
  year-only partials→blank). The 0-regression bar is unreachable. **Scaffolding
  reverted, tree byte-identical to `f024d4f`;** see MEMORY.md §3b-ix.
- **DONE (this session, run22_crashfix): None-component date guard.**
  `parse_date` returns `(None, month)`/`(year, None)` for values like `JAN`,
  `SEP`, `2026` — non-empty (truthy) tuples, so the `if pm and pe` guard in
  `_reconcile_date_ordering` let a deep `pm > pe` comparison through and
  crashed (`'>' not supported between 'NoneType' and 'int'`) on product 9 of
  the fresh pp2ctrl audit run. The frozen baseline draw had never produced
  that combination — a latent shipped-code crash that only a fresh full run
  surfaced. Inversion repair now requires both cells fully parsed to
  (year, month) via `_full_key`; equality branches already safe; p15-style
  proven inversions still repair. Golden audit (frozen pipe cache):
  **175/238 unchanged, byte-identical CSV, 0 regressions**; +2 tests
  (None-year `JAN`/`12/2027`, None-month `2026`/`06/2026`); suite **239
  passed, 2 skipped**. See MEMORY.md §3b-viii.
- **DONE (this session): OCR upgrade decision CLOSED — keep bundled PP-OCRv3.**
  Both PP-OCRv4 variants were measured on the golden set and REJECTED:
  run15-v4mobile (151/238, 17 broken cells → §3b-ii) and run17-v4server on
  GPU (169/238 vs run16 v3 baseline 166/238, but 22 true regressions → fails
  the 0-regression bar; server also hits ORT fallback-mode on this GPU and
  shows the same date-glue failure `8X2020` breaking p2 mfg). v4 scaffolding
  reverted; tree byte-identical to committed v3. Baseline to beat if ever
  revisited: **166/238 (run16: v3+GPU SLM)**; GPU-era runs need their own
  baseline (GPU shifts 3B draws).
- **CLOSED (this session): NO VLM rescue path — product decision.** An
  MRP-only guarded 7B-VLM rescue was built and measured (run18: 166→172/238,
  6 MRP cells fixed, 0 regressions) but **deliberately NOT adopted**: the
  field-extraction UX keeps unreadable statutory fields as **NOT DETECTED**
  and lets the **inspector enter the value manually** after viewing the photo
  (`apply_manual_overrides` + override UI + PDF "NOT DETECTED" cell) — a
  human check beats an automated re-read for legal evidence, and it keeps the
  demo fully offline/CPU. All rescue scaffolding is reverted; shipped code is
  byte-identical to run16's 166/238 baseline. (Anyone re-litigating must A/B
  on a shared cached extraction — raw run diff shows 3B GPU draw noise on a
  couple of cells.)
- Optional later: prompt-level label hint to the SLM ("this is the BACK label") — not
  needed for routing correctness, only for per-photo extraction focus.
- Diagnose the user's 4-image upload that returned poor results (product + output
  needed) — likely label-type selection and/or OCR-loss; the new top type + correct
  card tagging mitigates the mis-tag path.
- Note: renaming photos orphaned old OCR-cache keys (keyed by path+mtime+size) — the
  first labeled run re-OCRs all 72 (slower once, cached after).

## 3. Parallel workstreams for teammates (start now, no ML dependency)

| # | Stream | Files | First commit-sized task |
|---|---|---|---|
| A | Frontend polish | `frontend/app/page.tsx`, `inspection/[id]/`, `dashboard/`, `history/`, `components/RadarChart.tsx`, `lib/api.ts` | Empty/loading/error states; mobile camera CSS; dashboard charts wired to real `/dashboard/stats`; search filters wired to `/search` |
| B | Report/export UX | `backend/app/api/inspections.py::_build_pdf`, `services/certificate_generator.py`, frontend download buttons | Logo + header, QR to verify URL, certificate generator polish, CSV column freeze. (`_build_pdf` core redesign DONE — see §1.) |
| C | Auth + roles UX | `api/auth.py`, `login/`, `lib/api.ts` | Hide override buttons for VIEWER, redirect on 401, change-password screen, document seed creds rotation |
| D | Evidence integrity | `services/inspection_service._store_evidence`, evidence endpoints | Verify-hash display, tamper demo, storage-quota note |
| E | DevOps/docs | `docker-compose.yml`, Dockerfiles, `docs/` | `docker compose up --build` green on a clean machine; record GPU/CPU timings in MEMORY.md |
| F | QA dataset | `images/` (local), `/tmp/pipeline_audit` outputs | Build a `samples-private/` manifest: product → images → oracle JSON (never commit photos) |

Branch convention: `feat/<stream>-<short>` from `main`, PR with screenshot + `pytest -q`
output. Never commit `images/`, `backend/data/`, `venv/`, `node_modules/`, `.env`,
or any token (see MEMORY.md security note).

## 4. Backlog (after extraction is green)

- [ ] E-commerce listing URL input (needs new extractor, rules 2027 country filter).
- [x] Hindi/Devanagari support: PDF rendering (Hind font) ✓; `OCR_LANG` wiring (en /
      hi / bilingual) ✓; web-app EN/HI toggle ✓ — all shipped this session. Remaining
      questions in MEMORY.md §6 (Hindi accuracy target vs English; shaping/CTC polish
      for the Devanagari rec pass on noisier reads).
- [ ] Placement free-area auto-check from boxes (rules.json has the spec).
- [ ] Postgres swap behind `repositories/` for multi-node.
- [ ] PWA offline queue (store photo, sync when online).
- [ ] Admin user-management UI.

## 5. Definition of done per task

Code + test (`backend/tests/` or manual UI steps) + docs line update + no secrets/
photos/binaries in diff (`git status --short`, `git diff --stat` clean of `venv`,
`node_modules`, `data/`, `images/`).
