"""Raw-OCR transcript side channel tests.

The transcript is a display-only aggregation of each image's nested
``ocr_meta.raw_ocr`` block — it must never alter classifier inputs or the
frozen ten-field merge. These tests pin the aggregation contract.
"""
import io

from app.services.ocr_transcript import (
    build_ocr_transcript,
    transcript_has_text,
    transcript_total_regions,
)

_BLOCK = {
    "floor": 0.15,
    "count": 3,
    "low_conf": 1,
    "text": "MRP Rs. 100/-\nMFG 01/2026\nbar code",
}


def _result_with_raw(raw=None):
    return {"mrp": "MRP Rs. 100/-", "ocr_meta": {"engine": "rapidocr",
                                                 "raw_ocr": raw or _BLOCK}}


def test_build_single_image():
    out = build_ocr_transcript(["a/b/label.jpg"], [_result_with_raw()])
    assert out == [{
        "filename": "label.jpg",
        "count": 3,
        "low_conf": 1,
        "text": "MRP Rs. 100/-\nMFG 01/2026\nbar code",
    }]


def test_build_multiple_images_preserves_order():
    paths = ["/x/front.jpg", "/x/back.jpg"]
    results = [
        _result_with_raw({"floor": 0.15, "count": 2, "low_conf": 0, "text": "a\nb"}),
        _result_with_raw({"floor": 0.15, "count": 1, "low_conf": 0, "text": "c"}),
    ]
    out = build_ocr_transcript(paths, results)
    assert [e["filename"] for e in out] == ["front.jpg", "back.jpg"]
    assert out[0]["count"] == 2 and out[1]["count"] == 1


def test_missing_raw_ocr_yields_empty_entry():
    out = build_ocr_transcript(["label.jpg"], [{"mrp": "x"}])
    assert out == [{"filename": "label.jpg", "count": 0, "low_conf": 0, "text": ""}]


def test_none_results_skipped():
    assert build_ocr_transcript(["a.jpg"], [None]) == []
    assert build_ocr_transcript([], []) == []
    assert build_ocr_transcript(None, None) == []


def test_helpers():
    t = build_ocr_transcript(["f.jpg"], [_result_with_raw()])
    assert transcript_total_regions(t) == 3
    assert transcript_has_text(t) is True
    empty = build_ocr_transcript(["f.jpg"], [{"mrp": ""}])
    assert transcript_has_text(empty) is False
    assert transcript_total_regions([]) == 0


def _upload(client, path, headers):
    with open(path, "rb") as f:
        return client.post(
            "/api/inspect",
            files={"images": ("label.jpg", f, "image/jpeg")},
            headers=headers,
        )


class _FakeOCRWithTranscript:
    """FakeOCR variant that also reports a raw_ocr transcript block."""

    def extract_structured(self, image_path):
        return {
            "mrp": "MRP Rs. 100/-",
            "usp": "USP Rs. 0.50 per g",
            "net_quantity": "200 g",
            "product_name": "Test Commodity",
            "manufacturer": "Test Manufacturer Pvt Ltd",
            "manufacturing_date": "MFG: 01/2026",
            "expiry_date": "EXP: 01/2028",
            "consumer_care": "consumer.care@test.com 1800-123-456",
            "dimensions": "",
            "edible": "yes",
            "ocr_meta": {
                "engine": "rapidocr-test",
                "raw_ocr": {
                    "floor": 0.15,
                    "count": 4,
                    "low_conf": 1,
                    "text": "MRP Rs. 100/-\nMFG 01/2026\nbar code 8901234\nP.O.BAG 2 NEW DELHI",
                },
            },
        }

    def verify_currency_symbol(self, image_path, value):
        return None


class TestTranscriptApi:
    def test_transcript_in_response_and_stored_row(
        self, client, sample_image, auth_headers, monkeypatch
    ):
        import app.services.inspection_service as svc
        monkeypatch.setattr(svc, "_get_default_ocr", lambda: _FakeOCRWithTranscript())

        r = _upload(client, sample_image, auth_headers)
        assert r.status_code == 200
        data = r.json()

        # POST response carries the transcript; fresh run has meta in memory.
        assert "ocr_transcript" in data
        entry = data["ocr_transcript"][0]
        assert entry["filename"]
        assert entry["count"] == 4
        assert entry["low_conf"] == 1
        assert entry["text"] == (
            "MRP Rs. 100/-\nMFG 01/2026\nbar code 8901234\nP.O.BAG 2 NEW DELHI"
        )

        # Stored row flattens meta_json to the top level, so the detail view
        # shows the same transcript.
        got = client.get(f"/api/inspect/{data['inspection_id']}", headers=auth_headers)
        assert got.status_code == 200
        stored = got.json().get("ocr_transcript")
        assert stored == data["ocr_transcript"]

    def test_transcript_empty_without_raw_ocr(
        self, client, sample_image, auth_headers
    ):
        # Default FakeOCR returns a flat dict (no ocr_meta) — the transcript
        # key is still present and structurally valid.
        r = _upload(client, sample_image, auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert "ocr_transcript" in data
        entry = data["ocr_transcript"][0]
        assert entry["filename"]
        assert entry["count"] == 0
        assert entry["low_conf"] == 0
        assert entry["text"] == ""