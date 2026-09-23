# Claude Brainstorm Prompt — Font-Size Measurement Accuracy

Paste the block below into Claude verbatim, along with the two files it should read:
`backend/app/services/font_measurement.py` and `backend/app/services/ocr_service.py`
(and optionally `backend/app/services/inspection_service.py`).

---

```
You are a senior computer-vision + legal-compliance engineer. We need your critical help, not
praise. Challenge our assumptions and give us the strongest defensible design.

CONTEXT — what we are building
--------------------------------
"LegalMatrix" (SIH 2026, Problem Statement 26034): a field app used by Indian Legal
Metrology inspectors to check packaged goods labels for compliance with the Packaged Commodities
Rules. Flow: inspector photographs a product label with a phone (2-4 photos/product) -> FastAPI
backend -> Qwen2.5-VL 7B via local Ollama extracts structured declarations (mrp, net_quantity,
product_name, manufacturer, manufacturing/expiry date, consumer_care, dimensions, usp) -> a
DETERMINISTIC Python rule engine (data/rules.json) produces compliance verdicts -> a font-size
check measures whether printed MRP/net-quantity numerals meet the legal minimum cap-height
(1.0-2.0 mm depending on net quantity).

HARD RULES for the subsystem:
- Never fabricate a measurement. When calibration fails, the correct answer is "cannot measure,
  manual review" — a verdict we can defend against a judge. A tool that false-accuses a
  manufacturer is unusable.
- Report honest uncertainty, not a single fake-precise number.
- The stack is deliberately lean: FastAPI + OpenCV + Pillow + fpdf2 + httpx. We REMOVED all OCR
  libraries (EasyOCR, PaddleOCR, Tesseract). Single VLM (Qwen) is our only "AI" — cheaper field
  devices, no mobile compute. Do not suggest re-adding OCR or another ML model unless truly
  unavoidable; if you do, state the cost/benefit explicitly.
- Hardware ceiling: RTX 4060 8GB VRAM, 7GB system RAM. Backend pytest suite = 62 green tests.
- Next.js PWA frontend already exists; ignore it for this prompt.

HOW FONT MEASUREMENT WORKS TODAY (backend/app/services/font_measurement.py)
---------------------------------------------------------------------------
1) CALIBRATION (pixel->mm), priority order:
   a. "barcode": OpenCV BarcodeDetector -> barcode pixel width / 20mm nominal EAN-13 module width.
      ±15% uncertainty because EAN-13 magnification varies 0.8-2.0x.
   b. "exif": none/no reference object in frame. 35mm-equivalent focal (EXIF 0xA405 or 0x9205) ->
      horizontal FOV -> ppm = image_width / (2 * D * tan(FOV/2)), D = SubjectDistance (0x920A).
      ±20% uncertainty. GATED: ppm must be in [1.0, 300.0]; real phone SubjectDistance metadata is
      frequently garbage (we measured an effective "camera 11m away" => ppm ~0.28), so this is
      usually rejected.
   c. If neither -> measure() returns None. (15/32 real products currently get no measurement.)
2) MEASUREMENT:
   a. cap_height (preferred): given a VLM "regions" box for MRP/net-qty text
      ([x1,y1,x2,y2], 0-1000 normalized, top-left origin), crop -> bilateral blur -> Otsu
      invert -> morphological OPEN -> connected components -> keep glyph-like strokes ->
      DOMINANT stroke-height cluster (to ignore descenders g/p/q/y). Units: pixels, converted
      via ppm to mm.
   b. heuristic fallback (no VLM box): median height of all text components in the lower half of
      the image, excluding the barcode bbox.
3) VERDICT BANDS: lower = mm - unc, upper = mm + unc.
   if lower >= required -> COMPLIANT; elif upper < required -> POTENTIAL_VIOLATION;
   else REVIEW_REQUIRED.
4) inspection_service.run_inspection tries EVERY image of the product and keeps the first image
   that calibrates. VLM "regions" (when emitted) are plumbed in as text_box.
5) VLM extraction (ocr_service.py) prompt: strict JSON only, no examples, asks for optional
   "regions" in 0-1000 normalized coords. History: concrete EXAMPLES in the prompt made the
   smaller 3B model ECHO the example box verbatim, and required-regions phrasing produced unquoted
   keys that broke JSON parsing. Current prompt has neither — do not reintroduce.

REAL-WORLD VALIDATION (32 products, 78 photos, Qwen 7B at 896px) — the evidence you must trust
------------------------------------------------------------------------------------------------
- 3B model was retired after mass hallucination ("MRP: 100% PURE COFFEE", "15 MINS"), ~12 garbage
  '?????' crash sequences, unparseable output. 7B: zero crashes, realistic MRP strings with
  currency markers ("Rs. 265", "₹ 47.00", "₹150/-") — right semantics for our rule engine.
- BUT font measurements look wrong in places:
    * cap_height returned 0.18 mm and 6.35 mm on different products (both implausible for
      required 1.0 mm). Root suspicion: the VLM box was loose -> caught the product-name logo or
      multiple text lines -> dominant-height cluster is then NOT the MRP digit stroke height.
    * heuristic fallback consistently UNDERestimates: 0.2-0.9 mm (mixes tiny tagline/recyclable
      microprint into the median).
    * Some cap_height readings look plausible (3.49 mm, 1.79 mm, 0.73 mm) but we have NO ground
      truth to confirm any of them.
- So: calibration leg is solid, measurement leg is garbage-in/garbage-out, and there is zero
  quantitative accuracy evidence. This is the weakest link in an otherwise strong pipeline.

PROBLEMS WE NEED SOLVED (ranked)
---------------------------------
1. GROUND TRUTH without physical labels in hand: we plan PIL-synthesized labels rendered at
   KNOWN pixel cap-heights (algorithmic GT) + 10-15 physical labels measured with calipers (legal
   GT, later). Is the synthetic plan sound? How do we render so OpenCV preprocessing (blur, Otsu,
   morphology) still sees realistic noise/skew? Tolerance that is fair but not self-flattering?
2. DETECT a wrong VLM box (points at logo/multiple lines instead of MRP numerals) WITHOUT another
   model call and WITHOUT OCR. A cheap CV "text/digit plausibility" gate: box area < 40% of image,
   aspect ratio 1.5-15, stroke-density/ink ratio vs neighborhood, print-position heuristics
   (MRP usually near barcode or bottom-right). Critique + improve this: we want ~5-10ms per box.
3. ROBUST cap-height features on skewed/noisy/differently-lit photos: minAreaRect skew correction,
   digit-like component filter (0.8-1.2x median stroke height), row-projection profile
   (cap-line minus baseline) instead of raw connected components, ink-area weighting, median over
   multiple rows. Critique the design; what breaks in the real world (perspective skew, curved
   labels on jars, glossy reflections, very thin strokes)?
4. WHEN CALIBRATION FAILS: is a BRACKET/range answer ever better than "cannot measure"? One idea
   (weak, want your view): use MRP/net-qty numeral height RATIO as a relative consistency check,
   not as a source of absolute mm. What is the minimal DEFENSIBLE fallback output?
5. DEVIATION REPORT that would survive a Legal Metrology dispute: we already have SHA-256 evidence
   chain + full raw VLM output stored. Proposed report sections: identification, evidence,
   extraction (raw VLM output + prompt), calibration (method + uncertainty), measurement (method +
   raw pixels), verdict + rule citation, chain-of-custody hash + signature + QR, and an explicit
   "what this report does NOT prove". Critique the list; anything a manufacturer's lawyer would
   attack?
6. GATING POLICY we intend to adopt: return REVIEW_REQUIRED unless (barcode calibration succeeded
   AND VLM box passed sanity AND result is plausible relative to required_mm). Strictly better than
   shipping implausible numbers — confirm or argue.

DELIVERABLE — give us:
A) A critical review of the 6 problems above (say what's wrong, don't just say "good idea").
B) A concrete, ordered implementation plan with the tightest minimal code changes to the two files.
C) A 30-minute smoke-test recipe that runs headless on the existing 78-image dataset and prints a
   before/after table (product, calibration source, cap_height mm, required_mm, verdict, box-sanitized?).
D) The exact JSON schema for the per-inspection font_measurement result block after your changes.
Be skeptical, specific, and economical. We are 3 weeks from an SIH submission and can only afford
changes that measurably improve defensibility.
```

---

## ⚠️ UPDATE 2026-09-13 — YOUR REVIEW WAS IMPLEMENTED (read this before pasting again)

All of the above has been acted on. Do NOT re-litigate it — extend it:

**Implemented in `font_measurement.py` + `inspection_service.py` + `ocr_service.py`:**
- `measure()` returns `CANNOT_MEASURE` + `calibration_rejected_reason`, never `None`. EXIF reasons
  are granular (`exif_tags_missing`, `exif_focal_length_missing`, `exif_implausible(ppm=0.28)`).
- Barcode gated: `>=4` corners + convex-hull test (false positives rejected).
- Box gate: `_box_geometry_ok` (size/area[0.002,0.15]/aspect[1.2-12]) runs BEFORE glyphs, then
  `_box_is_plausible` (>=3 glyphs, stdev/mean<=0.4). Rejected box -> heuristic fallback +
  `box_rejected_reason`. Geometry is checked first so a wrong empty box reports e.g.
  `area_too_large`, not `no_glyphs_found`.
- Implausibility bounds `[0.3, 10.0] x required_mm` -> REVIEW_REQUIRED + `implausible: true`.
- `heuristic_lower_half` is FORCED to REVIEW_REQUIRED (informational) — automated verdicts require
  a clean box + calibration + plausible value.
- Relative cap-height bins (median//10) replacing fixed 2px; morphological open skipped for regions
  <40px tall (a (2,2) open shattered a 10px glyph); double-imread removed.
- Traceability: `image_index`, `image_path`, EXIF `photo_capture_timestamp` (0x9003),
  `extraction_prompt_hash` (SHA-256 of the VLM prompt); result carries `height_px`, `glyph_count`,
  `ppm`, `calibration`, `calibration_bbox`, `method`. Frontend renders CANNOT_MEASURE + implausible.
- Tests: 76 green, incl. synthetic ground-truth cap-height recovery at 14/24/36px (DejaVu/Liberation),
  box-gate unit tests, implausibility + forced-review tests.
- 78-image smoke: 61 CANNOT_MEASURE (uncalibrated), 17 barcode-calibrated -> all REVIEW_REQUIRED
  (heuristic), `image11_2`/`image8_2` readings 0.21/0.26mm flagged implausible.

**What is still genuinely unsolved (your input would help):**
1. New failure to skew/curved labels — cap-height is axis-aligned only; curved-jar labels should
   report REVIEW_REQUIRED. Is a cheap `minAreaRect` rotation test worth it, or just document it?
2. VLM boxes have NOT yet been crop-verified on the 78 real images (was the plan's step 2) and the
   VLM-only bench neither confirms nor denies which of the cap_height outliers the gate now catches.
3. merge_extractions still couples fields across photos (top task in DEEPSEEK_HANDOFF).
4. The synthetic GT covers measurement arithmetic; the barcode-calibration leg still has no
   synthetic test (OpenCV BarcodeDetector won't read PIL-drawn mock barcodes) — physical caliper
   labels remain the plan.
5. Report: `what this report does NOT prove` + device/inspector identity sections still not built.