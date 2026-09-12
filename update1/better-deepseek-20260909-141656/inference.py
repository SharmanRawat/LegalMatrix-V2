#!/usr/bin/env python3
"""
MetrIQ - Inference Script
SIH 2026 Demo - Updated Sep 2026

Lightweight inference script for real-time declaration extraction.
Optimized for <100ms inference per box.
"""

import sys
import json
import time
from typing import List, Dict, Any, Optional
import numpy as np
import joblib
import os

# Try importing the full extractor
try:
    from ml_extractor import MetrIQExtractor, extract_from_ocr_results
except ImportError:
    # Standalone mode: define minimal extractor
    from inference_standalone import MetrIQExtractor, extract_from_ocr_results

class InferenceEngine:
    """Fast inference engine with pre-loaded models."""
    
    def __init__(self, model_path: str = 'models/xgboost_model.joblib'):
        self.extractor = MetrIQExtractor(model_path=model_path)
        self._warmup_complete = False
        
    def warmup(self):
        """Run a warmup inference to ensure models are loaded."""
        if self._warmup_complete:
            return
        
        sample = [{'text': 'MRP: ₹100', 'bbox': {'x': 100, 'y': 500, 'width': 100, 'height': 30}, 'confidence': 0.95}]
        _ = self.extractor.predict_boxes(sample)
        self._warmup_complete = True
        print("✓ Inference engine warmed up")
    
    def infer(self, boxes: List[Dict]) -> Dict[str, Any]:
        """
        Run inference on a batch of text boxes.
        
        Args:
            boxes: List of dicts with 'text', 'bbox', 'confidence' keys
        
        Returns:
            Dict with declarations and metadata
        """
        start_time = time.time()
        
        result = self.extractor.extract_complete(boxes)
        
        elapsed = (time.time() - start_time) * 1000  # ms
        result['metadata']['inference_time_ms'] = elapsed
        
        return result
    
    def infer_single(self, box: Dict) -> Dict:
        """Run inference on a single text box."""
        return self.infer([box])['declarations']

# -----------------------------------------------------------------------------
# Fast Path - Direct Function
# -----------------------------------------------------------------------------

_engine = None

def get_engine(model_path: str = 'models/xgboost_model.joblib') -> InferenceEngine:
    """Get or create the inference engine singleton."""
    global _engine
    if _engine is None:
        _engine = InferenceEngine(model_path=model_path)
        _engine.warmup()
    return _engine

def fast_infer(boxes: List[Dict], model_path: str = 'models/xgboost_model.joblib') -> Dict[str, Any]:
    """
    Fast inference entry point.
    
    Example:
        >>> result = fast_infer([{'text': 'MRP: ₹99', 'bbox': {...}, 'confidence': 0.95}])
        >>> print(result['declarations'])
    """
    engine = get_engine(model_path)
    return engine.infer(boxes)

# -----------------------------------------------------------------------------
# CLI Entry Point
# -----------------------------------------------------------------------------

def main():
    """CLI entry point for inference."""
    if len(sys.argv) < 2:
        print("Usage: python inference.py <input_file.json> [output_file.json]")
        print("  input_file.json: JSON file with OCR results")
        print("  output_file.json: Optional output file (default: stdout)")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    # Load input
    with open(input_file, 'r') as f:
        data = json.load(f)
    
    # Handle different input formats
    if isinstance(data, list):
        boxes = data
    elif isinstance(data, dict) and 'boxes' in data:
        boxes = data['boxes']
    else:
        boxes = [data]
    
    # Run inference
    engine = get_engine()
    result = engine.infer(boxes)
    
    # Add timing
    result['metadata']['timestamp'] = time.time()
    
    # Output
    if output_file:
        with open(output_file, 'w') as f:
            json.dump(result, f, indent=2)
        print(f"✓ Results saved to {output_file}")
    else:
        print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
