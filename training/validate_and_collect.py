"""
validate_and_collect.py — MetrIQ Self-Improvement Pipeline (Raw ML Classifier)
"""

import re
import sys
import csv
import pandas as pd
import numpy as np
import joblib
from pathlib import Path

HERE = Path(__file__).parent
CLF  = joblib.load(HERE / "field_classifier.pkl")
LE   = joblib.load(HERE / "label_encoder.pkl")

SKIP = {"NOT_VISIBLE", "could not find", "N/A", "NA", "", "nan"}
FIELDS = [
    "mrp", "usp", "net_quantity", "product_name",
    "manufacturer", "manufacturing_date", "expiry_date", "consumer_care",
]

# ── feature extraction (same as train_classifier.py) ─────────────────────
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
    if not isinstance(text, str) or text.strip() in SKIP:
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

def classify(text):
    feats = np.array([extract_features(text)])
    proba = CLF.predict_proba(feats)[0]
    idx   = int(np.argmax(proba))
    return LE.inverse_transform([idx])[0], float(proba[idx])

# ── fuzzy match ────────────────────────────────────────────────────────────
def fuzzy_match(gt: str, pred: str, threshold: float = 0.6) -> bool:
    if not gt or not pred:
        return False
    gt   = gt.strip().lower()
    pred = pred.strip().lower()
    if gt == pred:
        return True
    gt_nums   = set(re.findall(r'\d+\.?\d*', gt))
    pred_nums = set(re.findall(r'\d+\.?\d*', pred))
    if gt_nums and gt_nums == pred_nums:
        return True
    gt_tokens   = set(re.findall(r'\w+', gt))
    pred_tokens = set(re.findall(r'\w+', pred))
    if not gt_tokens:
        return False
    overlap = len(gt_tokens & pred_tokens) / len(gt_tokens)
    return overlap >= threshold

# ── main ──────────────────────────────────────────────────────────────────
def run(csv_path: str = "dataset_complete_filled.csv"):
    df = pd.read_csv(csv_path)

    stats   = {f: {"correct": 0, "total": 0} for f in FIELDS}
    errors  = []

    for _, row in df.iterrows():
        pid = row.get("product_id", "?")
        for field in FIELDS:
            gt = str(row.get(field, "")).strip()
            if gt in SKIP:
                continue

            pred_label, confidence = classify(gt)
            stats[field]["total"] += 1

            # "correct" means the model labelled it as the right field
            correct = (pred_label == field) or (
                field in ("manufacturing_date", "expiry_date")
                and pred_label in ("manufacturing_date", "expiry_date")
            )

            if correct:
                stats[field]["correct"] += 1
            else:
                errors.append({
                    "product_id":    pid,
                    "field":         field,
                    "value":         gt,
                    "predicted":     pred_label,
                    "confidence":    round(confidence, 3),
                    "correct_label": field,
                })

    # ── report ────────────────────────────────────────────────────────────
    lines = []
    lines.append("=" * 60)
    lines.append("  MetrIQ Field Classifier — Validation Report (Raw ML)")
    lines.append("=" * 60)
    lines.append(f"{'Field':<22} {'Correct':>7} {'Total':>7} {'Accuracy':>9}")
    lines.append("-" * 50)

    total_c = total_t = 0
    for field in FIELDS:
        c = stats[field]["correct"]
        t = stats[field]["total"]
        acc = f"{c/t:.1%}" if t else "N/A"
        lines.append(f"{field:<22} {c:>7} {t:>7} {acc:>9}")
        total_c += c; total_t += t

    lines.append("-" * 50)
    overall = f"{total_c/total_t:.1%}" if total_t else "N/A"
    lines.append(f"{'OVERALL':<22} {total_c:>7} {total_t:>7} {overall:>9}")
    lines.append("=" * 60)
    lines.append(f"\nErrors logged: {len(errors)}")
    lines.append("Run retrain_from_errors.py to improve the model.")

    report = "\n".join(lines)
    print(report)

    with open("validation_report.txt", "w") as f:
        f.write(report)

    # ── save errors ───────────────────────────────────────────────────────
    if errors:
        keys = ["product_id", "field", "value", "predicted", "confidence", "correct_label"]
        with open("errors.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            w.writerows(errors)
        print(f"\nErrors saved to errors.csv ({len(errors)} rows)")
    else:
        print("\nNo errors — model is perfect on training data!")

    return stats, errors

if __name__ == "__main__":
    import os
    csv_path = sys.argv[1] if len(sys.argv) > 1 else "dataset_complete_filled.csv"
    if not os.path.exists(csv_path):
        sys.exit(f"ERROR: {csv_path} not found. Run from the training/ directory.")
    run(csv_path)