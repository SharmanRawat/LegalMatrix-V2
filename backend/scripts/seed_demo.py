#!/usr/bin/env python3
"""
seed_demo.py — Populate LegalMatrix with realistic demo inspection data.

Usage:
    python scripts/seed_demo.py          # Seed demo data
    python scripts/seed_demo.py --cleanup # Remove only demo records
    python scripts/seed_demo.py --status  # Show demo record counts

All demo records are tagged with _demo: true in meta_json for safe,
non-destructive identification and removal. Real inspection data is
never touched.
"""
import argparse
import hashlib
import json
import os
import random
import sqlite3
import string
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
DB_PATH = DATA_DIR / "legalmatrix.db"
EVIDENCE_DIR = DATA_DIR / "evidence"

# ── Helpers ────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _random_id(date: datetime) -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"LGM-{date.strftime('%Y%m%d')}-{date.strftime('%H%M%S')}-{suffix}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_placeholder_image(label: str) -> tuple[bytes, str]:
    """Create a minimal valid JPEG-like placeholder (tiny valid PNG)."""
    # 1x1 white pixel PNG (smallest valid image)
    import struct
    import zlib

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        c = chunk_type + data
        crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
        return struct.pack(">I", len(data)) + c + crc

    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw_pixel = b"\x00\xff\xff\xff"  # filter byte + RGB white
    compressed = zlib.compress(raw_pixel)

    png = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr_data)
    png += _chunk(b"IDAT", compressed)
    png += _chunk(b"IEND", b"")
    return png, f"demo_{label.lower().replace(' ', '_')}.png"


def _save_evidence(inspection_id: str, images: list[dict]) -> str:
    """Save placeholder images to evidence dir, return composite hash."""
    evidence_dir = EVIDENCE_DIR
    evidence_dir.mkdir(parents=True, exist_ok=True)

    composite_hash = ""
    db_images = []
    for i, img_info in enumerate(images):
        img_bytes, _ = _make_placeholder_image(img_info["original_name"])
        sha = _sha256(img_bytes)
        filename = f"demo_{sha[:16]}_{i+1}_evidence.png"
        dest = evidence_dir / filename
        dest.write_bytes(img_bytes)

        db_images.append({
            "filename": filename,
            "original_name": img_info["original_name"],
            "sha256": sha,
            "sort_order": i,
        })
        composite_hash += sha

    composite_hash = _sha256(composite_hash.encode("utf-8")) if composite_hash else ""
    return composite_hash, db_images


# ── Demo Data Definitions ──────────────────────────────────────────────

PRODUCTS = [
    {
        "product_name": "Amul Gold Full Cream Milk",
        "manufacturer": "Gujarat Cooperative Milk Marketing Federation, Anand",
        "category": "Dairy",
        "images": ["front_label_milk.jpg", "back_label_milk.jpg"],
    },
    {
        "product_name": "Tata Salt Iodised",
        "manufacturer": "Tata Chemicals Ltd., Mumbai",
        "category": "Edible Salt",
        "images": ["front_salt.jpg"],
    },
    {
        "product_name": "Fortune Sunlite Refined Sunflower Oil",
        "manufacturer": "Adani Wilmar Ltd., Ahmedabad",
        "category": "Edible Oil",
        "images": ["front_oil.jpg", "back_oil.jpg", "side_oil.jpg"],
    },
    {
        "product_name": "Surf Excel Easy Wash Detergent Powder",
        "manufacturer": "Hindustan Unilever Ltd., Mumbai",
        "category": "Detergent",
        "images": ["front_detergent.jpg", "back_detergent.jpg"],
    },
    {
        "product_name": "Maggi 2-Minute Masala Noodles",
        "manufacturer": "Nestle India Ltd., Gurugram",
        "category": "Instant Noodles",
        "images": ["front_noodles.jpg", "back_noodles.jpg", "side_noodles.jpg"],
    },
    {
        "product_name": "Colgate MaxFresh Toothpaste",
        "manufacturer": "Colgate-Palmolive India Ltd., Mumbai",
        "category": "Oral Care",
        "images": ["front_toothpaste.jpg", "back_toothpaste.jpg"],
    },
    {
        "product_name": "Dettol Antiseptic Liquid",
        "manufacturer": "Reckitt Benckiser India Ltd., Gurugram",
        "category": "Antiseptic",
        "images": ["front_dettol.jpg"],
    },
    {
        "product_name": "Aashirvaad Atta with Multi Grains",
        "manufacturer": "ITC Ltd., Kolkata",
        "category": "Flour",
        "images": ["front_atta.jpg", "back_atta.jpg"],
    },
    {
        "product_name": "Parle-G Glucose Biscuits",
        "manufacturer": "Parle Products Pvt. Ltd., Mumbai",
        "category": "Biscuits",
        "images": ["front_biscuit.jpg", "back_biscuit.jpg", "side_biscuit.jpg"],
    },
    {
        "product_name": "Vim Dishwash Liquid Gel",
        "manufacturer": "Hindustan Unilever Ltd., Mumbai",
        "category": "Dishwash",
        "images": ["front_vim.jpg", "back_vim.jpg"],
    },
]

# ── Inspection Configurations ──────────────────────────────────────────
# Each config defines the outcome for one of the 10 demo inspections.
# day_offset: how many days ago (0=today, 13=max for 14-day chart)

INSPECTION_CONFIGS = [
    # 1 — Fully compliant milk
    {
        "product_idx": 0,
        "day_offset": 0,
        "status": "COMPLIANT",
        "compliance_score": 96.4,
        "passed_count": 7,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹32",
            "usp": "₹32 per litre",
            "net_quantity": "500 ml",
            "product_name": "Amul Gold Full Cream Milk",
            "manufacturer": "Gujarat Cooperative Milk Marketing Federation, Anand, Gujarat 388001",
            "manufacturing_date": "21/09/2026",
            "expiry_date": "23/09/2026",
            "consumer_care": "amul.com, 1800-226-040",
            "dimensions": None,
            "edible": "yes",
        },
        "missing": [],
        "violations": [],
        "misleading": [],
        "radar": {
            "overall": 97.8,
            "grade": "A",
            "grade_label": "Highly Compliant",
            "axes": [
                {"axis": "Declarations", "score": 100, "weight": 0.375},
                {"axis": "Pricing", "score": 95, "weight": 0.25},
                {"axis": "Dates", "score": 100, "weight": 0.125},
                {"axis": "Consumer Care", "score": 100, "weight": 0.125},
                {"axis": "Readability", "score": 92, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 94,
            "coverage_ratio": 0.91,
            "fields_present": 9,
            "fields_required": 10,
            "by_field": {"mrp": 98, "usp": 92, "net_quantity": 96, "product_name": 99, "manufacturer": 95, "manufacturing_date": 90, "expiry_date": 88, "consumer_care": 85, "dimensions": 0, "edible": 97},
        },
    },
    # 2 — Non-compliant detergent (missing consumer care, dimensions)
    {
        "product_idx": 3,
        "day_offset": 1,
        "status": "POTENTIAL_VIOLATION",
        "compliance_score": 54.2,
        "passed_count": 4,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹245",
            "usp": "₹245 per kg",
            "net_quantity": "1 kg",
            "product_name": "Surf Excel Easy Wash Detergent Powder",
            "manufacturer": "Hindustan Unilever Ltd., Mumbai 400099",
            "manufacturing_date": "AUG/2026",
            "expiry_date": None,
            "consumer_care": None,
            "dimensions": None,
            "edible": "no",
        },
        "missing": ["consumer_care_details", "dimensions_where_relevant"],
        "violations": [
            {
                "rule_id": "consumer_care_details",
                "rule_no": "Rule 6(2)",
                "severity": "HIGH",
                "status": "MISSING",
                "field": "consumer_care",
                "extracted_value": "",
                "description": "Consumer care details including contact information are not mentioned on the label.",
                "remediation": "Add manufacturer name, address, and consumer care contact (phone/email) on the label.",
            },
            {
                "rule_id": "dimensions_where_relevant",
                "rule_no": "Rule 6(1)(f)",
                "severity": "MEDIUM",
                "status": "MISSING",
                "field": "dimensions",
                "extracted_value": "",
                "description": "Dimensions are not mentioned. Required for packages where size is a selling point.",
                "remediation": "Include dimensions (L x W x H) on the label if the product is sold by size.",
            },
        ],
        "misleading": [
            {
                "check": "usp_missing_or_equal_mrp",
                "severity": "MEDIUM",
                "detail": "USP equals MRP — consumer gets no price advantage indication.",
                "extracted_value": "MRP=245; USP=245",
            },
        ],
        "radar": {
            "overall": 47.0,
            "grade": "D",
            "grade_label": "Non-Compliant",
            "axes": [
                {"axis": "Declarations", "score": 57, "weight": 0.375},
                {"axis": "Pricing", "score": 50, "weight": 0.25},
                {"axis": "Dates", "score": 40, "weight": 0.125},
                {"axis": "Consumer Care", "score": 0, "weight": 0.125},
                {"axis": "Readability", "score": 65, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 68,
            "coverage_ratio": 0.70,
            "fields_present": 7,
            "fields_required": 10,
            "by_field": {"mrp": 95, "usp": 88, "net_quantity": 92, "product_name": 97, "manufacturer": 90, "manufacturing_date": 72, "expiry_date": 0, "consumer_care": 0, "dimensions": 0, "edible": 85},
        },
    },
    # 3 — Needs review noodles (expiry date format issue)
    {
        "product_idx": 4,
        "day_offset": 2,
        "status": "REVIEW_REQUIRED",
        "compliance_score": 78.5,
        "passed_count": 6,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹14",
            "usp": "₹14 per pack",
            "net_quantity": "70 g",
            "product_name": "Maggi 2-Minute Masala Noodles",
            "manufacturer": "Nestle India Ltd., Gurugram, Haryana 122001",
            "manufacturing_date": "15/09/2026",
            "expiry_date": "15/03/2027",
            "consumer_care": "nestle.in, 1800-111-222",
            "dimensions": None,
            "edible": "yes",
        },
        "missing": ["dimensions_where_relevant"],
        "violations": [
         {
                "rule_id": "dimensions_where_relevant",
                "rule_no": "Rule 6(1)(f)",
                "severity": "MEDIUM",
                "status": "MISSING",
                "field": "dimensions",
                "extracted_value": "",
                "description": "Dimensions not provided. While not mandatory for all food products, the net quantity declaration should be prominent.",
                "remediation": "Consider adding package dimensions for transparency.",
            },
        ],
        "misleading": [],
        "radar": {
            "overall": 82.0,
            "grade": "B",
            "grade_label": "Minor Violations",
            "axes": [
                {"axis": "Declarations", "score": 83, "weight": 0.375},
                {"axis": "Pricing", "score": 80, "weight": 0.25},
                {"axis": "Dates", "score": 85, "weight": 0.125},
                {"axis": "Consumer Care", "score": 90, "weight": 0.125},
                {"axis": "Readability", "score": 72, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 82,
            "coverage_ratio": 0.80,
            "fields_present": 9,
            "fields_required": 10,
            "by_field": {"mrp": 97, "usp": 85, "net_quantity": 94, "product_name": 98, "manufacturer": 92, "manufacturing_date": 88, "expiry_date": 80, "consumer_care": 78, "dimensions": 0, "edible": 95},
        },
    },
    # 4 — Fully compliant salt
    {
        "product_idx": 1,
        "day_offset": 3,
        "status": "COMPLIANT",
        "compliance_score": 99.1,
        "passed_count": 7,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹28",
            "usp": "₹28 per kg",
            "net_quantity": "1 kg",
            "product_name": "Tata Salt Iodised",
            "manufacturer": "Tata Chemicals Ltd., Mumbai 400020",
            "manufacturing_date": "SEP/2026",
            "expiry_date": "SEP/2028",
            "consumer_care": "tatatestsalt.com, 1800-22-0001",
            "dimensions": "19cm x 12cm x 5cm",
            "edible": "yes",
        },
        "missing": [],
        "violations": [],
        "misleading": [],
        "radar": {
            "overall": 99.8,
            "grade": "A",
            "grade_label": "Highly Compliant",
            "axes": [
                {"axis": "Declarations", "score": 100, "weight": 0.375},
                {"axis": "Pricing", "score": 100, "weight": 0.25},
                {"axis": "Dates", "score": 100, "weight": 0.125},
                {"axis": "Consumer Care", "score": 100, "weight": 0.125},
                {"axis": "Readability", "score": 98, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 97,
            "coverage_ratio": 1.0,
            "fields_present": 10,
            "fields_required": 10,
            "by_field": {"mrp": 99, "usp": 96, "net_quantity": 98, "product_name": 99, "manufacturer": 97, "manufacturing_date": 95, "expiry_date": 94, "consumer_care": 96, "dimensions": 90, "edible": 99},
        },
    },
    # 5 — Violation: oil missing MRP symbol
    {
        "product_idx": 2,
        "day_offset": 5,
        "status": "POTENTIAL_VIOLATION",
        "compliance_score": 42.8,
        "passed_count": 3,
        "total_rules": 7,
        "declarations": {
            "mrp": "249.00",
            "usp": None,
            "net_quantity": "1 litre",
            "product_name": "Fortune Sunlite Refined Sunflower Oil",
            "manufacturer": "Adani Wilmar Ltd., Ahmedabad, Gujarat 380015",
            "manufacturing_date": None,
            "expiry_date": "APR/2027",
            "consumer_care": "care@adaniwilmar.com",
            "dimensions": None,
            "edible": "yes",
        },
        "missing": ["month_year_manufacture"],
        "violations": [
            {
                "rule_id": "mrp",
                "rule_no": "Rule 6(1)(e)",
                "severity": "CRITICAL",
                "status": "FORMAT_ISSUE",
                "field": "mrp",
                "extracted_value": "249.00",
                "description": "MRP is printed without the Indian Rupee symbol (₹). The MRP must include the currency symbol.",
                "remediation": "Print MRP as '₹249' including the Indian Rupee symbol.",
            },
            {
                "rule_id": "month_year_manufacture",
                "rule_no": "Rule 6(1)(d)",
                "severity": "HIGH",
                "status": "MISSING",
                "field": "manufacturing_date",
                "extracted_value": "",
                "description": "Month and year of manufacture are not clearly mentioned on the label.",
                "remediation": "Print month and year of manufacturing prominently on the label.",
            },
            {
                "rule_id": "usp",
                "rule_no": "Rule 6(1)(e)",
                "severity": "HIGH",
                "status": "MISSING",
                "field": "usp",
                "extracted_value": "",
                "description": "Unit sale price not declared. Required when MRP is for a non-standard quantity.",
                "remediation": "Add unit sale price (per litre/kg/g) alongside the MRP.",
            },
        ],
        "misleading": [
            {
                "check": "usp_mismatch_computed",
                "severity": "HIGH",
                "detail": "Unit sale price could not be verified — MRP present but USP missing.",
                "extracted_value": "MRP=249; USP=N/A",
            },
        ],
        "radar": {
            "overall": 39.2,
            "grade": "D",
            "grade_label": "Non-Compliant",
            "axes": [
                {"axis": "Declarations", "score": 43, "weight": 0.375},
                {"axis": "Pricing", "score": 20, "weight": 0.25},
                {"axis": "Dates", "score": 30, "weight": 0.125},
                {"axis": "Consumer Care", "score": 60, "weight": 0.125},
                {"axis": "Readability", "score": 55, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 58,
            "coverage_ratio": 0.60,
            "fields_present": 6,
            "fields_required": 10,
            "by_field": {"mrp": 45, "usp": 0, "net_quantity": 90, "product_name": 95, "manufacturer": 88, "manufacturing_date": 0, "expiry_date": 82, "consumer_care": 70, "dimensions": 0, "edible": 80},
        },
    },
    # 6 — Compliant toothpaste with manual override
    {
        "product_idx": 5,
        "day_offset": 6,
        "status": "COMPLIANT",
        "compliance_score": 91.3,
        "passed_count": 7,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹95",
            "usp": "₹95 per 150g",
            "net_quantity": "150 g",
            "product_name": "Colgate MaxFresh Toothpaste",
            "manufacturer": "Colgate-Palmolive India Ltd., Mumbai 400076",
            "manufacturing_date": "JUL/2026",
            "expiry_date": "JUL/2028",
            "consumer_care": "colgate.in, 1800-225-566",
            "dimensions": None,
            "edible": "no",
        },
        "missing": [],
        "violations": [],
        "misleading": [],
        "radar": {
            "overall": 95.2,
            "grade": "A",
            "grade_label": "Highly Compliant",
            "axes": [
                {"axis": "Declarations", "score": 100, "weight": 0.375},
                {"axis": "Pricing", "score": 92, "weight": 0.25},
                {"axis": "Dates", "score": 95, "weight": 0.125},
                {"axis": "Consumer Care", "score": 98, "weight": 0.125},
                {"axis": "Readability", "score": 85, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 89,
            "coverage_ratio": 0.89,
            "fields_present": 9,
            "fields_required": 10,
            "by_field": {"mrp": 96, "usp": 88, "net_quantity": 94, "product_name": 98, "manufacturer": 93, "manufacturing_date": 85, "expiry_date": 82, "consumer_care": 90, "dimensions": 0, "edible": 92},
        },
        "manual_overrides": {
            "consumer_care": {
                "original": "care@colgate.com",
                "corrected": "colgate.in, 1800-225-566",
                "by_user_id": 1,
                "at": "2026-09-15T10:30:00Z",
            }
        },
    },
    # 7 — Review required antiseptic (declaration missing)
    {
        "product_idx": 6,
        "day_offset": 8,
        "status": "REVIEW_REQUIRED",
        "compliance_score": 72.0,
        "passed_count": 6,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹185",
            "usp": "₹185 per 500ml",
            "net_quantity": "500 ml",
            "product_name": "Dettol Antiseptic Liquid",
            "manufacturer": "Reckitt Benckiser India Ltd., Gurugram, Haryana 122001",
            "manufacturing_date": "AUG/2026",
            "expiry_date": "AUG/2028",
            "consumer_care": "reckitt.com, 1800-102-2222",
            "dimensions": None,
            "edible": "no",
        },
        "missing": ["dimensions_where_relevant"],
        "violations": [
            {
                "rule_id": "dimensions_where_relevant",
                "rule_no": "Rule 6(1)(f)",
                "severity": "MEDIUM",
                "status": "MISSING",
                "field": "dimensions",
                "extracted_value": "",
                "description": "Package dimensions not declared on the label.",
                "remediation": "Include dimensions if the product is sold in standardized packaging.",
            },
        ],
        "misleading": [],
        "radar": {
            "overall": 84.2,
            "grade": "B",
            "grade_label": "Minor Violations",
            "axes": [
                {"axis": "Declarations", "score": 83, "weight": 0.375},
                {"axis": "Pricing", "score": 85, "weight": 0.25},
                {"axis": "Dates", "score": 90, "weight": 0.125},
                {"axis": "Consumer Care", "score": 95, "weight": 0.125},
                {"axis": "Readability", "score": 70, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 75,
            "coverage_ratio": 0.80,
            "fields_present": 9,
            "fields_required": 10,
            "by_field": {"mrp": 94, "usp": 80, "net_quantity": 92, "product_name": 96, "manufacturer": 91, "manufacturing_date": 78, "expiry_date": 75, "consumer_care": 88, "dimensions": 0, "edible": 90},
        },
    },
    # 8 — Compliant atta
    {
        "product_idx": 7,
        "day_offset": 10,
        "status": "COMPLIANT",
        "compliance_score": 93.7,
        "passed_count": 7,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹360",
            "usp": "₹360 per 5kg",
            "net_quantity": "5 kg",
            "product_name": "Aashirvaad Atta with Multi Grains",
            "manufacturer": "ITC Ltd., Kolkata, West Bengal 700071",
            "manufacturing_date": "SEP/2026",
            "expiry_date": "MAR/2027",
            "consumer_care": "ashirvaad.com, 1800-425-1234",
            "dimensions": "30cm x 20cm x 12cm",
            "edible": "yes",
        },
        "missing": [],
        "violations": [],
        "misleading": [],
        "radar": {
            "overall": 96.0,
            "grade": "A",
            "grade_label": "Highly Compliant",
            "axes": [
                {"axis": "Declarations", "score": 100, "weight": 0.375},
                {"axis": "Pricing", "score": 95, "weight": 0.25},
                {"axis": "Dates", "score": 90, "weight": 0.125},
                {"axis": "Consumer Care", "score": 100, "weight": 0.125},
                {"axis": "Readability", "score": 88, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 92,
            "coverage_ratio": 1.0,
            "fields_present": 10,
            "fields_required": 10,
            "by_field": {"mrp": 97, "usp": 90, "net_quantity": 95, "product_name": 98, "manufacturer": 94, "manufacturing_date": 88, "expiry_date": 86, "consumer_care": 92, "dimensions": 88, "edible": 96},
        },
    },
    # 9 — Violation: biscuits missing net quantity
    {
        "product_idx": 8,
        "day_offset": 12,
        "status": "POTENTIAL_VIOLATION",
        "compliance_score": 38.5,
        "passed_count": 3,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹10",
            "usp": "₹10 per pack",
            "net_quantity": None,
            "product_name": "Parle-G Glucose Biscuits",
            "manufacturer": "Parle Products Pvt. Ltd., Mumbai 400013",
            "manufacturing_date": "SEP/2026",
            "expiry_date": "MAR/2027",
            "consumer_care": "parle.com, 1800-111-333",
            "dimensions": None,
            "edible": "yes",
        },
        "missing": ["net_quantity"],
        "violations": [
            {
                "rule_id": "net_quantity",
                "rule_no": "Rule 6(1)(c)",
                "severity": "CRITICAL",
                "status": "MISSING",
                "field": "net_quantity",
                "extracted_value": "",
                "description": "Net quantity of the commodity is not declared on the package. This is a mandatory declaration under Legal Metrology rules.",
                "remediation": "Print the net quantity (e.g., '100 g' or '20 biscuits, 100g') prominently on the front label.",
            },
        ],
        "misleading": [
            {
                "check": "net_qty_mismatch",
                "severity": "HIGH",
                "detail": "No net quantity declaration found. The weight or count of contents must be stated.",
                "extracted_value": "MISSING",
            },
        ],
        "radar": {
            "overall": 61.8,
            "grade": "C",
            "grade_label": "Significant Violations",
            "axes": [
                {"axis": "Declarations", "score": 43, "weight": 0.375},
                {"axis": "Pricing", "score": 70, "weight": 0.25},
                {"axis": "Dates", "score": 80, "weight": 0.125},
                {"axis": "Consumer Care", "score": 85, "weight": 0.125},
                {"axis": "Readability", "score": 60, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 52,
            "coverage_ratio": 0.55,
            "fields_present": 5,
            "fields_required": 10,
            "by_field": {"mrp": 92, "usp": 75, "net_quantity": 0, "product_name": 95, "manufacturer": 90, "manufacturing_date": 80, "expiry_date": 78, "consumer_care": 82, "dimensions": 0, "edible": 88},
        },
    },
    # 10 — Compliant dishwash (most recent, for "recent inspections")
    {
        "product_idx": 9,
        "day_offset": 0,
        "status": "COMPLIANT",
        "compliance_score": 88.9,
        "passed_count": 7,
        "total_rules": 7,
        "declarations": {
            "mrp": "₹99",
            "usp": "₹99 per 500ml",
            "net_quantity": "500 ml",
            "product_name": "Vim Dishwash Liquid Gel",
            "manufacturer": "Hindustan Unilever Ltd., Mumbai 400099",
            "manufacturing_date": "SEP/2026",
            "expiry_date": "SEP/2028",
            "consumer_care": "hul.co.in, 1800-200-4444",
            "dimensions": None,
            "edible": "no",
        },
        "missing": [],
        "violations": [],
        "misleading": [],
        "radar": {
            "overall": 92.5,
            "grade": "A",
            "grade_label": "Highly Compliant",
            "axes": [
                {"axis": "Declarations", "score": 100, "weight": 0.375},
                {"axis": "Pricing", "score": 90, "weight": 0.25},
                {"axis": "Dates", "score": 85, "weight": 0.125},
                {"axis": "Consumer Care", "score": 95, "weight": 0.125},
                {"axis": "Readability", "score": 80, "weight": 0.125},
            ],
        },
        "confidence": {
            "overall": 86,
            "coverage_ratio": 0.88,
            "fields_present": 9,
            "fields_required": 10,
            "by_field": {"mrp": 95, "usp": 88, "net_quantity": 93, "product_name": 97, "manufacturer": 91, "manufacturing_date": 82, "expiry_date": 80, "consumer_care": 86, "dimensions": 0, "edible": 90},
        },
    },
]


# ── Database Operations ────────────────────────────────────────────────

def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def count_existing(conn: sqlite3.Connection) -> dict:
    """Count existing records by type."""
    total = conn.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]
    demo = conn.execute(
        "SELECT COUNT(*) FROM inspections WHERE meta_json LIKE '%\"_demo\": true%'"
    ).fetchone()[0]
    users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    return {"total_inspections": total, "demo_inspections": demo, "users": users}


def seed_demo_data() -> None:
    """Insert 10 demo inspections into the database."""
    conn = get_conn()
    existing = count_existing(conn)

    if existing["demo_inspections"] > 0:
        print(f"[WARN]  {existing['demo_inspections']} demo records already exist.")
        print("   Run with --cleanup first to remove them, or --status to inspect.")
        conn.close()
        return

    print(f"[DB] {existing['total_inspections']} existing inspections, {existing['users']} users")
    print(f"[SEED] Seeding 10 demo inspections...\n")

    now = datetime.now(timezone.utc)
    seeded = []

    for i, config in enumerate(INSPECTION_CONFIGS):
        product = PRODUCTS[config["product_idx"]]
        inspection_date = now - timedelta(days=config["day_offset"], hours=random.randint(0, 12))
        inspection_id = _random_id(inspection_date)

        # Save placeholder evidence images
        image_files = [{"original_name": name} for name in product["images"]]
        evidence_hash, db_images = _save_evidence(inspection_id, image_files)

        # Build meta_json with all supplementary data
        meta = {
            "_demo": True,
            "_demo_label": f"Demo Inspection #{i+1}: {product['product_name']}",
            "compliance_radar": config["radar"],
            "grade": config["radar"]["grade"],
            "heatmaps": [
                {
                    "filename": f"demo_heatmap_{inspection_id[:8]}_{j}.png",
                    "image_index": j,
                    "field_boxes": {},
                    "calibration_box": None,
                }
                for j in range(len(product["images"]))
            ],
            "ocr_engine": "demo-seed",
            "classifier": "demo-seed",
            "field_evidence": {
                key: {
                    "source": random.choice(["regex", "vlm+regex", "llm"]),
                    "text": f"[DEMO] {key}: {val}" if val else f"[DEMO] {key}: not detected",
                    "image_index": random.randint(0, len(product["images"]) - 1),
                }
                for key, val in config["declarations"].items()
                if val
            },
            "extraction_confidence": config["confidence"],
            "manual_overrides": config.get("manual_overrides", {}),
            "ocr_confidence": round(random.uniform(0.85, 0.98), 2),
        }

        # Insert inspection
        conn.execute(
            "INSERT INTO inspections "
            "(id, product_name, manufacturer, status, compliance_score, "
            " passed_count, total_rules, declarations_json, missing_json, "
            " violations_json, misleading_json, meta_json, evidence_hash, images_count, "
            " model, user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                inspection_id,
                product["product_name"],
                product["manufacturer"],
                config["status"],
                config["compliance_score"],
                config["passed_count"],
                config["total_rules"],
                json.dumps(config["declarations"], ensure_ascii=False),
                json.dumps(config["missing"], ensure_ascii=False),
                json.dumps(config["violations"], ensure_ascii=False),
                json.dumps(config["misleading"], ensure_ascii=False),
                json.dumps(meta, ensure_ascii=False),
                evidence_hash,
                len(product["images"]),
                "demo-seed",
                1,  # admin user
                inspection_date.isoformat(),
            ),
        )

        # Insert evidence image records
        for img in db_images:
            conn.execute(
                "INSERT INTO inspection_images "
                "(inspection_id, filename, original_name, sha256, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (inspection_id, img["filename"], img["original_name"], img["sha256"], img["sort_order"]),
            )

        seeded.append(inspection_id)
        status_icon = {"COMPLIANT": "[OK]", "REVIEW_REQUIRED": "[!]", "POTENTIAL_VIOLATION": "[X]"}.get(config["status"], "?")
        print(f"  {status_icon} {inspection_id}  {product['product_name'][:35]:<35}  {config['compliance_score']:5.1f}%  {config['status']}")

    conn.commit()
    conn.close()

    img_count = sum(len(PRODUCTS[c["product_idx"]]["images"]) for c in INSPECTION_CONFIGS)
    print(f"\n[OK] Seeded {len(seeded)} demo inspections with {img_count} evidence images.")
    print(f"   Demo records are tagged with _demo: true in meta_json.")
    print(f"\n   Dashboard will now show {len(seeded)} additional inspections.")
    print(f"   History will list them with varied statuses and dates.")


def cleanup_demo_data() -> None:
    """Remove only demo-tagged inspection records and their evidence."""
    conn = get_conn()
    existing = count_existing(conn)

    if existing["demo_inspections"] == 0:
        print("[INFO]  No demo records found. Nothing to clean up.")
        conn.close()
        return

    print(f"[REMOVE]  Removing {existing['demo_inspections']} demo inspections...\n")

    # Get demo inspection IDs
    rows = conn.execute(
        "SELECT id FROM inspections WHERE meta_json LIKE '%\"_demo\": true%'"
    ).fetchall()

    removed_images = 0
    removed_inspections = 0

    for row in rows:
        insp_id = row["id"]

        # Delete evidence files from disk
        img_rows = conn.execute(
            "SELECT filename FROM inspection_images WHERE inspection_id = ?", (insp_id,)
        ).fetchall()
        for img in img_rows:
            fpath = EVIDENCE_DIR / img["filename"]
            if fpath.exists():
                fpath.unlink()
                removed_images += 1

        # Delete heatmap files
        meta_row = conn.execute(
            "SELECT meta_json FROM inspections WHERE id = ?", (insp_id,)
        ).fetchone()
        if meta_row:
            meta = json.loads(meta_row["meta_json"] or "{}")
            for hm in meta.get("heatmaps", []):
                hm_path = EVIDENCE_DIR / "heatmaps" / hm.get("filename", "")
                if hm_path.exists():
                    hm_path.unlink()
                    removed_images += 1

        # Delete image records
        conn.execute("DELETE FROM inspection_images WHERE inspection_id = ?", (insp_id,))
        # Delete inspection
        conn.execute("DELETE FROM inspections WHERE id = ?", (insp_id,))
        removed_inspections += 1
        print(f"  [REMOVE]  {insp_id}")

    conn.commit()
    conn.close()

    print(f"\n[OK] Removed {removed_inspections} demo inspections and {removed_images} evidence files.")
    print(f"   {existing['total_inspections'] - existing['demo_inspections']} real inspections preserved.")


def show_status() -> None:
    """Show current demo data status."""
    conn = get_conn()
    counts = count_existing(conn)

    print("[STATUS] Demo Data Status")
    print(f"   Total inspections: {counts['total_inspections']}")
    print(f"   Demo inspections:  {counts['demo_inspections']}")
    print(f"   Real inspections:  {counts['total_inspections'] - counts['demo_inspections']}")
    print(f"   Users:             {counts['users']}")

    if counts["demo_inspections"] > 0:
        print("\n   Demo records:")
        rows = conn.execute(
            "SELECT id, product_name, status, compliance_score, created_at "
            "FROM inspections WHERE meta_json LIKE '%\"_demo\": true%' "
            "ORDER BY created_at DESC"
        ).fetchall()
        for row in rows:
            status_icon = {"COMPLIANT": "[OK]", "REVIEW_REQUIRED": "[!]", "POTENTIAL_VIOLATION": "[X]"}.get(row["status"], "?")
            print(f"     {status_icon} {row['id']}  {row['product_name'][:30]:<30}  {row['compliance_score']:5.1f}%  {row['created_at'][:10]}")

    conn.close()


# ── CLI ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Seed or remove demo inspection data for LegalMatrix.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/seed_demo.py           # Seed 10 demo inspections
  python scripts/seed_demo.py --cleanup # Remove only demo records
  python scripts/seed_demo.py --status  # Show demo data counts
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--cleanup", action="store_true", help="Remove only demo-tagged records")
    group.add_argument("--status", action="store_true", help="Show current demo data counts")
    args = parser.parse_args()

    if args.cleanup:
        cleanup_demo_data()
    elif args.status:
        show_status()
    else:
        seed_demo_data()


if __name__ == "__main__":
    main()
