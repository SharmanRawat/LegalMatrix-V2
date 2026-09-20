# RULES — Legal Metrology (Packaged Commodities) Rules, 2011 as codified

Source of truth in code: `backend/app/data/rules.json`
(`rule_version: LM-PCR-2011-with-2021-USP-amendment-and-all-updates-to-2026`,
effective 2023-04-01). Rule text → `core/rule_engine.py::RULE_DETAILS` +
`evaluate_compliance` + `_check_format`. This file is the human-readable companion.

## 1. Seven required declarations (`declarations_required`)

| # | Rule | Code id | Field | Severity | What passes |
|---|---|---|---|---|---|
| 1 | Rule 6(1)(a) | `manufacturer_name_address` | `manufacturer` | CRITICAL | Name + registered address of manufacturer/importer/marketer on PDP |
| 2 | Rule 6(1)(b) | `generic_commodity_name` | `product_name` | CRITICAL | Common name (`Honey`, `Sunflower Oil`) prominent on PDP |
| 3 | Rule 6(1)(c) | `net_quantity` | `net_quantity` | CRITICAL | Numeric + SI unit (`g/kg/ml/L`, `cm/m` for length); liquids at 20 °C |
| 4 | Rule 6(1)(d) | `month_year_manufacture` | `manufacturing_date` | HIGH | Month + year (`MMM/YYYY`, `MM/YYYY`, `MM/YY`); code checks for a 4-digit year or `MM/YY` pattern |
| 5 | Rule 6(1)(e) | `mrp` | `mrp` | CRITICAL | `MRP Rs.XX / MRP ₹XX`, inclusive of all taxes; must contain digit + (`₹` or `Rs.` or `INR`) unless visually verified |
| 6 | Rule 6(1)(f) | `consumer_care_details` | `consumer_care` | HIGH | Name+address+email and/or phone; pipeline additionally requires a contact channel (`@`, `toll free`, `1800`, 10-digit) or the field counts as missing |
| 7 | Rule 6(1)(g) | `dimensions_where_relevant` | `dimensions` | MEDIUM | Only when product is non-edible sold by dimensions (garments, cables, electronics). `edible=no` → required; else skipped |

Missing → violation `status=MISSING`. Present-but-malformed → `FORMAT_ISSUE`
(severity MEDIUM by default). Score = `passed/7*100` (dimensions counts only when relevant).

## 2. Format checks (`rule_engine._check_format`, `inspection_service._check_misleading`)

- **MRP**: `validate_mrp_format` — needs digit; needs `₹/Rs./INR` unless `currency_verified[mrp]` (second VLM look confirmed a glyph OCR dropped). Failure surfaces both as a rule `FORMAT_ISSUE` and a misleading `mrp_format` HIGH with the raw value attached.
- **Net quantity**: needs digit + unit regex `(g|kg|ml|l|gm|cm|m|ltr|litre)`. Parsed to grams/ml by `_parse_net_quantity_g` for the font lookup.
- **Mfg date**: needs `YYYY` or `MM/YY`; glued dates (`07/04/2606/04/27`) are split pre-classifier.
- **USP**: `validate_usp_format` (digit + unit) + `price_engine.calculate_usp(MRP/net_qty)` cross-check. Printed USP differing >0.05 from computed → `usp_mismatch_computed` MEDIUM. USP identical to MRP → `usp_missing_or_equal_mrp` MEDIUM (USP probably not actually printed; exempt case below excluded).
- **Consumer care**: contact-channel regex gate (see above) — a long disclaimer without email/phone is rejected rather than accepted.

## 3. Font-size requirements (`font_size_requirements`)

Letters (normal/embossed): 1.0 / 2.0 mm minimum.

Numerals for weight/volume (normal / embossed), keyed by net quantity:

| Net qty | Normal | Embossed |
|---|---|---|
| ≤ 200 g/ml | 1.0 mm | 2.0 mm |
| 200–500 g/ml | 2.0 mm | 4.0 mm |
| > 500 g/ml | 4.0 mm | 6.0 mm |

Numerals for length/area/number keyed by PDP area (100/500/2500 cm² → 1/2/4/6 mm).
Measurement: `font_measurement.py` (token-box cap-height preferred) calibrated via
`scale_calibrator.py` chain credit-card → barcode → EXIF; result carries
`measured_mm / required_mm / uncertainty / status`; unmeasurable → honest
`CANNOT_MEASURE`, never a fake pass. Placement free-area rule (height above/below,
2× height left/right) and manner rules (legible/prominent, contrasting colour,
Hindi+English) are documented in `rules.json` but only partially auto-checked —
flag visually for now.

## 4. USP rules (`usp_rules`, G.S.R. 226(E)/60(E), effective 2023-04-01)

Formula `USP = MRP / Net_Quantity`, 2 decimals. Unit mapping: <1 kg → `Rs per g`,
≥1 kg → `Rs per kg`; <1 L → `Rs per ml`, ≥1 L → `Rs per litre`; length <1 m →
`per cm` else `per meter`; count → `per number`. Exemptions: `MRP == USP` (no USP
needed); alcoholic beverages (state excise law applies).

## 5. Exemptions 26(a)–(f) and exclusions

- **26(a)**: net ≤10 g/ml exempt — except 10–20 g/ml still needs MRP + net qty;
  **pan masala carve-out (G.S.R. 881(E), 2026-02-01): exemption does NOT apply**.
- **26(b)**: fast food packed by restaurant/hotel. **26(c)**: scheduled DPCO-1995
  formulations. **26(d)**: agri produce >50 kg. **26(f)** (G.S.R. 648(E)):
  garments/hosiery sold loose at POS still need maker address, origin if imported,
  care email/phone, size (`S/M/L…` + cm/m), MRP incl. taxes.
- **Medical devices** (G.S.R. 778(E)): routed to Medical Devices Rules 2017,
  skip Rules 6/7/33. **E-commerce** country-filter (G.S.R. 312(E)) effective
  2027-07-01 — not enforced yet. QR-for-electronics (2022) expired.

## 6. How to change a rule

1. Edit `backend/app/data/rules.json` (bump `rule_version`).
2. Mirror text/severity in `core/rule_engine.py::RULE_DETAILS` + mapping `_rule_to_field`.
3. Add/adjust `_check_format` + tests in `backend/tests/test_rule_engine.py`.
4. Re-run `pytest -q` and one `pipeline_audit.py` product to confirm scores move as expected.
