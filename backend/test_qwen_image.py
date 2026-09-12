import base64
import json
import requests
from PIL import Image
from io import BytesIO

image_path = "/home/destructo_49/SIH2026/training/images/image40_2.jpg"  # change this

# Resize to 512px max to drastically reduce tokens
img = Image.open(image_path).convert("RGB")
max_size = 512
img.thumbnail((max_size, max_size))
buffer = BytesIO()
img.save(buffer, format="JPEG", quality=80)
img_b64 = base64.b64encode(buffer.getvalue()).decode()

prompt = """Extract MRP, USP, net quantity, product name, manufacturer, manufacturing date, expiry date, consumer care from this product label. Return ONLY JSON with keys: mrp, usp, net_quantity, product_name, manufacturer, manufacturing_date, expiry_date, consumer_care. Use empty strings for missing fields."""

payload = {
    "model": "qwen3-vl:4b",
    "prompt": prompt,
    "images": [img_b64],
    "stream": False,
    "options": {
        "num_ctx": 8192
    }
}

resp = requests.post("http://localhost:11434/api/generate", json=payload)
print("Status:", resp.status_code)
print("Raw response:")
print(resp.text)