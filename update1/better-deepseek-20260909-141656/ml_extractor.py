#!/usr/bin/env python3
"""
MetrIQ - ML Extractor with Layout Features
SIH 2026 Demo - Updated Sep 2026

This module extracts and classifies text boxes from product labels
using a trained ML model with text, layout, and contextual features.
"""

import numpy as np
import pandas as pd
import json
import joblib
import os
from typing import Dict, List, Any, Optional
import warnings
warnings.filterwarnings('ignore')

class MetrIQExtractor:
    """Main extractor class for detecting declarations from OCR text boxes."""
    
    def __init__(self, model_path: str = 'models/xgboost_model.joblib'):
        """
        Initialize the extractor with trained models.
        
        Prefers XGBoost by default, falls back to RandomForest if available.
        """
        self.model_path = model_path
        self.model = None
        self.label_encoder = None
        self.scaler = None
        self.feature_names = None
        
        # Try loading XGBoost first, fallback to RandomForest
        self._load_models()
        
        # Define field groups for post-processing
        self.field_groups = {
            'mrp': ['mrp', 'price'],
            'usp': ['usp', 'selling_price', 'special_price'],
            'net_quantity': ['net_quantity', 'net_weight', 'weight', 'quantity'],
            'product_name': ['product_name', 'product', 'name', 'brand'],
            'manufacturer': ['manufacturer', 'mfg', 'made_by'],
            'manufacturing_date': ['manufacturing_date', 'mfg_date', 'mfd'],
            'expiry_date': ['expiry_date', 'exp_date', 'exp', 'best_before'],
            'consumer_care': ['consumer_care', 'contact', 'phone', 'email'],
        }
        
        # Confidence threshold for accepting predictions
        self.confidence_threshold = 0.4
        
    def _load_models(self):
        """Load models from disk."""
        model_dir = os.path.dirname(self.model_path)
        
        # Try loading XGBoost first
        try:
            self.model = joblib.load(self.model_path)
            print(f"✓ Loaded model: {os.path.basename(self.model_path)}")
        except Exception as e:
            print(f"⚠️ Could not load {self.model_path}, trying RandomForest...")
            try:
                rf_path = os.path.join(model_dir, 'random_forest_model.joblib')
                self.model = joblib.load(rf_path)
                print(f"✓ Loaded RandomForest model: {rf_path}")
            except Exception as e2:
                raise RuntimeError(f"Could not load any model: {e}")
        
        # Load label encoder
        label_path = os.path.join(model_dir, 'label_encoder.joblib')
        self.label_encoder = joblib.load(label_path)
        print(f"✓ Loaded label encoder with {len(self.label_encoder.classes_)} classes")
        
        # Load scaler
        scaler_path = os.path.join(model_dir, 'feature_scaler.joblib')
        self.scaler = joblib.load(scaler_path)
        print("✓ Loaded feature scaler")
        
        # Load feature names
        features_path = os.path.join(model_dir, 'feature_names.json')
        with open(features_path, 'r') as f:
            self.feature_names = json.load(f)
        print(f"✓ Loaded {len(self.feature_names)} feature names")
    
    # -------------------------------------------------------------------------
    # Feature Extraction Methods (mirrors training)
    # -------------------------------------------------------------------------
    
    def _extract_text_features(self, text: str) -> Dict[str, Any]:
        """Extract text-based features from a string."""
        if not text or not isinstance(text, str):
            text = ''
        
        text = str(text).strip()
        length = len(text)
        digit_count = sum(c.isdigit() for c in text)
        alpha_count = sum(c.isalpha() for c in text)
        space_count = sum(c.isspace() for c in text)
        special_count = length - digit_count - alpha_count - space_count
        
        text_lower = text.lower()
        
        return {
            'length': length,
            'digit_count': digit_count,
            'alpha_count': alpha_count,
            'space_count': space_count,
            'special_count': special_count,
            'has_rupee': int('₹' in text or 'rs' in text_lower),
            'has_dollar': int('$' in text),
            'has_percent': int('%' in text),
            'has_mrp': int('mrp' in text_lower),
            'has_price': int('price' in text_lower or '₹' in text),
            'has_date': int(any(w in text_lower for w in ['date', 'exp', 'mfg', 'man', 'pack', 'best before', 'use by'])),
            'has_weight': int(any(w in text_lower for w in ['g', 'kg', 'ml', 'l', 'gm', 'mg', 'net', 'wt', 'weight'])),
            'has_contact': int(any(w in text_lower for w in ['phone', 'contact', 'call', 'email', 'www', 'http'])),
            'has_product': int(any(w in text_lower for w in ['product', 'name', 'brand', 'flavour', 'flavor'])),
            'has_manufacturer': int(any(w in text_lower for w in ['manufacturer', 'mfg', 'manufactured', 'made by', 'produced by'])),
            'has_colon': int(':' in text),
            'has_slash': int('/' in text),
            'has_dash': int('-' in text),
            'has_parentheses': int('(' in text and ')' in text),
            'has_decimal': int('.' in text and any(c.isdigit() for c in text)),
            'has_comma_separated': int(',' in text and any(c.isdigit() for c in text)),
            'is_upper': int(text.isupper()),
            'is_title': int(text.istitle()),
            'contains_upper': int(any(c.isupper() for c in text)),
            'word_count': len(text.split()),
            'digit_ratio': digit_count / length if length > 0 else 0,
            'unique_ratio': len(set(text)) / length if length > 0 else 0,
        }
    
    def _extract_layout_features(self, bbox: Dict, image_width: int = 1000, image_height: int = 1000) -> Dict[str, float]:
        """Extract normalized layout features from bounding box."""
        if not bbox:
            return {
                'x_center_norm': 0.5, 'y_center_norm': 0.5,
                'width_norm': 0.1, 'height_norm': 0.1,
                'area_norm': 0.01, 'aspect_ratio': 1.0,
                'x_min': 0, 'y_min': 0, 'x_max': 1, 'y_max': 1,
            }
        
        x = float(bbox.get('x', 0))
        y = float(bbox.get('y', 0))
        w = float(bbox.get('width', 0))
        h = float(bbox.get('height', 0))
        
        # Normalize
        x_norm = x / image_width
        y_norm = y / image_height
        w_norm = w / image_width
        h_norm = h / image_height
        
        return {
            'x_center_norm': x_norm + w_norm / 2,
            'y_center_norm': y_norm + h_norm / 2,
            'width_norm': w_norm,
            'height_norm': h_norm,
            'area_norm': w_norm * h_norm,
            'aspect_ratio': w_norm / (h_norm + 1e-6),
            'x_min': x_norm,
            'y_min': y_norm,
            'x_max': x_norm + w_norm,
            'y_max': y_norm + h_norm,
        }
    
    def _extract_text_density(self, text: str, bbox: Dict) -> float:
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
    
    def _extract_neighbor_context(self, boxes: List[Dict], idx: int, window: int = 1) -> Dict[str, Any]:
        """
        Extract features from neighboring text boxes.
        
        Args:
            boxes: List of boxes with 'text' and 'bbox' fields
            idx: Index of current box
            window: Number of neighbors to consider
        """
        if len(boxes) == 0 or idx >= len(boxes):
            return {
                'above_text': '', 'below_text': '',
                'has_above': 0, 'has_below': 0,
                'num_above': 0, 'num_below': 0,
                'above_has_mrp': 0, 'above_has_price': 0, 'above_has_date': 0, 'above_has_weight': 0,
                'below_has_mrp': 0, 'below_has_price': 0, 'below_has_date': 0, 'below_has_weight': 0,
            }
        
        current_box = boxes[idx]
        current_y = float(current_box.get('bbox', {}).get('y', 0))
        
        # Get positions of all boxes
        positions = [float(b.get('bbox', {}).get('y', i * 10)) for i, b in enumerate(boxes)]
        texts = [b.get('text', '') for b in boxes]
        
        # Find neighbors
        above_indices = [i for i, y in enumerate(positions) if y < current_y and i != idx]
        above_indices.sort(key=lambda i: positions[i], reverse=True)
        
        below_indices = [i for i, y in enumerate(positions) if y > current_y and i != idx]
        below_indices.sort(key=lambda i: positions[i])
        
        above_text = texts[above_indices[0]] if above_indices else ''
        below_text = texts[below_indices[0]] if below_indices else ''
        
        return {
            'above_text': above_text,
            'below_text': below_text,
            'has_above': int(len(above_indices) > 0),
            'has_below': int(len(below_indices) > 0),
            'num_above': len(above_indices),
            'num_below': len(below_indices),
            'above_has_mrp': int('mrp' in above_text.lower()),
            'above_has_price': int('₹' in above_text or 'rs' in above_text.lower()),
            'above_has_date': int(any(w in above_text.lower() for w in ['date', 'exp', 'mfg'])),
            'above_has_weight': int(any(w in above_text.lower() for w in ['g', 'kg', 'ml', 'net'])),
            'below_has_mrp': int('mrp' in below_text.lower()),
            'below_has_price': int('₹' in below_text or 'rs' in below_text.lower()),
            'below_has_date': int(any(w in below_text.lower() for w in ['date', 'exp', 'mfg'])),
            'below_has_weight': int(any(w in below_text.lower() for w in ['g', 'kg', 'ml', 'net'])),
        }
    
    def _extract_features_for_boxes(self, boxes: List[Dict]) -> np.ndarray:
        """
        Extract all features for a list of text boxes.
        
        Args:
            boxes: List of dicts with 'text', 'bbox', 'confidence' keys
        
        Returns:
            numpy array of features in the correct order for the model
        """
        feature_rows = []
        
        # Ensure all boxes have required fields
        for i, box in enumerate(boxes):
            text = box.get('text', '')
            bbox = box.get('bbox', {})
            confidence = box.get('confidence', 0.85)
            
            # Extract features
            text_feat = self._extract_text_features(text)
            layout_feat = self._extract_layout_features(bbox)
            density = self._extract_text_density(text, bbox)
            neighbor_feat = self._extract_neighbor_context(boxes, i)
            
            # Combine all features
            row = {
                **text_feat,
                **layout_feat,
                'text_density': density,
                'ocr_confidence': confidence,
                **neighbor_feat,
            }
            
            # Ensure all expected features are present
            feature_vector = []
            for name in self.feature_names:
                feature_vector.append(row.get(name, 0.0))
            
            feature_rows.append(feature_vector)
        
        # Convert to numpy array and scale
        X = np.array(feature_rows, dtype=np.float32)
        X_scaled = self.scaler.transform(X)
        return X_scaled
    
    # -------------------------------------------------------------------------
    # Prediction Methods
    # -------------------------------------------------------------------------
    
    def predict_boxes(self, boxes: List[Dict]) -> List[Dict]:
        """
        Predict labels for a list of text boxes.
        
        Args:
            boxes: List of dicts with 'text', 'bbox', 'confidence' keys
        
        Returns:
            Same list with 'predicted_label' and 'confidence' added to each box
        """
        if not boxes:
            return boxes
        
        # Extract features
        X = self._extract_features_for_boxes(boxes)
        
        # Get predictions
        pred_proba = self.model.predict_proba(X)
        pred_indices = np.argmax(pred_proba, axis=1)
        pred_labels = self.label_encoder.inverse_transform(pred_indices)
        confidences = np.max(pred_proba, axis=1)
        
        # Add predictions to boxes
        for i, box in enumerate(boxes):
            box['predicted_label'] = pred_labels[i]
            box['confidence'] = float(confidences[i])
        
        return boxes
    
    def extract_declarations(self, boxes: List[Dict]) -> Dict[str, Any]:
        """
        Extract all declarations from a list of text boxes.
        
        Returns a dict with one field per declaration type.
        """
        if not boxes:
            return {field: None for field in self.field_groups.keys()}
        
        # Predict labels
        boxes = self.predict_boxes(boxes)
        
        # Group predictions by field
        field_values = {field: [] for field in self.field_groups.keys()}
        
        for box in boxes:
            label = box.get('predicted_label', '')
            confidence = box.get('confidence', 0.0)
            text = box.get('text', '')
            
            if label in field_values:
                field_values[label].append({
                    'text': text,
                    'confidence': confidence,
                    'bbox': box.get('bbox', {}),
                })
        
        # Select best candidate for each field
        result = {}
        for field, candidates in field_values.items():
            if not candidates:
                result[field] = None
                continue
            
            # Sort by confidence descending, take highest
            candidates.sort(key=lambda x: x['confidence'], reverse=True)
            
            # Only accept if confidence > threshold
            best = candidates[0]
            if best['confidence'] >= self.confidence_threshold:
                result[field] = best['text']
            else:
                result[field] = None
        
        return result
    
    def extract_complete(self, boxes: List[Dict]) -> Dict[str, Any]:
        """
        Full extraction with metadata and confidence scores.
        """
        if not boxes:
            return {
                'declarations': {},
                'metadata': {'total_boxes': 0, 'fields_detected': 0}
            }
        
        # Predict and extract
        boxes = self.predict_boxes(boxes)
        declarations = self.extract_declarations(boxes)
        
        # Count detected fields
        detected = sum(1 for v in declarations.values() if v is not None)
        
        return {
            'declarations': declarations,
            'metadata': {
                'total_boxes': len(boxes),
                'fields_detected': detected,
                'total_fields': len(self.field_groups),
                'completeness': detected / len(self.field_groups) if self.field_groups else 0,
                'boxes_with_predictions': boxes,
            }
        }

# -----------------------------------------------------------------------------
# Convenience Functions
# -----------------------------------------------------------------------------

def load_extractor(model_path: str = 'models/xgboost_model.joblib') -> MetrIQExtractor:
    """Load the extractor with the specified model."""
    return MetrIQExtractor(model_path=model_path)

def extract_from_ocr_results(ocr_data: List[Dict], model_path: str = 'models/xgboost_model.joblib') -> Dict[str, Any]:
    """
    Extract declarations from OCR results.
    
    Args:
        ocr_data: List of dicts with 'text', 'bbox', 'confidence' keys
        model_path: Path to the trained model
    
    Returns:
        Dict with extracted declarations and metadata
    """
    extractor = load_extractor(model_path)
    return extractor.extract_complete(ocr_data)

# -----------------------------------------------------------------------------
# Demo / Quick Test
# -----------------------------------------------------------------------------
if __name__ == '__main__':
    print("="*60)
    print("MetrIQ Extractor - Quick Test")
    print("="*60)
    
    # Sample OCR data
    sample_boxes = [
        {'text': 'MRP: ₹99.00', 'bbox': {'x': 100, 'y': 500, 'width': 150, 'height': 30}, 'confidence': 0.95},
        {'text': 'Product Name: Choco Bliss', 'bbox': {'x': 100, 'y': 50, 'width': 200, 'height': 30}, 'confidence': 0.98},
        {'text': 'Net Wt: 200g', 'bbox': {'x': 100, 'y': 150, 'width': 120, 'height': 25}, 'confidence': 0.92},
        {'text': 'Mfg Date: 01/09/2026', 'bbox': {'x': 100, 'y': 300, 'width': 160, 'height': 25}, 'confidence': 0.90},
        {'text': 'Exp Date: 01/09/2027', 'bbox': {'x': 100, 'y': 340, 'width': 160, 'height': 25}, 'confidence': 0.88},
        {'text': 'Phone: 1800-123-4567', 'bbox': {'x': 100, 'y': 600, 'width': 160, 'height': 25}, 'confidence': 0.85},
    ]
    
    extractor = load_extractor()
    result = extractor.extract_complete(sample_boxes)
    
    print("\nExtracted Declarations:")
    for field, value in result['declarations'].items():
        print(f"  {field}: {value}")
    
    print(f"\nMetadata:")
    for key, value in result['metadata'].items():
        if key != 'boxes_with_predictions':
            print(f"  {key}: {value}")
