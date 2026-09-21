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
- **DONE (this session): OCR upgrade decision CLOSED — keep bundled PP-OCRv3.**
  Both PP-OCRv4 variants were measured on the golden set and REJECTED:
  run15-v4mobile (151/238, 17 broken cells → §3b-ii) and run17-v4server on
  GPU (169/238 vs run16 v3 baseline 166/238, but 22 true regressions → fails
  the 0-regression bar; server also hits ORT fallback-mode on this GPU and
  shows the same date-glue failure `8X2020` breaking p2 mfg). v4 scaffolding
  reverted; tree byte-identical to committed v3. Baseline to beat if ever
  revisited: **166/238 (run16: v3+GPU SLM)**; GPU-era runs need their own
  baseline (GPU shifts 3B draws).
- **DONE (this session): MRP-ONLY guarded VLM rescue SHIPPED (run18, +6, 0
  regressions) — the date/contact mis-file guard, scoped to a single field.**
  `VLM_RESCUE_ENABLED=1` now fills empty/sub-rupee MRP from the 7B VLM
  (validated `Rs/₹` amount ≥ ₹1, `NONE`-when-absent, declaration-face photo
  probing, writes ONLY mrp — dates/care/manufacturer never touched; runtime +
  audit share the same `vlm_rescuer.guarded_mrp_rescue`). Measured 172/238
  (mrp 17→23/28) with 0 regressions on an isolated cached-extraction A/B.
  Default (flag off) is byte-identical to the 166/238 baseline.
- Remaining MRP gaps (optional next): p5/p16/p25 are wrong-but-plausible
  values the guard deliberately leaves alone (touching believable prices
  risks ok→wrong regressions — would need a golden-validated
  wrong-vs-right discriminator); p17/p27/p28 are 7B read-misses
  (230/68/50 vs golden 210/83/85). p2's mfg date-glue tail and the
  OCR-loss date cells (p25 expiry) remain OCR-bound, not prompt-fixable.
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
| B | Report/export UX | `backend/app/api/inspections.py::_build_pdf`, `services/certificate_generator.py`, frontend download buttons | Logo + header, QR to verify URL, Hindi font note (₹→Rs. is intentional in PDF), CSV column freeze |
| C | Auth + roles UX | `api/auth.py`, `login/`, `lib/api.ts` | Hide override buttons for VIEWER, redirect on 401, change-password screen, document seed creds rotation |
| D | Evidence integrity | `services/inspection_service._store_evidence`, evidence endpoints | Verify-hash display, tamper demo, storage-quota note |
| E | DevOps/docs | `docker-compose.yml`, Dockerfiles, `docs/` | `docker compose up --build` green on a clean machine; record GPU/CPU timings in MEMORY.md |
| F | QA dataset | `images/` (local), `/tmp/pipeline_audit` outputs | Build a `samples-private/` manifest: product → images → oracle JSON (never commit photos) |

Branch convention: `feat/<stream>-<short>` from `main`, PR with screenshot + `pytest -q`
output. Never commit `images/`, `backend/data/`, `venv/`, `node_modules/`, `.env`,
or any token (see MEMORY.md security note).

## 4. Backlog (after extraction is green)

- [ ] E-commerce listing URL input (needs new extractor, rules 2027 country filter).
- [ ] Hindi/Devanagari OCR evaluation (`OCR_LANG`, manner Rules language check).
- [ ] Placement free-area auto-check from boxes (rules.json has the spec).
- [ ] Postgres swap behind `repositories/` for multi-node.
- [ ] PWA offline queue (store photo, sync when online).
- [ ] Admin user-management UI.

## 5. Definition of done per task

Code + test (`backend/tests/` or manual UI steps) + docs line update + no secrets/
photos/binaries in diff (`git status --short`, `git diff --stat` clean of `venv`,
`node_modules`, `data/`, `images/`).
