import base64
import json
import requests
from PIL import Image
from io import BytesIO

# Load and resize image
image_path = "/app/images/image11_2.jpg"
img = Image.open(image_path).convert("RGB")
img.thumbnail((800, 800))  # reduce size for faster test
buffer = BytesIO()
img.save(buffer, format="JPEG", quality=80)
img_b64 = base64.b64encode(buffer.getvalue()).decode()

prompt = """Extract MRP, USP, net quantity, product name, manufacturer, manufacturing date, expiry date, consumer care. Return ONLY JSON with keys: mrp, usp, net_quantity, product_name, manufacturer, manufacturing_date, expiry_date, consumer_care. Use empty strings for missing."""

payload = {
    "model": "qwen3-vl:8b",
    "prompt": prompt,
    "images": [img_b64],
    "stream": False,
    "options": {"num_ctx": 8192, "temperature": 0.0}
}

print("Sending request to Qwen...")
try:
    response = requests.post("http://ollama:11434/api/generate", json=payload, timeout=120)
    print("Status:", response.status_code)
    print("Response:")
    print(response.text)
except Exception as e:
    print(f"Error: {e}")
