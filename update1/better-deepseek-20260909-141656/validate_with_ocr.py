#!/usr/bin/env python3
"""
MetrIQ - OCR Validation Script
SIH 2026 Demo - Updated Sep 2026

Tests the ML model on real OCR output, including layout and neighbor context.
Validates both feature extraction and prediction accuracy.
"""

import os
import json
import time
import numpy as np
import pandas as pd
from typing import List, Dict, Any
import argparse
from collections import defaultdict
import warnings
warnings.filterwarnings('ignore')

# Import the extractor and inference modules
try:
    from ml_extractor import MetrIQExtractor
    from inference import InferenceEngine
except ImportError:
    print("⚠️ Could not import ml_extractor. Please ensure models are trained.")
    sys.exit(1)

class OCRValidator:
    """Validates ML model performance on real OCR data."""
    
    def __init__(self, model_path: str = 'models/xgboost_model.joblib'):
        self.extractor = MetrIQExtractor(model_path=model_path)
        self.engine = InferenceEngine(model_path=model_path)
        self.engine.warmup()
        self.results = {
            'per_box': [],
            'per_image': [],
            'summary': {}
        }
    
    def validate_boxes(self, boxes: List[Dict], ground_truth: Dict[str, str]) -> Dict[str, Any]:
        """
        Validate predictions for a single image.
        
        Args:
            boxes: List of OCR boxes with 'text', 'bbox', 'confidence'
            ground_truth: Dict mapping field names to expected values
        
        Returns:
            Dict with prediction results
        """
        # Run inference
        result = self.engine.infer(boxes)
        predictions = result['declarations']
        
        # Compare with ground truth
        matches = {}
        total_fields = len(ground_truth)
        correct = 0
        
        for field, expected in ground_truth.items():
            predicted = predictions.get(field)
            
            # Compare (case-insensitive)
            if expected and predicted:
                match = expected.lower().strip() == predicted.lower().strip()
            else:
                match = (expected is None and predicted is None)
            
            matches[field] = {
                'expected': expected,
                'predicted': predicted,
                'match': match
            }
            
            if match:
                correct += 1
        
        accuracy = correct / total_fields if total_fields > 0 else 0
        
        return {
            'accuracy': accuracy,
            'correct': correct,
            'total': total_fields,
            'matches': matches,
            'inference_time_ms': result['metadata'].get('inference_time_ms', 0),
            'boxes_processed': len(boxes),
        }
    
    def validate_dataset(self, dataset_path: str, ground_truth_path: str) -> Dict[str, Any]:
        """
        Validate on a full dataset.
        
        Args:
            dataset_path: Path to CSV with OCR boxes (text, bbox, confidence, image_id)
            ground_truth_path: Path to CSV with ground truth labels
        """
        # Load data
        df = pd.read_csv(dataset_path)
        gt = pd.read_csv(ground_truth_path)
        
        # Group by image
        image_results = []
        per_field_stats = defaultdict(lambda: {'correct': 0, 'total': 0})
        
        for image_id in gt['image_id'].unique():
            image_boxes = df[df['image_id'] == image_id].to_dict('records')
            image_truth = gt[gt['image_id'] == image_id].iloc[0].to_dict()
            
            # Remove image_id from truth
            image_truth.pop('image_id', None)
            
            # Validate
            result = self.validate_boxes(image_boxes, image_truth)
            image_results.append({
                'image_id': image_id,
                **result
            })
            
            # Update field stats
            for field, match_info in result['matches'].items():
                per_field_stats[field]['total'] += 1
                if match_info['match']:
                    per_field_stats[field]['correct'] += 1
        
        # Compute overall metrics
        total_accuracy = np.mean([r['accuracy'] for r in image_results])
        avg_time = np.mean([r['inference_time_ms'] for r in image_results])
        
        field_accuracies = {
            field: stats['correct'] / stats['total'] if stats['total'] > 0 else 0
            for field, stats in per_field_stats.items()
        }
        
        summary = {
            'total_images': len(image_results),
            'overall_accuracy': total_accuracy,
            'avg_inference_time_ms': avg_time,
            'field_accuracies': field_accuracies,
            'per_image': image_results,
        }
        
        self.results['summary'] = summary
        self.results['per_image'] = image_results
        
        return summary
    
    def validate_custom(self, boxes: List[Dict]) -> Dict[str, Any]:
        """
        Validate on custom input with predictions.
        
        Shows confidence scores and feature contributions.
        """
        # Predict
        predicted_boxes = self.extractor.predict_boxes(boxes)
        
        # Analyze each box
        analysis = []
        for box in predicted_boxes:
            analysis.append({
                'text': box.get('text', ''),
                'predicted_label': box.get('predicted_label', ''),
                'confidence': box.get('confidence', 0.0),
                'bbox': box.get('bbox', {}),
            })
        
        return {
            'analysis': analysis,
            'declarations': self.extractor.extract_declarations(boxes),
            'total_boxes': len(boxes),
        }
    
    def print_summary(self):
        """Print a formatted summary of validation results."""
        summary = self.results['summary']
        
        print("\n" + "="*60)
        print("VALIDATION SUMMARY")
        print("="*60)
        
        print(f"\n📊 Total Images: {summary.get('total_images', 0)}")
        print(f"🎯 Overall Accuracy: {summary.get('overall_accuracy', 0):.2%}")
        print(f"⚡ Avg Inference Time: {summary.get('avg_inference_time_ms', 0):.2f}ms")
        
        print("\n📋 Per-Field Accuracy:")
        field_acc = summary.get('field_accuracies', {})
        for field, acc in sorted(field_acc.items(), key=lambda x: x[1], reverse=True):
            print(f"  {field:20s} {acc:.2%}")
        
        print("\n✅ Validation complete!")

# -----------------------------------------------------------------------------
# Command Line Interface
# -----------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='Validate ML model on OCR data')
    parser.add_argument('--dataset', help='Path to dataset CSV')
    parser.add_argument('--ground-truth', help='Path to ground truth CSV')
    parser.add_argument('--boxes', help='JSON file with boxes to validate')
    parser.add_argument('--model', default='models/xgboost_model.joblib', help='Model path')
    parser.add_argument('--output', help='Output file for results')
    
    args = parser.parse_args()
    
    validator = OCRValidator(model_path=args.model)
    
    if args.dataset and args.ground_truth:
        print(f"📊 Validating on dataset: {args.dataset}")
        summary = validator.validate_dataset(args.dataset, args.ground_truth)
        validator.print_summary()
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(validator.results, f, indent=2)
            print(f"\n📁 Results saved to {args.output}")
    
    elif args.boxes:
        print(f"📦 Validating on custom boxes: {args.boxes}")
        with open(args.boxes, 'r') as f:
            boxes = json.load(f)
        
        result = validator.validate_custom(boxes)
        print("\n📋 Analysis:")
        for item in result['analysis']:
            conf = item['confidence']
            conf_str = f"{conf:.2%}" if conf > 0 else "N/A"
            print(f"  '{item['text'][:30]}' → {item['predicted_label']} ({conf_str})")
        
        print("\n📦 Declarations:")
        for field, value in result['declarations'].items():
            print(f"  {field}: {value}")
        
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2)
            print(f"\n📁 Results saved to {args.output}")
    
    else:
        print("⚠️ Please provide either --dataset and --ground-truth, or --boxes")
        parser.print_help()

if __name__ == '__main__':
    main()
