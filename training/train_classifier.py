"""
train_classifier.py — MetrIQ ML Field Classifier (80/20 Train/Test Split)
"""

import re
import sys
import pandas as pd
import numpy as np
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report, confusion_matrix
from sklearn.preprocessing import LabelEncoder

# ── feature extraction ─────────────────────────────────────────────────────
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

# ── load dataset ──────────────────────────────────────────────────────────
CSV_PATH = "dataset_complete_filled.csv"
FIELD_MAP = {
    "mrp": "mrp", "usp": "usp", "net_quantity": "net_quantity",
    "product_name": "product_name", "manufacturer": "manufacturer",
    "manufacturing_date": "manufacturing_date",
    "expiry_date": "expiry_date", "consumer_care": "consumer_care",
}

def load_data(csv_path):
    df = pd.read_csv(csv_path)
    X, y = [], []
    for _, row in df.iterrows():
        for col, label in FIELD_MAP.items():
            val = str(row.get(col, "")).strip()
            if val in SKIP:
                continue
            X.append(extract_features(val))
            y.append(label)
    return np.array(X), y

# ── train ─────────────────────────────────────────────────────────────────
def train(csv_path: str = CSV_PATH):
    print(f"Loading dataset from {csv_path} …")
    X, y_raw = load_data(csv_path)
    print(f"  {len(X)} training examples across {len(set(y_raw))} classes")

    le = LabelEncoder()
    y = le.fit_transform(y_raw)

    # ---- 80/20 split ----
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )
    print(f"\nTrain set: {len(X_train)} examples")
    print(f"Test set:  {len(X_test)} examples")

    # ---- Train on 80% ----
    clf = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=10,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    clf.fit(X_train, y_train)

    # ---- Evaluate on 20% (test) ----
    y_pred = clf.predict(X_test)
    test_acc = clf.score(X_test, y_test)
    print(f"\n── Test set accuracy: {test_acc:.1%} ──")
    print("\nClassification Report (Test Set):")
    print(classification_report(y_test, y_pred, target_names=le.classes_))

    # ---- (Optional) Cross‑validation on train set ----
    from sklearn.model_selection import cross_val_score
    cv_scores = cross_val_score(clf, X_train, y_train, cv=5, scoring="accuracy")
    print(f"\n5‑Fold CV (on train set): {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

    # ---- Final model on ALL data (for deployment) ----
    print("\nTraining final model on all data …")
    clf_final = RandomForestClassifier(
        n_estimators=100,
        max_depth=10,
        min_samples_split=10,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1,
    )
    clf_final.fit(X, y)
    final_acc = clf_final.score(X, y)
    print(f"  Final in‑sample accuracy: {final_acc:.1%}")

    # ---- Save ----
    joblib.dump(clf_final, "field_classifier.pkl")
    joblib.dump(le, "label_encoder.pkl")
    print("\n✅  Saved: field_classifier.pkl  +  label_encoder.pkl")

    return clf_final, le

if __name__ == "__main__":
    import os
    if not os.path.exists(CSV_PATH):
        sys.exit(f"ERROR: {CSV_PATH} not found. Run from the training/ directory.")
    train()