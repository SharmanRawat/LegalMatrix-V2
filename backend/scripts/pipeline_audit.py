#!/usr/bin/env python3
"""Pipeline-vs-7B-VLM oracle audit.

Runs the REAL web-app pipeline per product group
    preprocessing -> RapidOCR -> qwen2.5:3b SLM classifier (+regex merge)
and compares every extracted field against the qwen2.5vl:7b VLM read of the
same photos (the oracle). Prints per-product diffs + per-field agreement and
writes machine-readable reports (JSON + CSV) to --out-dir.

Both the OCR token pass and the oracle reads are disk-cached (keyed by image
mtime so edited images re-run). Re-running after you tune the SLM prompt /
regex / preprocessor is therefore near-free: only the classifier + merge
re-execute.

Usage (from backend/):
    python scripts/pipeline_audit.py [--images-dir PATH] [--product 6]
        [--oracle qwen2.5vl:7b] [--classifier qwen2.5:3b]
        [--no-ocr-cache] [--out-dir /tmp/pipeline_audit]
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Set env BEFORE importing app modules (config reads these at import time).
os.environ.setdefault("OCR_ENGINE", "auto")
os.environ.setdefault("VLM_RESCUE_ENABLED", "0")          # measure the CPU+SLM path
os.environ.setdefault("OCR_ENHANCE_ENABLED", "1")
os.environ.setdefault("OCR_MULTI_PASS_ENABLED", "1")
os.environ.setdefault("OCR_MULTI_PASS_ON_FAIL", "1")

from app.services.ocr_engine import SmartOCRService  # noqa: E402

FIELDS = [
    "mrp", "usp", "net_quantity", "product_name", "manufacturer",
    "manufacturing_date", "expiry_date", "consumer_care", "dimensions", "edible",
]

OCR_CACHE_PATH = Path("/tmp/pipeline_audit_ocr_cache.json")
VLM_CACHE_PATH = Path("/tmp/pipeline_audit_oracle_cache.json")


# ── disk caches (loaded once, flushed on write) ─────────────────────────────
class DiskCache:
    def __init__(self, path: Path):
        self.path = path
        try:
            self._data = json.loads(path.read_text()) if path.exists() else {}
        except (OSError, json.JSONDecodeError):
            # A killed run can leave a half-written cache — start fresh
            # rather than crashing the next run.
            self._data = {}

    def get(self, key: str):
        return self._data.get(key)

    def set(self, key: str, value) -> None:
        self._data[key] = value
        try:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._data, ensure_ascii=False))
            # Atomic replace: a crash never leaves a half-written cache file.
            os.replace(tmp, self.path)
        except OSError:
            pass

    def __len__(self):
        return len(self._data)


def _fstat_key(path: str) -> str:
    try:
        st = os.stat(path)
        return f"{path}|{st.st_mtime:.3f}|{st.st_size}"
    except OSError:
        return f"{path}|?"


# ── pipeline side (cached OCR, real classification) ─────────────────────────
class CachedSmartOCR(SmartOCRService):
    """Subclasses SmartOCRService with disk-cached token passes.

    The actual classifier / merge / post-processing logic is the production
    code (SmartOCRService.extract_structured) — only the expensive raw OCR
    passes are cached, so tuning the SLM prompt or regexes re-runs just the
    cheap classification steps.
    """

    def __init__(self, ocr_cache: DiskCache, variant_cache: DiskCache):
        super().__init__()
        self._ocr_cache = ocr_cache
        self._variant_cache = variant_cache

    def _ocr_tokens(self, image_path: str):
        key = "ocr|" + _fstat_key(image_path)
        hit = self._ocr_cache.get(key)
        if hit is not None:
            return hit
        out = super()._ocr_tokens(image_path)
        self._ocr_cache.set(key, out)
        return out

    def _ocr_variant_tokens(self, image_path: str):
        key = "var|" + _fstat_key(image_path)
        hit = self._variant_cache.get(key)
        if hit is not None:
            return hit
        out = super()._ocr_variant_tokens(image_path)
        self._variant_cache.set(key, out)
        return out


def _run_pipeline(svc: CachedSmartOCR, paths: list) -> list:
    return [svc.extract_structured(p) for p in paths]


# ── oracle side (7B VLM, cached) ────────────────────────────────────────────
def _oracle_read(path: str, model: str, cache: DiskCache):
    key = "vlm|" + _fstat_key(path) + "|" + model
    hit = cache.get(key)
    if hit is not None:
        return hit
    print(f"  oracle: {Path(path).name}...", end=" ", flush=True)
    t0 = time.time()
    from app.services.vlm_rescuer import VLMRescuer
    rescuer = VLMRescuer(model=model)
    bare = {f: "" for f in FIELDS}
    bare["tokens"] = []
    bare["ocr_meta"] = {"classifier": "regex"}
    out = rescuer.rescue(path, bare)
    print(f"{time.time()-t0:.1f}s")
    result = {f: (out.get(f, "") if out else "") for f in FIELDS}
    cache.set(key, result)
    return result


# ── merge (production logic) ────────────────────────────────────────────────
def _merge(results: list) -> dict:
    from app.services.inspection_service import merge_extractions
    return {k: (merge_extractions([r for r in results]).get(k) or "") for k in FIELDS}


# ── comparison ──────────────────────────────────────────────────────────────
def _norm(s: str) -> str:
    s = str(s or "").lower().replace("\u20b9", "rs")
    s = re.sub(r"\s+", " ", s)
    return s


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


_DATE_PAT = re.compile(r"/|\.|:", re.I)


def _token_set(s: str):
    toks = set()
    for ch in re.split(r"[^a-z0-9]+", str(s or "").lower()):
        if ch.isdigit() or (2 <= len(ch) <= 3 and ch.isalpha()):
            toks.add(ch)
    return toks


def compare_field(pipe: str, oracle: str) -> tuple:
    """Returns (status, detail) with status in ok|missing|wrong|extra."""
    p, o = (_alnum(pipe), _alnum(oracle))
    if o and not p:
        return "missing", ""
    if not o and p:
        return "extra", ""
    if o and p:
        if p == o:
            return "ok", ""
        # Date formats differ ('06/04/27' vs '6/4/2027', 'JUN 2026' vs '06/2026')
        if _DATE_PAT.sub("", pipe) and _DATE_PAT.sub("", oracle):
            t0, t1 = _token_set(pipe), _token_set(oracle)
            if t0 and t0 == t1:
                return "ok", "date-equivalent"
        if len(p) >= 12 and (p in o or o in p):
            return "ok", "substring"
        return "wrong", ""
    return "ok", "both-absent"


# ── image grouping (ignore *.enhanced artifacts) ────────────────────────────
def _group_images(images_dir: Path) -> dict:
    groups = defaultdict(list)
    for p in sorted(images_dir.glob("image*.jpg")):
        m = re.fullmatch(r"image(\d+)_(\d+)", p.stem)
        if m:
            groups[m.group(1)].append(str(p))
    return dict(sorted(groups.items(), key=lambda x: int(x[0])))


def _fmt(v: str, limit: int = 40) -> str:
    v = str(v or "")
    return v if len(v) <= limit else v[: limit - 1] + "…"


def _write_reports(out_dir: Path, rows, tally, groups, t_start) -> tuple:
    csv_path = out_dir / "pipeline_vs_oracle.csv"
    with csv_path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["product", "field", "pipeline", "oracle_7b", "status", "note"])
        w.writerows(rows)
    json_path = out_dir / "pipeline_vs_oracle.json"
    json_path.write_text(json.dumps({
        "fields": FIELDS,
        "tally": {f: dict(tally[f]) for f in FIELDS},
        "rows": [dict(zip(["product", "field", "pipeline", "oracle_7b", "status", "note"], r))
                 for r in rows],
        "products": len(groups),
        "elapsed_s": round(time.time() - t_start, 1),
    }, indent=1))
    return csv_path, json_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-dir", default="/mnt/e/SIH_installation_files/images")
    ap.add_argument("--product", default=None, help="single product number, e.g. 6")
    ap.add_argument("--products", default=None,
                    help="comma-separated product numbers, e.g. '3,6,10'")
    ap.add_argument("--oracle", default="qwen2.5vl:7b")
    ap.add_argument("--classifier", default="qwen2.5:3b")
    ap.add_argument("--no-ocr-cache", action="store_true")
    ap.add_argument("--out-dir", default="/tmp/pipeline_audit")
    ap.add_argument("--answers", default=None,
                    help="file of prior 7B VLM reads -> use it as the oracle "
                         "(fast, fully offline, no VLM calls)")
    ap.add_argument("--generate-answers", default=None, metavar="PATH",
                    help="write the 7B VLM reads for every product to PATH as "
                         "ground-truth answers.json (skips the pipeline) and exit")
    args = ap.parse_args()

    os.environ["FIELD_CLASSIFIER_MODEL"] = args.classifier
    # modules already imported by helpers above; re-read the module attribute
    # so the SLM model the classifier instantiates is the requested one.
    import app.config as cfg
    cfg.FIELD_CLASSIFIER_MODEL = args.classifier

    images_dir = Path(args.images_dir)
    if not images_dir.exists():
        repo_images = ROOT.parent / "images"
        if args.images_dir == ap.get_default("images-dir") and repo_images.exists():
            images_dir = repo_images
            print(f"  (default E-drive path {args.images_dir} not mounted; "
                  f"using repo images at {images_dir})")
    if not images_dir.exists():
        ap.error(f"images dir not found: {images_dir}")
    groups = _group_images(images_dir)
    if args.product:
        groups = {k: v for k, v in groups.items() if k == args.product}
    elif args.products:
        wanted = {p.strip() for p in args.products.split(",")}
        groups = {k: v for k, v in groups.items() if k in wanted}

    answers_from_file = {}
    if args.answers:
        answers_from_file = json.loads(Path(args.answers).read_text())

    ocr_cache = DiskCache(OCR_CACHE_PATH if not args.no_ocr_cache else Path("/tmp/nocache-ocr.json"))
    vlm_cache = DiskCache(VLM_CACHE_PATH)
    svc = CachedSmartOCR(ocr_cache, vlm_cache)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    tally = defaultdict(lambda: defaultdict(int))
    rows = []
    generated_answers = {}
    t_start = time.time()

    for prefix, paths in groups.items():
        print(f"\n{'='*78}\nPRODUCT {prefix}  ({len(paths)} images: "
              f"{', '.join(Path(p).name for p in paths)})\n{'='*78}")

        oracle_merged = None
        if prefix in answers_from_file:
            t0 = time.time()
            oracle_merged = {f: (answers_from_file.get(prefix, {}).get(f, "") or "") for f in FIELDS}
            print(f"  (oracle from answers.json, {time.time()-t0:.1f}s)")
        elif args.generate_answers is not None or not args.answers:
            t0 = time.time()
            oracle_per = [_oracle_read(p, args.oracle, vlm_cache) for p in paths]
            oracle_merged = _merge(oracle_per)
            print(f"  (7B VLM oracle {time.time()-t0:.1f}s for {len(paths)} images)")
        else:
            oracle_merged = {f: "" for f in FIELDS}

        if args.generate_answers is not None:
            generated_answers[prefix] = oracle_merged
            continue

        t0 = time.time()
        pipe_per = _run_pipeline(svc, paths)
        pipe_merged = _merge(pipe_per)
        print(f"  (pipeline {time.time()-t0:.1f}s for {len(paths)} images)")

        diffs = 0
        for f in FIELDS:
            pv, ov = pipe_merged.get(f, ""), oracle_merged.get(f, "")
            status, note = compare_field(pv, ov)
            tally[f][status] += 1
            tally[f]["oracle_present"] += 1 if (ov or "").strip() else 0
            tick = {"ok": " ✓", "missing": " ✗ MISSING", "wrong": " ≈ WRONG",
                    "extra": " ? EXTRA(over-read)"}[status]
            marker = "    " if (status == "ok" and not (ov or "").strip()) else tick
            rows.append([prefix, f, pv, ov, status, note])
            if status != "ok":
                diffs += 1
            print(f"  {f:18s}{marker}")
            if status == "ok" and (ov or "").strip():
                pass
            if status in ("missing", "wrong", "extra"):
                print(f"      pipeline: {_fmt(pv)!r}")
                print(f"      oracle  : {_fmt(ov)!r}{'  ('+note+')' if note else ''}")
        if diffs == 0:
            print("  → all fields match the 7B oracle")

        # Persist incrementally so an interrupted run never loses earlier
        # products (re-running resumes from the on-disk OCR cache).
        _write_reports(out_dir, rows, tally, groups, t_start)

    if args.generate_answers is not None:
        gen_path = Path(args.generate_answers)
        gen_path.parent.mkdir(parents=True, exist_ok=True)
        gen_path.write_text(json.dumps(generated_answers, ensure_ascii=False, indent=1))
        print(f"\nSaved 7B VLM ground-truth answers for {len(generated_answers)} products "
              f"to {gen_path}")
        print(f"Next: python scripts/pipeline_audit.py --answers {gen_path}  "
              f"(validates the pipeline offline, no VLM calls)")
        return

    csv_path, json_path = _write_reports(out_dir, rows, tally, groups, t_start)

    print(f"\n{'#'*78}\nFIELD AGREEMENT vs 7B ORACLE  ({len(groups)} products)\n{'#'*78}")
    print(f"  {'field':18s} {'oracle':>7s} {'match':>7s} {'miss':>6s} {'wrong':>7s} {'extra':>7s}  recall")
    for f in FIELDS:
        t = tally[f]
        op = t["oracle_present"]
        ok = t["ok"]
        rec = f"{ok/op:5.1%}" if op else "   n/a"
        print(f"  {f:18s} {op:7d} {ok:7d} {t['missing']:6d} {t['wrong']:7d} {t['extra']:7d}  {rec}")
    ok_all = sum(tally[f]["ok"] for f in FIELDS)
    op_all = sum(tally[f]["oracle_present"] for f in FIELDS)
    print(f"  {'TOTAL':18s} {op_all:7d} {ok_all:7d} "
          f"{sum(tally[f]['missing'] for f in FIELDS):6d} "
          f"{sum(tally[f]['wrong'] for f in FIELDS):7d} "
          f"{sum(tally[f]['extra'] for f in FIELDS):7d}  "
          f"{ok_all/op_all:5.1%}" if op_all else "")
    print(f"\n  reports: {csv_path}  {json_path}")
    print(f"  total elapsed {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()