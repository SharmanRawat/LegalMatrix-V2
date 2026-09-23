"""Raw-OCR transcript side channel (display-only).

Each per-image ``extract_structured`` result carries a nested
``ocr_meta.raw_ocr`` block — reads down to the display transcript floor,
captured from the SAME single engine call as the classifier tokens. This
module aggregates those blocks across the images of an inspection into a
plain, frontend-friendly ``ocr_transcript`` list.

By construction the transcript is never re-fed to the classifier: the frozen
golden-statutory audit token stream stays byte-identical.
"""
import os
from pathlib import Path
from typing import Dict, List


def build_ocr_transcript(
    image_paths: List[str], individual_results: List[Dict]
) -> List[Dict]:
    """One entry per image: filename, region count, low-confidence count and
    the joined raw text. Results without a raw_ocr block yield count 0 / ''."""
    transcript: List[Dict] = []
    sources = list(image_paths or [])
    for i, result in enumerate(individual_results or []):
        if not result:
            continue
        filename = ""
        if i < len(sources) and sources[i]:
            filename = Path(str(sources[i])).name
        raw = (result.get("ocr_meta") or {}).get("raw_ocr") or {}
        text = str(raw.get("text", "") or "")
        transcript.append({
            "filename": filename,
            "count": int(raw.get("count", 0) or 0),
            "low_conf": int(raw.get("low_conf", 0) or 0),
            "text": text,
        })
    return transcript


def transcript_total_regions(transcript: List[Dict]) -> int:
    return sum(int(e.get("count", 0) or 0) for e in transcript or [])


def transcript_has_text(transcript: List[Dict]) -> bool:
    return any(str(e.get("text", "") or "").strip() for e in transcript or [])