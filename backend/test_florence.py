# test_florence.py
from app.services.vision_extractor import get_vision_extractor

print("Loading Florence...")
fl = get_vision_extractor()
print("Available:", fl.available)
if fl.available:
    print("✅ Florence is ready!")
else:
    print("❌ Florence failed to load.")