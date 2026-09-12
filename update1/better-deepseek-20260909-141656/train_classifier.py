#!/usr/bin/env python3
"""
MetrIQ - ML Classifier Training Script with Layout Features and XGBoost
SIH 2026 Demo - Updated Sep 2026

This script trains a classifier for extracting declarations from product labels
using both text-based features and spatial/layout features.
"""

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split, StratifiedKFold, cross_val_score
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score
from sklearn.feature_selection import SelectFromModel
import xgboost as xgb
import joblib
import json
import warnings
warnings.filterwarnings('ignore')

# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------
RANDOM_STATE = 42
TEST_SIZE = 0.2
N_ESTIMATORS = 200
MAX_DEPTH = 15
CV_FOLDS = 5

# Classes we're predicting
CLASSES = [
    'mrp', 'usp', 'net_quantity', 'product_name',
    'manufacturer', 'manufacturing_date', 'expiry_date', 'consumer_care'
]

# -----------------------------------------------------------------------------
# Feature Engineering
# -----------------------------------------------------------------------------
def extract_text_features(text):
    """Extract all text-based features from a string."""
    if not text or not isinstance(text, str):
        text = ''
    
    text = str(text).strip()
    
    # Basic metrics
    length = len(text)
    digit_count = sum(c.isdigit() for c in text)
    alpha_count = sum(c.isalpha() for c in text)
    space_count = sum(c.isspace() for c in text)
    special_count = len(text) - digit_count - alpha_count - space_count
    
    # Currency detection
    has_rupee = '₹' in text or 'Rs' in text or 'rs' in text.lower()
    has_dollar = '$' in text
    has_percent = '%' in text
    
    # Keyword detection
    text_lower = text.lower()
    has_mrp = 'mrp' in text_lower
    has_price = 'price' in text_lower or '₹' in text
    has_date = any(word in text_lower for word in ['date', 'exp', 'mfg', 'man', 'pack', 'best before', 'use by'])
    has_weight = any(word in text_lower for word in ['g', 'kg', 'ml', 'l', 'gm', 'mg', 'net', 'wt', 'weight'])
    has_contact = any(word in text_lower for word in ['phone', 'contact', 'call', 'email', 'www', 'http'])
    has_product = any(word in text_lower for word in ['product', 'name', 'brand', 'flavour', 'flavor'])
    has_manufacturer = any(word in text_lower for word in ['manufacturer', 'mfg', 'manufactured', 'made by', 'produced by'])
    
    # Pattern features
    has_colon = ':' in text
    has_slash = '/' in text
    has_dash = '-' in text
    has_parentheses = '(' in text and ')' in text
    
    # Number patterns
    has_decimal = '.' in text and any(c.isdigit() for c in text)
    has_comma_separated = ',' in text and any(c.isdigit() for c in text)
    
    # Capitalization features
    is_upper = text.isupper()
    is_title = text.istitle()
    contains_upper = any(c.isupper() for c in text)
    
    # Word count
    word_count = len(text.split())
    
    # Digit ratio
    digit_ratio = digit_count / length if length > 0 else 0
    
    # Unique chars ratio
    unique_ratio = len(set(text)) / length if length > 0 else 0
    
    return {
        'length': length,
        'digit_count': digit_count,
        'alpha_count': alpha_count,
        'space_count': space_count,
        'special_count': special_count,
        'has_rupee': int(has_rupee),
        'has_dollar': int(has_dollar),
        'has_percent': int(has_percent),
        'has_mrp': int(has_mrp),
        'has_price': int(has_price),
        'has_date': int(has_date),
        'has_weight': int(has_weight),
        'has_contact': int(has_contact),
        'has_product': int(has_product),
        'has_manufacturer': int(has_manufacturer),
        'has_colon': int(has_colon),
        'has_slash': int(has_slash),
        'has_dash': int(has_dash),
        'has_parentheses': int(has_parentheses),
        'has_decimal': int(has_decimal),
        'has_comma_separated': int(has_comma_separated),
        'is_upper': int(is_upper),
        'is_title': int(is_title),
        'contains_upper': int(contains_upper),
        'word_count': word_count,
        'digit_ratio': digit_ratio,
        'unique_ratio': unique_ratio,
    }

def extract_layout_features(bbox, image_width=1000, image_height=1000):
    """
    Extract layout features from a bounding box.
    
    Args:
        bbox: Dict with x, y, width, height (pixel coordinates)
        image_width: Reference image width for normalization
        image_height: Reference image height for normalization
    
    Returns:
        Dict of normalized layout features
    """
    if bbox is None:
        return {
            'x_center_norm': 0.5,
            'y_center_norm': 0.5,
            'width_norm': 0.1,
            'height_norm': 0.1,
            'area_norm': 0.01,
            'aspect_ratio': 1.0,
            'x_min': 0,
            'y_min': 0,
            'x_max': 1,
            'y_max': 1,
        }
    
    x = float(bbox.get('x', 0))
    y = float(bbox.get('y', 0))
    w = float(bbox.get('width', 0))
    h = float(bbox.get('height', 0))
    
    # Normalize by image dimensions
    x_norm = x / image_width
    y_norm = y / image_height
    w_norm = w / image_width
    h_norm = h / image_height
    
    # Center coordinates
    x_center = x_norm + w_norm / 2
    y_center = y_norm + h_norm / 2
    
    # Area and aspect ratio
    area = w_norm * h_norm
    aspect_ratio = w_norm / (h_norm + 1e-6)
    
    return {
        'x_center_norm': x_center,
        'y_center_norm': y_center,
        'width_norm': w_norm,
        'height_norm': h_norm,
        'area_norm': area,
        'aspect_ratio': aspect_ratio,
        'x_min': x_norm,
        'y_min': y_norm,
        'x_max': x_norm + w_norm,
        'y_max': y_norm + h_norm,
    }

def extract_text_density(text, bbox):
    """Calculate text density (characters per unit area)."""
    if not text or not bbox:
        return 0.0
    
    text_len = len(str(text).strip())
    if text_len == 0:
        return 0.0
    
    w = float(bbox.get('width', 1))
    h = float(bbox.get('height', 1))
    area = w * h
    if area < 1:
        return 0.0
    
    return text_len / area

def extract_neighbor_context(texts, positions, idx, window=1):
    """
    Extract neighbor context features.
    
    Args:
        texts: List of text strings
        positions: List of y-coordinates (top position)
        idx: Index of current text
        window: Number of neighbors to consider on each side
    
    Returns:
        Dict with text above/below and their features
    """
    if len(texts) == 0 or idx >= len(texts):
        return {'above_text': '', 'below_text': '', 'has_above': 0, 'has_below': 0}
    
    current_y = positions[idx] if idx < len(positions) else 0
    
    # Find text above (with smaller y)
    above_texts = []
    above_indices = [i for i, y in enumerate(positions) if y < current_y and i != idx]
    above_indices.sort(key=lambda i: positions[i], reverse=True)  # closest first
    
    below_texts = []
    below_indices = [i for i, y in enumerate(positions) if y > current_y and i != idx]
    below_indices.sort(key=lambda i: positions[i])  # closest first
    
    # Get immediate neighbors
    above_text = ''
    if above_indices:
        above_text = texts[above_indices[0]]
    
    below_text = ''
    if below_indices:
        below_text = texts[below_indices[0]]
    
    return {
        'above_text': above_text,
        'below_text': below_text,
        'has_above': int(len(above_indices) > 0),
        'has_below': int(len(below_indices) > 0),
        'num_above': len(above_indices),
        'num_below': len(below_indices),
        # Features from above text
        'above_has_mrp': int('mrp' in above_text.lower()),
        'above_has_price': int('₹' in above_text or 'rs' in above_text.lower()),
        'above_has_date': int(any(w in above_text.lower() for w in ['date', 'exp', 'mfg'])),
        'above_has_weight': int(any(w in above_text.lower() for w in ['g', 'kg', 'ml', 'net'])),
        # Features from below text
        'below_has_mrp': int('mrp' in below_text.lower()),
        'below_has_price': int('₹' in below_text or 'rs' in below_text.lower()),
        'below_has_date': int(any(w in below_text.lower() for w in ['date', 'exp', 'mfg'])),
        'below_has_weight': int(any(w in below_text.lower() for w in ['g', 'kg', 'ml', 'net'])),
    }

def extract_all_features(df):
    """
    Extract all features from the dataset.
    
    Returns:
        DataFrame with all features
    """
    features = []
    y = []
    texts = df['text'].tolist()
    positions = []
    
    # First pass: collect positions for neighbor context
    for idx, row in df.iterrows():
        bbox = row.get('bbox')
        if bbox:
            positions.append(float(bbox.get('y', 0)))
        else:
            positions.append(float(idx * 10))
    
    for idx, row in df.iterrows():
        text = row.get('text', '')
        label = row.get('label', '')
        bbox = row.get('bbox')
        ocr_confidence = row.get('confidence', 0.85)
        
        # Extract text features
        text_features = extract_text_features(text)
        
        # Extract layout features
        layout_features = extract_layout_features(bbox)
        
        # Extract text density
        density = extract_text_density(text, bbox)
        
        # Extract neighbor context
        neighbor_features = extract_neighbor_context(texts, positions, idx)
        
        # Combine all features
        all_features = {
            **text_features,
            **layout_features,
            'text_density': density,
            'ocr_confidence': ocr_confidence,
            **neighbor_features,
        }
        
        features.append(all_features)
        y.append(label)
    
    return pd.DataFrame(features), np.array(y)

# -----------------------------------------------------------------------------
# Training
# -----------------------------------------------------------------------------
def train_models(X_train, X_test, y_train, y_test):
    """Train RandomForest and XGBoost models."""
    # Scale features for XGBoost
    scaler = StandardScaler()
    X_train_scaled = scaler.fit_transform(X_train)
    X_test_scaled = scaler.transform(X_test)
    
    models = {}
    results = {}
    
    # 1. Random Forest
    print("\n" + "="*60)
    print("Training RandomForestClassifier...")
    print("="*60)
    
    rf = RandomForestClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=MAX_DEPTH,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        class_weight='balanced'
    )
    
    # Stratified cross-validation
    skf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    cv_scores = cross_val_score(rf, X_train, y_train, cv=skf, scoring='accuracy')
    print(f"CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
    
    rf.fit(X_train, y_train)
    y_pred_rf = rf.predict(X_test)
    acc_rf = accuracy_score(y_test, y_pred_rf)
    print(f"Test Accuracy: {acc_rf:.4f}")
    
    models['random_forest'] = rf
    results['random_forest'] = {
        'accuracy': acc_rf,
        'cv_mean': cv_scores.mean(),
        'cv_std': cv_scores.std(),
        'predictions': y_pred_rf
    }
    
    # 2. XGBoost
    print("\n" + "="*60)
    print("Training XGBoost Classifier...")
    print("="*60)
    
    xgb_model = xgb.XGBClassifier(
        n_estimators=N_ESTIMATORS,
        max_depth=8,
        learning_rate=0.1,
        random_state=RANDOM_STATE,
        use_label_encoder=False,
        eval_metric='mlogloss',
        subsample=0.8,
        colsample_bytree=0.8
    )
    
    skf = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_STATE)
    cv_scores = cross_val_score(xgb_model, X_train_scaled, y_train, cv=skf, scoring='accuracy')
    print(f"CV Accuracy: {cv_scores.mean():.4f} (+/- {cv_scores.std():.4f})")
    
    xgb_model.fit(X_train_scaled, y_train)
    y_pred_xgb = xgb_model.predict(X_test_scaled)
    acc_xgb = accuracy_score(y_test, y_pred_xgb)
    print(f"Test Accuracy: {acc_xgb:.4f}")
    
    models['xgboost'] = xgb_model
    results['xgboost'] = {
        'accuracy': acc_xgb,
        'cv_mean': cv_scores.mean(),
        'cv_std': cv_scores.std(),
        'predictions': y_pred_xgb
    }
    
    return models, results, scaler

# -----------------------------------------------------------------------------
# Feature Importance Analysis
# -----------------------------------------------------------------------------
def analyze_feature_importance(model, feature_names, model_name):
    """Analyze and display feature importance."""
    if hasattr(model, 'feature_importances_'):
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        print(f"\n--- {model_name} Feature Importance ---")
        print("Top 15 Features:")
        for i in range(min(15, len(feature_names))):
            idx = indices[i]
            print(f"  {i+1:2d}. {feature_names[idx]:30s} {importances[idx]:.4f}")
        
        # Return top features for comparison
        top_features = [(feature_names[idx], importances[idx]) for idx in indices[:20]]
        return top_features
    return []

# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    # Load dataset
    print("Loading dataset...")
    df = pd.read_csv('training/dataset_complete_filled.csv')
    print(f"Loaded {len(df)} samples")
    
    # Strip whitespace
    if 'text' in df.columns:
        df['text'] = df['text'].str.strip()
    if 'label' in df.columns:
        df['label'] = df['label'].str.strip()
    
    # Drop rows with empty labels
    df = df[df['label'].notna()]
    df = df[df['label'] != '']
    print(f"After cleaning: {len(df)} samples")
    
    # Encode labels
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(df['label'])
    print(f"Classes: {label_encoder.classes_}")
    
    # Extract features
    print("\nExtracting features...")
    X_df, y_raw = extract_all_features(df)
    print(f"Extracted {len(X_df.columns)} features")
    print(f"Feature columns: {list(X_df.columns)}")
    
    # Convert to numpy
    X = X_df.values
    y = y_encoded
    
    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=TEST_SIZE, random_state=RANDOM_STATE, stratify=y
    )
    print(f"Train: {len(X_train)}, Test: {len(X_test)}")
    
    # Train models
    models, results, scaler = train_models(X_train, X_test, y_train, y_test)
    
    # Feature importance
    feature_names = X_df.columns.tolist()
    for name, model in models.items():
        analyze_feature_importance(model, feature_names, name)
    
    # Save models and artifacts
    print("\n" + "="*60)
    print("Saving models and artifacts...")
    print("="*60)
    
    # Save RandomForest
    joblib.dump(models['random_forest'], 'models/random_forest_model.joblib')
    print("✓ Saved RandomForest model")
    
    # Save XGBoost
    joblib.dump(models['xgboost'], 'models/xgboost_model.joblib')
    print("✓ Saved XGBoost model")
    
    # Save label encoder
    joblib.dump(label_encoder, 'models/label_encoder.joblib')
    print("✓ Saved label encoder")
    
    # Save scaler
    joblib.dump(scaler, 'models/feature_scaler.joblib')
    print("✓ Saved feature scaler")
    
    # Save feature names
    with open('models/feature_names.json', 'w') as f:
        json.dump(feature_names, f, indent=2)
    print("✓ Saved feature names")
    
    # Save comparison report
    report = {
        'random_forest': {
            'accuracy': float(results['random_forest']['accuracy']),
            'cv_mean': float(results['random_forest']['cv_mean']),
            'cv_std': float(results['random_forest']['cv_std']),
        },
        'xgboost': {
            'accuracy': float(results['xgboost']['accuracy']),
            'cv_mean': float(results['xgboost']['cv_mean']),
            'cv_std': float(results['xgboost']['cv_std']),
        },
        'n_samples': len(df),
        'n_features': len(feature_names),
        'classes': label_encoder.classes_.tolist(),
        'feature_names': feature_names[:50],  # Top 50 for report
    }
    
    with open('models/comparison_report.json', 'w') as f:
        json.dump(report, f, indent=2)
    print("✓ Saved comparison report")
    
    # Print summary
    print("\n" + "="*60)
    print("TRAINING COMPLETE")
    print("="*60)
    print(f"\nRandomForest Test Accuracy: {results['random_forest']['accuracy']:.4f}")
    print(f"XGBoost Test Accuracy:     {results['xgboost']['accuracy']:.4f}")
    print(f"\nBest model: {'XGBoost' if results['xgboost']['accuracy'] > results['random_forest']['accuracy'] else 'RandomForest'}")
    print("\nModels saved to ./models/")

if __name__ == '__main__':
    main()
