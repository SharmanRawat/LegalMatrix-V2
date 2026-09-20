#!/usr/bin/env python3
"""Audit the RegexFieldClassifier across all product images in the data folder.

Usage (from backend/):
    python scripts/regex_audit.py [--images-dir PATH] [--product 5]

Caches OCR lines to ``/tmp/regex_audit_cache.json`` so subsequent runs are
near-instant.  Only re-runs OCR for images not already in the cache.
"""

import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rapidocr_onnxruntime import RapidOCR  # type: ignore

from app.services.field_classifier import RegexFieldClassifier
from app.services.ocr_engine import (
    _postprocess_text,
    _merge_classifiers,
    EXPECTED_KEYS,
)

STAT_KEYS = ("mrp", "usp", "net_quantity")

# ── OCR cache ────────────────────────────────────────────────────────────────
CACHE = Path("/tmp/regex_audit_cache.json")
_ocr = RapidOCR()


def _cached_ocr(path: str) -> list[dict]:
    key = str(path)
    if CACHE.exists():
        cache = json.loads(CACHE.read_text())
    else:
        cache = {}
    if key in cache:
        return cache[key]
    print(f"  OCR: {Path(path).name}...", end=" ", flush=True)
    t0 = time.time()
    raw, _ = _ocr(path)
    print(f"{time.time()-t0:.1f}s")
    tokens: list[dict] = []
    for r in (raw or []):
        raw_text = r[1]
        text = _postprocess_text(raw_text)
        tokens.append({"text": text, "box": r[0], "conf": r[2]})
    cache[key] = tokens
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return tokens


def _extract(tokens: list[dict]) -> dict:
    lines = [{"text": t["text"], "box": t["box"]} for t in tokens]
    return RegexFieldClassifier().classify(lines)


def _merge(results: list[dict]) -> dict:
    merged = {}
    for r in results:
        fields = r.get("fields", {})
        for key, value in fields.items():
            if not value:
                continue
            if key in STAT_KEYS and key in merged:
                continue
            if key not in merged or len(str(value)) > len(str(merged[key])):
                merged[key] = value
    return merged


# ── Image groups ──────────────────────────────────────────────────────────────
def _group_images(images_dir: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in sorted(images_dir.glob("image*.jpg")):
        name = p.stem
        # image13_1 → 13; image13_2.enhanced → 13
        base = name.split(".")[0]
        parts = base.rsplit("_", 1)
        if len(parts) == 2:
            groups[parts[0]].append(str(p))
    return dict(sorted(groups.items(), key=lambda x: int(x[0].replace("image", "")) if x[0].replace("image", "").isdigit() else 0))


def _pick_best(results: list[dict]) -> int:
    best, best_i = -1, 0
    for i, r in enumerate(results):
        fields = r.get("fields", {})
        w = sum(1 for k in STAT_KEYS if fields.get(k))
        if w > best:
            best, best_i = w, i
    return best_i


_FIELDS_TO_SHOW = ["mrp", "usp", "net_quantity", "product_name", "manufacturer",
                   "manufacturing_date", "expiry_date", "consumer_care", "edible"]


def _shorten(s: str, limit: int = 42) -> str:
    s = str(s or "")
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def main():
    images_dir = Path("/mnt/e/SIH_installation_files/images")
    product_filter = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--images-dir" and i < len(sys.argv) - 1:
            images_dir = Path(sys.argv[i + 1])
        elif arg == "--product" and i < len(sys.argv) - 1:
            product_filter = sys.argv[i + 1]

    if not images_dir.exists():
        repo_images = ROOT.parent / "images"
        if repo_images.exists():
            print(f"  (E-drive path not mounted; using repo images at {repo_images})")
            images_dir = repo_images

    groups = _group_images(images_dir)
    total_fields = {f: 0 for f in _FIELDS_TO_SHOW}
    found_fields = {f: 0 for f in _FIELDS_TO_SHOW}

    for prefix, paths in groups.items():
        num = prefix.replace("image", "")
        if product_filter and num != product_filter:
            continue
        print(f"\n{'='*60}")
        print(f"PRODUCT GROUP: {prefix}  ({len(paths)} images)")
        print(f"{'='*60}")

        per_image_results: list[dict] = []
        for p in paths:
            tokens = _cached_ocr(p)
            result = _extract(tokens)
            fields = result.get("fields", {})
            per_image_results.append(result)
            token_count = len(tokens)
            short_name = Path(p).name
            field_summary = ", ".join(
                f"{k}={_shorten(fields.get(k, ''), 30)!r}"
                for k in _FIELDS_TO_SHOW
                if fields.get(k)
            )
            print(f"  [{short_name}] {token_count} tokens | fields: {field_summary or '(none)'}")

        # Merge across images
        merged = _merge(per_image_results)
        print(f"\n  MERGED:")
        for f in _FIELDS_TO_SHOW:
            v = str(merged.get(f, "") or "").strip()
            marker = " ✓" if v else " ✗"
            total_fields[f] += 1
            if v:
                found_fields[f] += 1
            print(f"    {f:20s}: {_shorten(v, 50):50s}{marker}")

    n = len(groups) if product_filter is None else 1
    print(f"\n{'='*60}")
    print("EXTRACTION COVERAGE")
    print(f"{'='*60}")
    for f in _FIELDS_TO_SHOW:
        t, v = total_fields[f], found_fields[f]
        pct = (v / t * 100) if t else 0
        print(f"  {f:20s}: {v:3d}/{t:3d}  ({pct:5.1f}%)")
    total_sum = sum(total_fields.values())
    found_sum = sum(found_fields.values())
    pct = (found_sum / total_sum * 100) if total_sum else 0
    print(f"  {'TOTAL':20s}: {found_sum:3d}/{total_sum:3d}  ({pct:5.1f}%)")


if __name__ == "__main__":
    main()
