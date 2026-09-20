#!/usr/bin/env python3
"""Cascade benchmark: CPU-regex baseline vs. resource-adaptive VLM escalation.

The pitch metric: on the same 32 product groups, how many statutory fields are
recovered by (a) the frugal CPU path alone and (b) the CPU path + VLM escalation
on groups whose coverage drops below ``--threshold``.

VLM canvasses are cached in ``/tmp/vlm_rescue_cache.json`` keyed by
``image_path|model`` so re-runs (and later fairness re-checks) are free.

Usage (from backend/):
    python scripts/cascade_bench.py [--images-dir PATH] [--product 9]
        [--model qwen2.5vl:3b] [--threshold 5] [--no-vlm]

Metrics match scripts/regex_audit.py on purpose (presence of each of the 9
tracked statutory fields), so the two can be compared apples-to-apples.
"""

import argparse
import json
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys

sys.path.insert(0, str(ROOT))

from rapidocr_onnxruntime import RapidOCR  # type: ignore

from app.services.field_classifier import RegexFieldClassifier
from app.services.ocr_engine import _postprocess_text

from app.services.vlm_rescuer import VLMRescuer

STAT_KEYS = ("mrp", "usp", "net_quantity")
OCR_CACHE = Path("/tmp/regex_audit_cache.json")
VLM_CACHE = Path("/tmp/vlm_rescue_cache.json")
FIELDS = ["mrp", "usp", "net_quantity", "product_name", "manufacturer",
          "manufacturing_date", "expiry_date", "consumer_care", "edible"]

_ocr = RapidOCR()
_rescuer = None


def _cached_ocr(path: str) -> list[dict]:
    key = str(path)
    cache = json.loads(OCR_CACHE.read_text()) if OCR_CACHE.exists() else {}
    if key in cache:
        return cache[key]
    print(f"  OCR: {Path(path).name}...", end=" ", flush=True)
    t0 = time.time()
    raw, _ = _ocr(path)
    print(f"{time.time()-t0:.1f}s")
    tokens = []
    for r in (raw or []):
        tokens.append({"text": _postprocess_text(r[1]), "box": r[0], "conf": r[2]})
    cache[key] = tokens
    OCR_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return tokens


def _regex_extract(tokens: list[dict]) -> dict:
    lines = [{"text": t["text"], "box": t["box"]} for t in tokens]
    return RegexFieldClassifier().classify(lines).get("fields", {})


def _vlm_canvas(path: str, model: str) -> dict | None:
    """VLM read of one label image, cached. Returns {field: value, ...}."""
    key = f"{path}|{model}"
    cache = json.loads(VLM_CACHE.read_text()) if VLM_CACHE.exists() else {}
    if key in cache:
        return cache[key]
    global _rescuer
    if _rescuer is None:
        _rescuer = VLMRescuer(model=model)
    bare = {f: "" for f in FIELDS + ["dimensions"]}
    bare["tokens"] = _cached_ocr(path)
    bare["ocr_meta"] = {"classifier": "regex"}
    print(f"  VLM: {Path(path).name}...", end=" ", flush=True)
    t0 = time.time()
    rescued = _rescuer.rescue(path, bare, min_tokens=-1)
    print(f"{time.time()-t0:.1f}s")
    out = {f: rescued.get(f, "") for f in FIELDS} if rescued else None
    cache[key] = out
    VLM_CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return out


def _merge(results: list[dict]) -> dict:
    merged = {}
    for r in results:
        for key, value in (r or {}).items():
            if not value:
                continue
            if key in STAT_KEYS and key in merged:
                continue
            if key not in merged or len(str(value)) > len(str(merged[key])):
                merged[key] = value
    return merged


def _group_images(images_dir: Path) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for p in sorted(images_dir.glob("image*.jpg")):
        parts = p.stem.split(".")[0].rsplit("_", 1)
        if len(parts) == 2:
            groups[parts[0]].append(str(p))
    return dict(sorted(groups.items(), key=lambda x: int(x[0].replace("image", "")) if x[0].replace("image", "").isdigit() else 0))


def _coverage(merged: dict) -> int:
    return sum(1 for f in FIELDS if (merged.get(f) or "").strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", default="/mnt/e/SIH_installation_files/images")
    ap.add_argument("--product", default=None)
    ap.add_argument("--model", default="qwen2.5vl:3b")
    ap.add_argument("--threshold", type=int, default=5,
                    help="escalate a group when its regex merge recovers fewer fields than this")
    ap.add_argument("--no-vlm", action="store_true")
    args = ap.parse_args()

    images_dir = Path(args.images_dir)
    groups = _group_images(images_dir)
    totals = {"regex": {f: 0 for f in FIELDS}, "cascade": {f: 0 for f in FIELDS}}
    escalated = 0
    t_start = time.time()

    for prefix, paths in groups.items():
        if args.product and prefix.replace("image", "") != args.product:
            continue
        regex_per = [_regex_extract(_cached_ocr(p)) for p in paths]
        merged_regex = _merge(regex_per)
        cover = _coverage(merged_regex)

        per = regex_per
        if not args.no_vlm and cover < args.threshold:
            escalated += 1
            for p in paths:
                vlm = _vlm_canvas(p, args.model)
                if vlm:
                    regex_per[paths.index(p)] = {**regex_per[paths.index(p)], **vlm}
            merged_cascade = _merge(regex_per)
        else:
            merged_cascade = merged_regex

        print(f"[{prefix}] regex_cover={cover}/9 -> cascade_cover={_coverage(merged_cascade)}/9")
        for f in FIELDS:
            totals["regex"][f] += 1 if (merged_regex.get(f) or "").strip() else 0
            totals["cascade"][f] += 1 if (merged_cascade.get(f) or "").strip() else 0

    print(f"\n{'='*66}")
    print(f"RECOVERY COVERAGE  (groups escalated: {escalated})")
    print(f"{'='*66}")
    print(f"  {'field':20s} {'CPU regex':>12s} {'+ VLM cascade':>14s}")
    for f in FIELDS:
        r, c = totals["regex"][f], totals["cascade"][f]
        n = len(groups) if args.product is None else 1
        print(f"  {f:20s} {r:3d}/{n:<9d} {c:3d}/{n:<9d}")
    r_t = sum(totals["regex"].values())
    c_t = sum(totals["cascade"].values())
    n_t = len(groups) * len(FIELDS) if args.product is None else len(FIELDS)
    print(f"  {'TOTAL':20s} {r_t:3d}/{n_t:<9d} {c_t:3d}/{n_t:<9d}")
    print(f"\n  elapsed: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()