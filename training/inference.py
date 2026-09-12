"""
inference.py — MetrIQ ML Field Classifier  (standalone / test script)

Usage examples
--------------
# Classify a single text string
python inference.py "₹ 249/-"

# Interactive mode (type texts, press Ctrl-C to exit)
python inference.py

# Pipe a file of texts (one per line)
cat ocr_texts.txt | python inference.py --pipe

# Test against the training CSV (quick sanity check)
python inference.py --eval dataset_complete_filled.csv
"""

import sys
import re
import os
import argparse
import json
from pathlib import Path

import joblib
import numpy as np

# ── locate model files ────────────────────────────────────────────
_HERE = Path(__file__).parent
_CLF_PATH  = _HERE / "field_classifier.pkl"
_LE_PATH   = _HERE / "label_encoder.pkl"

if not _CLF_PATH.exists() or not _LE_PATH.exists():
    sys.exit(
        f"ERROR: model files not found in {_HERE}\n"
        "Run  python train_classifier.py  first."
    )

clf = joblib.load(_CLF_PATH)
le  = joblib.load(_LE_PATH)

# ── feature extraction (identical to train_classifier.py) ─────────
MONTH_ABBRS  = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b'
DATE_PATTERNS = [
    r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}',
    r'\d{2,4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}',
    r'\d{1,2}/\d{2}',
]
PHONE_PATTERN = r'(\b1800|\+91|0\d{9,10}|\b\d{5}[-\s]\d{5,6}\b)'


def _year_val(text):
    m = re.search(r'\b(20\d{2})\b', text)
    if m: return (int(m.group(1)) - 2020) / 10.0
    m = re.search(r'\b(\d{2})\b', text)
    if m:
        y = int(m.group(1))
        if 20 <= y <= 40: return (y - 20) / 10.0
    return 0.0


def extract_features(text):
    if not isinstance(text, str) or text.strip() in ("", "NOT_VISIBLE", "could not find"):
        text = ""
    t = text.strip(); tl = t.lower()
    n_chars = len(t); n_digits = sum(c.isdigit() for c in t)
    n_upper = sum(c.isupper() for c in t); n_alpha = sum(c.isalpha() for c in t)
    n_words = len(t.split()); n_lines = t.count('\n') + 1

    has_rupee_symbol = '₹' in t
    has_rs   = bool(re.search(r'\brs\.?\b', tl))
    has_curr = has_rupee_symbol or has_rs
    has_weight_unit = bool(re.search(r'\b(g|gm|gram|kg|mg)\b', tl))
    has_volume_unit = bool(re.search(r'\b(ml|l|litre|liter)\b', tl))
    has_unit = has_weight_unit or has_volume_unit or bool(re.search(r'\b(cm|mm|m|meter|metre)\b', tl))
    has_mfg_kw = bool(re.search(r'\b(mfg|manufactured|manufacturing)\b', tl))
    has_exp_kw = bool(re.search(r'\b(exp|expiry|expiry date|best before|use by|bb)\b', tl))

    return [
        n_chars, n_digits, n_words, n_lines,
        n_digits / max(n_chars, 1), n_upper / max(n_alpha, 1),
        n_alpha / max(n_words, 1), len(re.findall(r'\d+', t)),
        int(has_curr), int(has_rupee_symbol), int(has_rs),
        int(bool(re.search(r'/\s*-', t))), int(bool(re.search(r'\bper\b', tl))),
        int('.' in t and bool(re.search(r'\d\.\d', t))),
        int(bool(re.search(r'\d\s*/\s*[a-z]+', tl))),
        int(has_unit), int(has_weight_unit), int(has_volume_unit),
        int(bool(re.search(r'\bm\.?r\.?p\.?\b', tl))),
        int(bool(re.search(r'maximum retail', tl))),
        int(bool(re.search(r'incl.*tax|inclusive.*tax', tl))),
        int(bool(re.search(r'\busp\b', tl))),
        int(bool(re.search(r'unit sale', tl))),
        int(bool(re.search(r'(price|₹|rs)\s*\d+.*per\s*\w+', tl))),
        int(has_mfg_kw), int(has_exp_kw),
        int(bool(re.search(MONTH_ABBRS, tl))), int(bool(re.search(r'\b(19|20)\d{2}\b', t))),
        int(any(bool(re.search(p, t)) for p in DATE_PATTERNS)),
        int(bool(re.search(r'\bdot\b', tl))),
        int(has_mfg_kw and not has_exp_kw), int(has_exp_kw and not has_mfg_kw),
        int(bool(re.search(r'best before|use by\b', tl))),
        int(bool(re.search(r'\bbb\b', tl))),
        _year_val(t),
        int(bool(re.search(r'\b(manufacturer|manufactured|packer|packed|marketed|marketed by|mfg by)\b', tl))),
        int(bool(re.search(r'\b(pvt|ltd|llp|inc|corp|co\.|foods|industries|enterprises|limited)\b', tl))),
        int(bool(re.search(r'\b(plot|sector|phase|unit|building|road|street|nagar|industrial)\b', tl))),
        int(bool(re.search(r'\bgstin\b|\b\d{2}[A-Z]{5}\d{4}[A-Z]{1}', t))),
        int(bool(re.search(r'\bfssai\b|\blic\.?\s*no\b', tl))),
        int(bool(re.search(r'\b(consumer care|customer care|helpline|toll.?free|complaint)\b', tl))),
        int(bool(re.search(r'[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}', tl))),
        int(bool(re.search(PHONE_PATTERN, t))), int('1800' in t),
        int(n_chars < 40), int(t.istitle()),
        int(all(w.replace("&","").replace("'","").isalpha() for w in t.split() if w)),
    ]


# ── core classify function ────────────────────────────────────────

def classify(text: str, top_k: int = 3) -> dict:
    """
    Returns a dict:
      {
        "text": str,
        "prediction": str,
        "confidence": float,
        "top_k": [(label, confidence), ...]
      }
    """
    feats = np.array([extract_features(text)])
    proba = clf.predict_proba(feats)[0]
    order = np.argsort(proba)[::-1]
    top   = [(le.classes_[i], round(float(proba[i]), 4)) for i in order[:top_k]]
    return {
        "text":       text,
        "prediction": top[0][0],
        "confidence": top[0][1],
        "top_k":      top,
    }


def classify_ocr_boxes(boxes: list[dict], threshold: float = 0.40) -> dict:
    """
    Takes a list of OCR result dicts ({"text": ..., "bbox": ..., ...})
    and returns a field → box mapping (same shape as extract_all).
    """
    fields = ["mrp","net_quantity","usp","manufacturer","product_name","date","consumer_care"]
    output = {f: None for f in fields}
    label_to_field = {
        "mrp": "mrp", "usp": "usp", "net_quantity": "net_quantity",
        "product_name": "product_name", "manufacturer": "manufacturer",
        "manufacturing_date": "date", "expiry_date": "date",
        "consumer_care": "consumer_care",
    }
    candidates = {f: [] for f in fields}

    for box in boxes:
        text = box.get("text", "") if isinstance(box, dict) else str(box)
        r    = classify(text)
        field = label_to_field.get(r["prediction"])
        if field and r["confidence"] >= threshold:
            candidates[field].append((r["confidence"], box))

    for field, cands in candidates.items():
        if cands:
            output[field] = max(cands, key=lambda x: x[0])[1]
    return output


# ── eval mode ────────────────────────────────────────────────────

def _eval(csv_path: str):
    import pandas as pd
    from sklearn.metrics import classification_report
    df   = pd.read_csv(csv_path)
    SKIP = {"NOT_VISIBLE", "could not find", "N/A", "NA", "", "nan"}
    FIELDS = ["mrp","usp","net_quantity","product_name","manufacturer",
              "manufacturing_date","expiry_date","consumer_care"]
    texts, true_labels = [], []
    for _, row in df.iterrows():
        for col in FIELDS:
            val = str(row.get(col, "")).strip()
            if val not in SKIP:
                texts.append(val)
                true_labels.append(col)

    feats  = np.array([extract_features(t) for t in texts])
    preds  = le.inverse_transform(clf.predict(feats))
    print(classification_report(true_labels, preds, zero_division=0))


# ── CLI ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="MetrIQ ML Field Classifier")
    parser.add_argument("text", nargs="?", help="Text to classify")
    parser.add_argument("--pipe", action="store_true", help="Read lines from stdin")
    parser.add_argument("--eval", metavar="CSV", help="Evaluate against a CSV")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument("--top", type=int, default=3, help="Show top-k predictions")
    args = parser.parse_args()

    if args.eval:
        _eval(args.eval)
        return

    if args.pipe:
        for line in sys.stdin:
            r = classify(line.rstrip('\n'), top_k=args.top)
            if args.json:
                print(json.dumps(r, ensure_ascii=False))
            else:
                print(f"{r['prediction']:20s}  {r['confidence']:.2%}  |  {r['text'][:60]}")
        return

    if args.text:
        r = classify(args.text, top_k=args.top)
        if args.json:
            print(json.dumps(r, indent=2, ensure_ascii=False))
        else:
            print(f"\n  Text:       {r['text']}")
            print(f"  Prediction: {r['prediction']}  ({r['confidence']:.1%} confidence)")
            print("  Top-k:")
            for label, conf in r["top_k"]:
                bar = "█" * int(conf * 20)
                print(f"    {label:22s} {conf:5.1%}  {bar}")
        return

    # Interactive mode
    print("MetrIQ Field Classifier  (Ctrl-C to exit)\n")
    while True:
        try:
            text = input("OCR text> ").strip()
            if not text: continue
            r = classify(text, top_k=args.top)
            print(f"  → {r['prediction']}  ({r['confidence']:.1%})")
            for label, conf in r["top_k"][1:]:
                print(f"     {label:22s} {conf:.1%}")
        except (KeyboardInterrupt, EOFError):
            print("\nBye.")
            break


if __name__ == "__main__":
    main()
