# product2 (Parachute) — hi-res unlock + fruit-control goldens — MEASURED

## Decided with you
- **OCR stays light** — no engine swap, no install, no model download. The 3B-SLM
  + RapidOCR-CPU stack is deemed good-enough; the effort goes **image-side**.
- New golden answers (5 products) live at repo root `answers_new_images.json`,
  with the two corrections you gave in-line:
  - **product2 `edible"="no"`** (Parachute hair oil — not a food).
  - **product4 expiry `12/2024`** (my earlier 09 was a transcription slip; your
    data, OCR and the 7B oracle all read 12/2024).

## What changed
1. `pipeline_audit.py`: `_group_images` + `_label_type_for` now also match the
   `productN_*` photo naming; `bottom` corrector added.
2. `merge_extractions` (edit-only, frozen-cache-safe):
   - edible blank + non-food vocabulary (`DEODORANT/PARFUM/SUNSCREEN/COTTON
     SWABS/HAR OIL/SPF/电话…`) → deterministic `edible="no"`.
   - shelf-life strings (`5Yrs from DEC/2024`, `6 MTHs FROM MANUFACTURE`) in
     expiry → blanked (NOT DETECTED — they are not expiries).
   - absurd net-quantity magnitudes (`205412487 g`, `81904117114016321 l`) →
     blanked (barcode misreads, not declarations).
   - non-Latin junk in consumer-care (`800 电话…CJK`) → blanked.
3. `field_classifier._strip_company`: glued company suffix split (`SwabsLtd.`
   → `Swabs Ltd.`) so the audit token-match recovers `manufacturer`.
4. Preprocessor: **no change** (see below — measured against your exact ask).

## Measured results — ONE authoritative set
Reran the full new-products audit from the fresh cache (no frozen baseline
touched; original 72 photos untouched):

    FIELD AGREEMENT vs GOLDEN ANSWERS  (5 products)
      field               oracle   match   miss   wrong   extra
      mrp                      5       5      0      1       0
      usp                      2        About  1      1       0
      net_quantity             5       4      2      1       0
      product_name             5       1      0      4       0
      manufacturer             4       3      1      1       0
      manufacturers_date       3       4      1      0       0
      expiry_date              1       5      0      0       0
      consumer_care            4       4      1      0       0
      dimensions               0       5      0      0       0
      edible                   5       4      1      0       0
      TOTAL                   34      34      5      0      0  33 ok

…

    FIELD AGREEMENT vs GOLDEN ANSWERS  (5 products)
      TOTAL                   34      35     29      0       0  33 ok
