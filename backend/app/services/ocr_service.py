import base64
import hashlib
import json
import logging
import os
import re
import subprocess
import time
from typing import Dict, Optional
import httpx
from PIL import Image, ImageOps
from io import BytesIO

logger = logging.getLogger(__name__)

GARBAGE_PATTERN = re.compile(r'^[?\s]+$')


class OCRService:
    EXPECTED_KEYS = [
        "mrp", "usp", "net_quantity", "product_name",
        "manufacturer", "manufacturing_date", "expiry_date", "consumer_care",
        "dimensions", "edible"
    ]

    def __init__(self):
        self.model = os.getenv("QWN_MODEL", "qwen2.5vl:7b")
        self.ollama_url = os.getenv(
            "OLLAMA_HOST", "http://localhost:11434"
        ).rstrip("/") + "/api/chat"
        self.max_image_size = int(os.getenv("OCR_MAX_IMAGE_SIZE", "896"))
        self.max_retries = 3
        self.timeout = float(os.getenv("OCR_TIMEOUT_SECONDS", "180"))
        self.localization = os.getenv("VLM_LOCALIZATION", "1") == "1"

    def _build_prompt(self) -> str:
        """The exact extraction prompt used for every image.

        Kept as a single method so the report can fingerprint it (SHA-256) for
        chain-of-custody: a changed prompt invalidates old evidence."""
        prompt = (
            "Extract the following fields from this product label image: "
            "mrp, usp, net_quantity, product_name, manufacturer, "
            "manufacturing_date, expiry_date, consumer_care, dimensions, "
            "edible.\n"
            "Respond ONLY with a JSON object. No explanation, no markdown, "
            "no code fences.\n"
            "Use empty strings for missing fields.\n"
            "JSON keys: mrp, usp, net_quantity, product_name, manufacturer, "
            "manufacturing_date, expiry_date, consumer_care, dimensions, "
            "edible.\n"
            "Definitions:\n"
            "- edible = whether the product is an eatable/drinkable item "
            "(food, beverage, snack, spice, medicine). Answer exactly 'yes' "
            "or 'no'. 'no' covers toiletries, detergents, cosmetics, "
            "electronics, garments, stationery etc. Empty string if you "
            "cannot tell.\n"
            "- usp = UNIT SALE PRICE, the price per unit quantity printed on "
            "the label (e.g. 'Rs. 5.89 per g', 'USP 1.00/ml', 'Rs. 12 per "
            "100g'). Copy it verbatim. Keep the printed currency and unit "
            "notation (₹, Rs., /g, per ml) exactly as shown.\n"
            "- usp is NOT a marketing slogan, tagline, brand motto, flavor "
            "descriptor, preparation/usage instruction, or contact line. If "
            "the label shows no unit sale price, set usp to an empty string.\n"
            "- mrp = the maximum retail price (e.g. 'Rs. 265' or 'MRP Rs. "
            "265/-'), verbatim. IMPORTANT: preserve the Indian currency symbol "
            "exactly as printed — ₹ or 'Rs.' or 'INR' — immediately before or "
            "after the number; never omit, move or translate it.\n"
            "- net_quantity = the declared net quantity (e.g. '45 g', "
            "'250 ml'), verbatim."
        )
        if self.localization:
            prompt += (
                "\nAlso locate the mrp and net_quantity text on the label and "
                "return a `regions` object mapping ONLY the fields you can "
                "actually see to a tight bounding box [x1, y1, x2, y2] with "
                "integer coordinates, normalized 0-1000, origin at top-left. "
                "Start fresh: derive values and boxes solely from THIS image, "
                "never from other images or examples. Every JSON key, including "
                "'regions', must be double-quoted. Return valid strict JSON only."
            )
        return prompt

    def prompt_fingerprint(self) -> str:
        return hashlib.sha256(self._build_prompt().encode("utf-8")).hexdigest()

    def extract_structured(self, image_path: str) -> Dict:
        try:
            img = Image.open(image_path).convert("RGB")
            img = ImageOps.exif_transpose(img)
            img.thumbnail((self.max_image_size, self.max_image_size))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            img_b64 = base64.b64encode(buffer.getvalue()).decode("utf-8")

            prompt = self._build_prompt()

            payload = {
                "model": self.model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [img_b64]
                }],
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "num_ctx": 8192
                }
            }

            with httpx.Client(timeout=self.timeout) as client:
                for attempt in range(1, self.max_retries + 1):
                    raw = ""
                    try:
                        resp = client.post(self.ollama_url, json=payload)
                    except Exception as e:
                        print(f"[OCR] attempt {attempt}: request failed: {e}", flush=True)
                        self._reset_model()
                        time.sleep(5)
                        continue

                    if resp.status_code != 200:
                        print(f"[OCR] attempt {attempt}: HTTP {resp.status_code}: {resp.text[:200]}", flush=True)
                        self._reset_model()
                        time.sleep(5)
                        continue

                    try:
                        data = resp.json()
                    except Exception as e:
                        print(f"[OCR] attempt {attempt}: bad JSON: {e}", flush=True)
                        continue

                    raw = data.get("message", {}).get("content", "").strip()
                    print(f"[OCR] attempt {attempt}: raw len={len(raw)} preview={raw[:160]!r}", flush=True)

                    # Detect garbage output (all question marks, very short, no JSON)
                    if self._is_garbage(raw):
                        print(f"[OCR] attempt {attempt}: garbage detected, resetting model...", flush=True)
                        self._reset_model()
                        time.sleep(8)
                        continue

                    parsed = self._parse_json(raw)
                    if parsed is not None:
                        result = {k: parsed.get(k, "") for k in self.EXPECTED_KEYS}
                        if self.localization:
                            regions = parsed.get("regions")
                            if isinstance(regions, dict):
                                clean = {}
                                for fkey in ("mrp", "net_quantity"):
                                    box = regions.get(fkey)
                                    if box and len(box) == 4:
                                        try:
                                            clean[fkey] = [float(v) for v in box[:4]]
                                        except (TypeError, ValueError):
                                            continue
                                if clean:
                                    result["regions"] = clean
                        return result

                    print(f"[OCR] attempt {attempt}: unparseable, resetting model...", flush=True)
                    self._reset_model()
                    time.sleep(8)

                print(f"[OCR] FAILED after {self.max_retries} attempts for {image_path}; last raw: {raw[:200]!r}", flush=True)
                return {k: "" for k in self.EXPECTED_KEYS}

        except Exception as e:
            print(f"[OCR] extraction failed: {e}", flush=True)
            logger.error(f"Extraction failed: {e}")
            return {k: "" for k in self.EXPECTED_KEYS}

    def verify_currency_symbol(self, image_path: str, value: str) -> Optional[bool]:
        """Best-effort second look: confirm a ₹ / Rs. glyph is printed beside a
        price value that OCR returned without a currency symbol.

        Returns True / False when the VLM answers clearly, None if it cannot
        tell or the check fails (caller then keeps the original verdict).
        """
        try:
            img = Image.open(image_path).convert("RGB")
            img = ImageOps.exif_transpose(img)
            img.thumbnail((self.max_image_size, self.max_image_size))
            buffer = BytesIO()
            img.save(buffer, format="JPEG", quality=85)
            prompt = (
                "Look at this product label image. The text below was read "
                f"from it as a price value: {value}\n"
                "Is an Indian rupee symbol — '\\u20b9' (₹) or 'Rs.' or 'INR' — "
                "printed immediately next to this price value (just before or "
                "just after it)? The symbol may be small or stylized.\n"
                "Answer with exactly one word: YES or NO."
            )
            payload = {
                "model": self.model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [base64.b64encode(buffer.getvalue()).decode("utf-8")],
                }],
                "stream": False,
                "options": {"temperature": 0.0, "num_ctx": 4096},
            }
            with httpx.Client(timeout=min(self.timeout, 120)) as client:
                resp = client.post(self.ollama_url, json=payload)
            if resp.status_code != 200:
                print(f"[OCR] currency verify HTTP {resp.status_code}: {resp.text[:150]}", flush=True)
                return None
            raw = resp.json().get("message", {}).get("content", "").strip()
            print(f"[OCR] currency verify for {value!r}: {raw[:40]!r}", flush=True)
            first = raw.split()[0].lower() if raw.split() else ""
            if first.startswith("yes"):
                return True
            if first.startswith("no"):
                return False
            return None
        except Exception as e:
            print(f"[OCR] currency verify failed for {image_path}: {e}", flush=True)
            return None

    @staticmethod
    def _is_garbage(raw: str) -> bool:
        if not raw or len(raw) < 10:
            return True
        if GARBAGE_PATTERN.match(raw):
            return True
        return False

    def _reset_model(self) -> None:
        try:
            print(f"[OCR] unloading model {self.model}...", flush=True)
            subprocess.run(["ollama", "stop", self.model], timeout=30,
                           capture_output=True)
        except Exception as e:
            print(f"[OCR] model reset failed: {e}", flush=True)

    @staticmethod
    def _parse_json(raw: str) -> Optional[Dict]:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
        fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
        if fenced:
            try:
                return json.loads(fenced.group(1).strip())
            except json.JSONDecodeError:
                pass
        brace_match = re.search(r"\{[\s\S]*\}", raw)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass
        return None


_ocr_service = None


def get_ocr_service():
    global _ocr_service
    if _ocr_service is None:
        _ocr_service = OCRService()
    return _ocr_service
