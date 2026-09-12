"""
retrain_from_errors.py — MetrIQ Iterative Retraining
=====================================================
Loads errors.csv (from validate_and_collect.py), merges with the original
training data, retrains the classifier, and prints accuracy delta.

Usage:
    cd /path/to/SIH2026/training
    python retrain_from_errors.py

Requires: errors.csv (run validate_and_collect.py first)
Updates:  field_classifier.pkl, label_encoder.pkl
"""

import re
import sys
import pandas as pd
import numpy as np
import joblib
from pathlib import Path
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.metrics import classification_report
from sklearn.preprocessing import LabelEncoder

HERE = Path(__file__).parent

# ── feature extraction (identical to train_classifier.py) ─────────────────
MONTH_ABBRS  = r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b'
DATE_PATTERNS = [
    r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}',
    r'\d{2,4}[/\-\.]\d{1,2}[/\-\.]\d{1,2}',
    r'\d{1,2}/\d{2}',
]
PHONE_PATTERN = r'(\b1800|\+91|0\d{9,10}|\b\d{5}[-\s]\d{5,6}\b)'
SKIP = {"NOT_VISIBLE", "could not find", "N/A", "NA", "", "nan"}


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


FIELD_COLS = [
    "mrp", "usp", "net_quantity", "product_name",
    "manufacturer", "manufacturing_date", "expiry_date", "consumer_care",
]


def load_base(csv_path):
    df = pd.read_csv(csv_path)
    X, y = [], []
    for _, row in df.iterrows():
        for col in FIELD_COLS:
            val = str(row.get(col, "")).strip()
            if val in SKIP:
                continue
            X.append(extract_features(val))
            y.append(col)
    return X, y


def load_errors(errors_path):
    """Load misclassified examples; each is added with correct label (oversampled 3x)."""
    df = pd.read_csv(errors_path)
    X, y = [], []
    for _, row in df.iterrows():
        val   = str(row.get("value", "")).strip()
        label = str(row.get("correct_label", "")).strip()
        if val in SKIP or label not in FIELD_COLS:
            continue
        # Oversample errors 3x so the model pays more attention
        for _ in range(3):
            X.append(extract_features(val))
            y.append(label)
    return X, y


def retrain(csv_path="dataset_complete_filled.csv", errors_path="errors.csv"):
    # ── load original accuracy ────────────────────────────────────────────
    print("Loading original model …")
    clf_old = joblib.load(HERE / "field_classifier.pkl")
    le_old  = joblib.load(HERE / "label_encoder.pkl")

    X_base, y_base = load_base(csv_path)
    X_base_arr     = np.array(X_base)
    y_base_enc     = le_old.transform(y_base)

    old_acc = clf_old.score(X_base_arr, y_base_enc)
    print(f"  Baseline in-sample accuracy: {old_acc:.1%}")

    # ── load errors ───────────────────────────────────────────────────────
    errors_path_obj = Path(errors_path)
    if not errors_path_obj.exists():
        print(f"\nNo {errors_path} found — run validate_and_collect.py first.")
        sys.exit(1)

    X_err, y_err = load_errors(errors_path)
    print(f"  Error examples loaded: {len(X_err)} (from {len(X_err)//3} unique misclassifications)")

    # ── merge and retrain ─────────────────────────────────────────────────
    X_all = X_base + X_err
    y_all = y_base + y_err

    le_new = LabelEncoder()
    y_enc  = le_new.fit_transform(y_all)
    X_arr  = np.array(X_all)

    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    clf_new = RandomForestClassifier(
        n_estimators=300, max_depth=None, min_samples_leaf=1,
        class_weight="balanced", random_state=42, n_jobs=-1,
    )
    cv_scores = cross_val_score(clf_new, X_arr, y_enc, cv=skf, scoring="accuracy")
    print(f"\n5-Fold CV Accuracy after retraining: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    clf_new.fit(X_arr, y_enc)
    new_acc = clf_new.score(X_arr, y_enc)
    print(f"  New in-sample accuracy: {new_acc:.1%}")
    print(f"  Delta: {new_acc - old_acc:+.1%}")

    print("\n── Per-class report (in-sample) ──")
    y_pred = clf_new.predict(X_arr)
    print(classification_report(y_enc, y_pred, target_names=le_new.classes_, zero_division=0))

    # ── save ──────────────────────────────────────────────────────────────
    joblib.dump(clf_new, HERE / "field_classifier.pkl")
    joblib.dump(le_new,  HERE / "label_encoder.pkl")

    # Also copy to backend if it exists
    backend_svc = HERE.parent / "backend" / "app" / "services"
    if backend_svc.exists():
        import shutil
        shutil.copy(HERE / "field_classifier.pkl", backend_svc / "field_classifier.pkl")
        shutil.copy(HERE / "label_encoder.pkl",    backend_svc / "label_encoder.pkl")
        print("\n✅  Model deployed to backend/app/services/")
    else:
        print("\n✅  Model saved to training/")


if __name__ == "__main__":
    import os
    csv_path    = sys.argv[1] if len(sys.argv) > 1 else "dataset_complete_filled.csv"
    errors_path = sys.argv[2] if len(sys.argv) > 2 else "errors.csv"
    if not os.path.exists(csv_path):
        sys.exit(f"ERROR: {csv_path} not found.")
    retrain(csv_path, errors_path)
