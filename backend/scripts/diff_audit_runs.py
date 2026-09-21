#!/usr/bin/env python3
"""Diff two pipeline_audit CSV reports product-by-product, field-by-field.

Usage:
    python scripts/diff_audit_runs.py /tmp/pipeline_audit_run14_baseline_v3 \
                                     /tmp/pipeline_audit_run15_v4

Prints, per product: cells where {pipeline, status} changed between the runs,
plus a summary: which cells v4 fixed vs broke (vs golden), and OCR-token-level
change counts per photo (from the tagged ocr caches) to separate OCR-driven
changes from SLM flakiness.
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

FIELDS = [
    "mrp", "usp", "net_quantity", "product_name", "manufacturer",
    "manufacturing_date", "expiry_date", "consumer_care", "dimensions", "edible",
]


def load_rows(csv_path: Path) -> dict:
    """{(product, field): {pipeline, status, note, triage}} — from the JSON report."""
    json_path = csv_path.with_name("pipeline_vs_oracle.json")
    d = json.loads(json_path.read_text())
    rows = {}
    for r in d["rows"]:
        rows[(str(r["product"]), r["field"])] = {
            "pipeline": r.get("pipeline", "") or "",
            "status": r.get("status", ""),
            "note": r.get("note", "") or "",
            "triage": r.get("triage", "") or "",
        }
    return rows


def load_ocr_tokens(cache_path: Path) -> dict:
    """{image_basename: [(conf, text), ...]} — strict per-model tag, no clobber."""
    if not cache_path.exists():
        return {}
    d = json.loads(cache_path.read_text())
    out = {}
    for key, toks in d.items():
        tag = "v3" if "|det=v3|" in key else ("v4" if "|det=ch_PP-OCRv4" in key else None)
        if tag is None:
            continue
        m = re.search(r"/(image\d+_[a-z0-9_.]+\.jpg)", key)
        if not m:
            continue
        out[(tag, m.group(1))] = [(round(float(t.get("conf", 0)), 3), t.get("text", ""))
                                  for t in toks]
    return out


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    d1, d2 = Path(sys.argv[1]), Path(sys.argv[2])
    r1 = load_rows(d1 / "pipeline_vs_oracle.csv")
    r2 = load_rows(d2 / "pipeline_vs_oracle.csv")

    fixed, broke, drift = [], [], []
    for (prod, field), row1 in sorted(r1.items()):
        row2 = r2.get((prod, field))
        if row2 is None:
            continue
        if row1["status"] == row2["status"] and row1["pipeline"] == row2["pipeline"]:
            continue
        changed = row1["pipeline"] != row2["pipeline"] or row1["status"] != row2["status"]
        if not changed:
            continue
        s1, s2 = row1["status"], row2["status"]
        # v4 FIXES a cell: v3 not-ok -> v4 ok
        if s1 != "ok" and s2 == "ok":
            fixed.append((prod, field, row1["pipeline"], row2["pipeline"]))
        # v4 BREAKS a cell: v3 ok -> v4 not-ok
        elif s1 == "ok" and s2 != "ok":
            broke.append((prod, field, row1["pipeline"], row2["pipeline"]))
        else:
            drift.append((prod, field, s1, s2, row1["pipeline"], row2["pipeline"]))

    print(f"== {d1.name} -> {d2.name} ==")
    print(f"FIXED ({len(fixed)}):")
    for prod, field, p1, p2 in fixed:
        print(f"  {prod:>3} {field:18s} {p1!r:42s} -> {p2!r}")
    print(f"\nBROKE ({len(broke)}):")
    for prod, field, p1, p2 in broke:
        print(f"  {prod:>3} {field:18s} {p1!r:42s} -> {p2!r}")
    print(f"\nDRIFT/other ({len(drift)}):")
    for prod, field, s1, s2, p1, p2 in drift:
        print(f"  {prod:>3} {field:18s} [{s1}->{s2}] {p1!r:42s} -> {p2!r}")

    # OCR token change counts per photo (v3 vs v4 raw reads), strict per tag
    toks = load_ocr_tokens(Path("/tmp/pipeline_audit_ocr_cache.json"))
    t3 = {b: v for (t, b), v in toks.items() if t == "v3"}
    t4c = {b: v for (t, b), v in toks.items() if t == "v4"}
    print(f"\nOCR token photos: v3={len(t3)} v4={len(t4c)}")
    if t3 and t4c:
        changed = sorted(set(t4c) & set(t3))
        n_changed = sum(1 for k in changed if t4c[k] != t3[k])
        print(f"v4 photos with tokens differing from v3: {n_changed}/{len(changed)}")
        same = [k for k in changed if t4c[k] == t3[k]]
        if same:
            print(f"  token-identical photos (any cell delta here is SLM noise): {same}")

    # Attribute each fixed/broke cell to OCR-driven vs SLM-noise using the photos
    # involved. The run CSVs don't carry the image list, so this is heuristic:
    # a cell is OCR-suspect if ANY of its photo tokens differ.
    ocr_changed = {k for k in changed if t4c[k] != t3[k]} if t3 and t4c else set()
    print("\n-- attribution (photos with v4 token diffs) --")
    ev = sorted(set(p for (p, _f, _a, _b) in list(fixed) + list(broke)))
    for p in ev:
        imgs = [b for b in ocr_changed if b.startswith(f"image{p}_")]
        print(f"  product {p}: {len(imgs)} photos with OCR token diffs ({imgs})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())