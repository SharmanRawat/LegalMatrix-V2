"""
generate_ocr_training_data.py – Creates training data from actual PaddleOCR output.

For each product in dataset_complete_filled.csv:
  - Runs PaddleOCR on all available images
  - For each field (MRP, USP, net_quantity, etc.), finds the OCR box that best matches
    the CSV ground truth (using fuzzy matching)
  - Saves a new training file: ocr_training_data.csv

Usage:
    cd SIH2026/training
    python generate_ocr_training_data.py
"""

import re
import sys
import pandas as pd
from pathlib import Path
from difflib import SequenceMatcher

# Add backend to path for OCR engine
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))
from app.core.ocr_engine import ocr_engine

CSV_PATH = "dataset_complete_filled.csv"
IMAGE_DIR = Path("images")
OUTPUT_CSV = "ocr_training_data.csv"

# Fields to extract (matching your dataset)
FIELDS = [
    "mrp", "usp", "net_quantity", "product_name",
    "manufacturer", "manufacturing_date", "expiry_date", "consumer_care"
]

# Values to skip (these are missing labels)
SKIP_VALUES = {"NOT_VISIBLE", "could not find", "N/A", "NA", "", "nan"}


def fuzzy_match(a: str, b: str, threshold: float = 0.7) -> bool:
    """Check if two strings are similar (ignoring case, whitespace, punctuation)."""
    def normalize(s):
        # Remove extra spaces, punctuation, convert to lowercase
        s = re.sub(r'[^\w\s]', '', str(s))
        return re.sub(r'\s+', ' ', s).strip().lower()

    a_norm = normalize(a)
    b_norm = normalize(b)
    if a_norm == b_norm:
        return True
    ratio = SequenceMatcher(None, a_norm, b_norm).ratio()
    return ratio >= threshold


def find_matching_ocr_box(ocr_results, target_text, field_name):
    """
    Find the OCR box that best matches the target text.
    Returns the text from that box (or None if no match).
    """
    if not ocr_results:
        return None

    target = str(target_text).strip()
    if target in SKIP_VALUES or not target:
        return None

    best_match = None
    best_score = 0

    for item in ocr_results:
        text = item.get("text", "").strip()
        if not text:
            continue

        # For MRP and USP: prefer boxes with currency or "USP" keywords
        score = 0
        if field_name == "mrp":
            if re.search(r'[₹Rs]', text) or re.search(r'\bmrp\b', text.lower()):
                score = 1.0 + 0.1
        elif field_name == "usp":
            if re.search(r'\busp\b', text.lower()) or re.search(r'unit\s*sale', text.lower()):
                score = 1.0 + 0.1

        # Check similarity
        if fuzzy_match(target, text, threshold=0.5):
            # Higher score for longer text (more complete)
            score += len(text) / 100
            # Higher score for higher confidence
            score += item.get("confidence", 0) * 0.5

            if score > best_score:
                best_score = score
                best_match = text

    return best_match


def process_image(product_id, img_num, df_row):
    """
    Process a single image for a product.
    Returns a dict of extracted fields from OCR.
    """
    img_path = IMAGE_DIR / f"{product_id}_{img_num}.jpg"
    if not img_path.exists():
        return None

    print(f"  Processing {img_path.name}...")
    ocr_results = ocr_engine.extract_text_with_details(str(img_path))

    if not ocr_results:
        print(f"    ⚠️  No OCR results for {img_path.name}")
        return None

    extracted = {}
    for field in FIELDS:
        ground_truth = str(df_row.get(field, "")).strip()
        if ground_truth in SKIP_VALUES or not ground_truth:
            extracted[field] = "NOT_VISIBLE"
            continue

        matched_text = find_matching_ocr_box(ocr_results, ground_truth, field)
        if matched_text:
            extracted[field] = matched_text
        else:
            # If no exact match, look for the ground truth as a substring in any box
            found = False
            for item in ocr_results:
                text = item.get("text", "").strip()
                if text and ground_truth.lower() in text.lower():
                    extracted[field] = text
                    found = True
                    break
            if not found:
                extracted[field] = "NOT_VISIBLE"

    return extracted


def main():
    print("=" * 60)
    print("  Generating OCR Training Data from PaddleOCR")
    print("=" * 60)

    # Load dataset
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} products from {CSV_PATH}")

    # Store all training examples
    training_examples = []

    for idx, row in df.iterrows():
        product_id = row.get("product_id")
        print(f"\n📦 Product: {product_id}")

        # Try images 1, 2, 3 (front, back, neck)
        image_results = []
        for img_num in [1, 2, 3]:
            result = process_image(product_id, img_num, row)
            if result:
                image_results.append(result)

        if not image_results:
            print(f"  ⚠️  No images found for {product_id}")
            continue

        # Merge results from all images: if a field appears in any image, use the first one
        merged = {}
        for field in FIELDS:
            for img_result in image_results:
                if field in img_result and img_result[field] != "NOT_VISIBLE":
                    merged[field] = img_result[field]
                    break
            if field not in merged:
                merged[field] = "NOT_VISIBLE"

        # Add to training examples
        training_examples.append({
            "product_id": product_id,
            "mrp": merged.get("mrp", "NOT_VISIBLE"),
            "usp": merged.get("usp", "NOT_VISIBLE"),
            "net_quantity": merged.get("net_quantity", "NOT_VISIBLE"),
            "product_name": merged.get("product_name", "NOT_VISIBLE"),
            "manufacturer": merged.get("manufacturer", "NOT_VISIBLE"),
            "manufacturing_date": merged.get("manufacturing_date", "NOT_VISIBLE"),
            "expiry_date": merged.get("expiry_date", "NOT_VISIBLE"),
            "consumer_care": merged.get("consumer_care", "NOT_VISIBLE"),
        })

    # Save to CSV
    output_df = pd.DataFrame(training_examples)
    output_df.to_csv(OUTPUT_CSV, index=False)
    print(f"\n✅ Saved OCR training data to {OUTPUT_CSV}")
    print(f"   {len(output_df)} products, {len(FIELDS)} fields each")

    # Show sample
    print("\n📊 Sample of generated OCR data:")
    print(output_df.head(3).to_string())


if __name__ == "__main__":
    main()