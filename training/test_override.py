# test_override.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.services.ml_extractor import ml_extractor

# Create a dummy OCR result (one box)
dummy_ocr = [{"text": "₹ 75.00", "bbox": [[0,0],[0,0],[0,0],[0,0]], "center": {"x":0, "y":0}, "confidence": 0.9}]

result = ml_extractor.extract_all(dummy_ocr, 1000, 800)
print("Result:")
for field, item in result.items():
    print(f"  {field}: {item.get('text') if item else None}")
