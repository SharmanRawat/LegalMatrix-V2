import hashlib
import io
import json
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Header
from fastapi.responses import JSONResponse, StreamingResponse, Response, FileResponse
from PIL import Image

from app.config import get_evidence_dir
from app.repositories import inspections as inspection_repo
from app.services import inspection_service
from app.services import progress as progress_store
from app.services.auth_service import optional_auth, require_roles

from fpdf import FPDF

router = APIRouter()


def _can_access_inspection(user: Optional[dict], inspection: dict) -> bool:
    """Read scoping for stored inspections.

    ADMIN sees every inspection. An authenticated non-admin (INSPECTOR /
    VIEWER) sees only scans they created. Anonymous callers keep read access
    so the no-login demo flow can still render the report / detail pages
    after a run. All non-admin access checks are enforced per inspection.
    """
    if not user:
        return True
    if user.get("role") == "ADMIN":
        return True
    owner = inspection.get("user_id")
    return owner is not None and int(owner) == int(user.get("uid") or -1)


def _require_access(user: Optional[dict], inspection: dict) -> None:
    if not _can_access_inspection(user, inspection):
        raise HTTPException(
            403, "You can only view or modify inspections you created"
        )


async def _save_uploads(images: List[UploadFile]) -> List[str]:
    if not images:
        raise HTTPException(400, "At least one image is required")
    if len(images) > 6:
        raise HTTPException(400, "Maximum 6 images allowed")
    temp_paths = []
    try:
        for image_file in images:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
                content = await image_file.read()
                if not content:
                    raise HTTPException(400, "Empty image file uploaded")
                tmp.write(content)
                temp_paths.append(tmp.name)
        return temp_paths
    except HTTPException:
        for p in temp_paths:
            import os
            os.unlink(p)
        raise


@router.post("/inspect")
async def inspect_package(
    images: List[UploadFile] = File(...),
    label_types: List[str] = Form(default=None),
    x_progress_token: Optional[str] = Header(default=None),
    user=Depends(optional_auth),
):
    """Run a compliance inspection on 1-6 product label images and persist it.

    ``label_types`` is optional and aligned with ``images`` — one of
    front/back/side/top/other per photo (e.g. front label = PDP, back label =
    declaration block, top = cap/roof face). When present, each field is routed
    to the photo whose label type is its strongest source; absent/unknown
    entries fall back to the original best-photo heuristics.

    ``X-Progress-Token`` (optional) makes the pipeline's per-stage events
    pollable at GET /api/inspect/progress/{token} while the synchronous
    request is still in flight.
    """
    try:
        paths = await _save_uploads(images)
        if label_types and len(label_types) != len(paths):
            raise HTTPException(400, "label_types must have one entry per image")
        normalized = [t.lower() for t in label_types] if label_types else None
        print(f"[Inspect] Received {len(paths)} image(s) at {datetime.now().isoformat()}", flush=True)
        user_id = user.get("uid") if user else None

        if x_progress_token:
            progress_store.create(x_progress_token)
            progress_store.append(x_progress_token, {"stage": "upload", "ts": time.time()})

        def _run():
            cb = None
            if x_progress_token:
                def cb(payload):
                    progress_store.append(x_progress_token, payload)
            return inspection_service.run_inspection(
                paths, user_id, None, None, normalized, progress_cb=cb)

        result = await run_in_thread(_run)
        return JSONResponse(content=result)
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        return Response(
            status_code=500,
            content=json.dumps({"status": "ERROR", "message": str(e)}),
            media_type="application/json",
        )


@router.get("/inspect/progress/{token}")
async def get_inspection_progress(token: str):
    """Live per-stage progress for a running /api/inspect request (polled by
    the UI). Returns any events emitted so far; the final 'done' event carries
    the inspection_id."""
    events = progress_store.get(token)
    if events is None:
        return JSONResponse({"events": [], "running": False})
    return JSONResponse({"events": events, "running": True})


async def run_in_thread(func, *args):
    import asyncio
    return await asyncio.to_thread(func, *args)


@router.post("/inspect/report")
async def generate_report(
    images: List[UploadFile] = File(...),
    label_types: List[str] = Form(default=None),
    user=Depends(optional_auth),
):
    """Run an inspection (optionally label-type-routed) and return a PDF report."""
    try:
        paths = await _save_uploads(images)
        if label_types and len(label_types) != len(paths):
            raise HTTPException(400, "label_types must have one entry per image")
        normalized = [t.lower() for t in label_types] if label_types else None
        user_id = user.get("uid") if user else None
        result = await run_in_thread(
            inspection_service.run_inspection, paths, user_id, None, None, normalized)
        if result["status"] == "ERROR":
            raise HTTPException(500, result.get("message", "Inspection failed"))

        pdf_bytes = _build_pdf(result)
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=LegalMatrix-Report-{result['inspection_id']}.pdf"
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Report generation failed: {e}")


@router.get("/inspect/{inspection_id}/report")
async def stored_inspection_report(
    inspection_id: str,
    user=Depends(optional_auth),
):
    """PDF report built from the STORED inspection row (fast, includes manual
    overrides). This is the post-correction report: it renders the saved
    corrected declarations instead of re-running OCR from scratch."""
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, f"Inspection {inspection_id} not found")
    _require_access(user, inspection)
    inspection["status"] = inspection.get("status") or "REVIEW_REQUIRED"
    # Stored rows keep the hash in a column and photos in `images`; rebuild the
    # `evidence` dict the PDF builder expects.
    inspection.setdefault("evidence", {}).update({
        "hash": inspection.get("evidence_hash", ""),
        "images": inspection.get("images", []),
    })
    try:
        pdf_bytes = await run_in_thread(_build_pdf, inspection)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(500, f"Report generation failed: {e}")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=LegalMatrix-Report-{inspection_id}.pdf"
        },
    )


@router.get("/inspect/verify")
def verify_inspection(
    inspection_id: str,
    hash: Optional[str] = Query(None, description="Expected evidence SHA-256 from the certificate QR"),
    user=Depends(optional_auth),
):
    """Tamper-evident verification: a certificate QR encodes
    ``<inspection_id>|<evidence_hash>``. This endpoint confirms the
    inspection exists and whether the stored evidence hash matches."""
    # A QR payload arrives as "id|hash" in one param — split first so the
    # lookup uses the bare inspection id.
    id_part = inspection_id
    hash_part = hash
    if "|" in inspection_id:
        id_part, maybe_hash = inspection_id.split("|", 1)
        if not hash_part and maybe_hash:
            hash_part = maybe_hash
    inspection = inspection_repo.get_inspection(id_part)
    if not inspection:
        raise HTTPException(404, "Certificate not found")
    stored_hash = (
        ((inspection.get("evidence") or {}).get("hash"))
        or inspection.get("evidence_hash")
        or ""
    )
    return {
        "found": True,
        "inspection_id": id_part,
        "product_name": inspection.get("product_name"),
        "manufacturer": inspection.get("manufacturer"),
        "status": inspection.get("status"),
        "compliance_score": inspection.get("compliance_score"),
        "created_at": inspection.get("created_at"),
        "evidence_hash": stored_hash,
        "hash_match": bool(hash_part) and stored_hash == hash_part,
    }


@router.get("/inspect/{inspection_id}")
async def get_inspection(inspection_id: str, user=Depends(optional_auth)):
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, f"Inspection {inspection_id} not found")
    _require_access(user, inspection)
    return inspection


@router.patch("/inspect/{inspection_id}")
async def override_inspection(
    inspection_id: str,
    payload: Dict,
    user=Depends(require_roles("ADMIN", "INSPECTOR")),
):
    """Manually correct extracted declaration values (e.g. a wrong OCR / LLM
    reading). Rules are re-evaluated on the corrected declarations; the
    original AI values are preserved in meta.manual_overrides."""
    user_id = user.get("uid") if user else None
    overrides = payload.get("overrides") or payload
    if not isinstance(overrides, dict) or not overrides:
        raise HTTPException(400, "Provide 'overrides' as a JSON object of field -> corrected value")
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, f"Inspection {inspection_id} not found")
    _require_access(user, inspection)
    try:
        updated = await run_in_thread(
            inspection_service.apply_manual_overrides, inspection_id, overrides, user_id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return updated


@router.get("/inspect/{inspection_id}/evidence/{index}")
async def get_evidence_image(
    inspection_id: str,
    index: int,
    user=Depends(require_roles("ADMIN", "INSPECTOR", "VIEWER")),
):
    """Serve a stored evidence photo for an inspection."""
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, "Inspection not found")
    _require_access(user, inspection)
    images = inspection.get("images", [])
    if not 0 <= index < len(images):
        raise HTTPException(404, "Evidence image not found")
    filename = images[index].get("filename", "")
    evidence_root = get_evidence_dir().resolve()
    candidate = (evidence_root / filename).resolve()
    if not str(candidate).startswith(str(evidence_root)) or not candidate.exists():
        raise HTTPException(404, "Evidence image not found")
    return FileResponse(str(candidate))


def _serve_stored_file(inspection_id: str, rel_dir: str, filename: str, media_type: str, error_msg: str = "File not found"):
    """Safe FileResponse within the evidence root (blocks path traversal)."""
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, "Inspection not found")
    evidence_root = get_evidence_dir().resolve()
    candidate = (evidence_root / rel_dir / filename).resolve()
    if not str(candidate).startswith(str(evidence_root)) or not candidate.exists():
        raise HTTPException(404, error_msg)
    return FileResponse(str(candidate), media_type=media_type)


@router.get("/inspect/{inspection_id}/heatmap/{index}")
async def get_heatmap(
    inspection_id: str,
    index: int,
    user=Depends(optional_auth),
):
    """Serve the compliance heat-map overlay for a photo of an inspection."""
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, "Inspection not found")
    _require_access(user, inspection)
    heatmap = next((h for h in inspection.get("heatmaps", []) if h.get("image_index") == index), None)
    if not heatmap:
        raise HTTPException(404, "Heat-map not found")
    return await to_thread_static(_serve_stored_file, inspection_id, "heatmaps", heatmap["filename"], "image/jpeg")


@router.get("/inspect/{inspection_id}/certificate")
async def get_certificate(
    inspection_id: str,
    user=Depends(optional_auth),
):
    """Download a tamper-evident compliance certificate (PDF) for a result."""
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, "Inspection not found")
    _require_access(user, inspection)
    from app.services.certificate_generator import build_certificate
    from app.config import FRONTEND_URL
    pdf_bytes = await run_in_thread(
        build_certificate, inspection, f"{FRONTEND_URL}/verify?inspection_id="
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=LegalMatrix-Certificate-{inspection_id}.pdf"},
    )


async def to_thread_static(func, *args):
    return await run_in_thread(func, *args)


@router.get("/inspect")
async def list_inspections(
    limit: int = 50,
    user=Depends(require_roles("ADMIN", "INSPECTOR", "VIEWER")),
):
    """History list. ADMIN sees every inspection; INSPECTOR / VIEWER only see
    scans they created (own-user isolation)."""
    limit = min(limit, 200)
    if user.get("role") == "ADMIN":
        return inspection_repo.list_inspections(limit=limit)
    return inspection_repo.list_inspections_by_user(int(user.get("uid") or -1), limit=limit)


@router.get("/inspect/{inspection_id}/export")
async def export_inspection(
    inspection_id: str,
    format: str = "json",
    user=Depends(require_roles("ADMIN", "INSPECTOR", "VIEWER")),
):
    """Export a stored inspection as JSON or CSV (editable formats)."""
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, "Inspection not found")
    _require_access(user, inspection)

    if format == "json":
        return JSONResponse(
            content={"inspection": inspection},
            headers={"Content-Disposition": f"attachment; filename={inspection_id}.json"},
        )

    if format == "csv":
        import csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["field", "value", "declared", "rule_no", "severity"])
        writer.writerow(["rule_version",
                         str(inspection.get("rule_version") or inspection.get("meta", {}).get("rule_version", "n/a")),
                         "YES", "", ""])
        declarations = inspection.get("declarations", {})
        for key, value in declarations.items():
            writer.writerow([key, value, "YES" if value else "NO", "", ""])
        for v in inspection.get("violations", []):
            writer.writerow([
                v.get("field", ""), v.get("extracted_value", ""),
                "NO" if v.get("status") == "MISSING" else "YES",
                v.get("rule_no", ""), v.get("severity", ""),
            ])
        csv_bytes = buf.getvalue().encode("utf-8")
        return Response(
            content=csv_bytes,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f"attachment; filename={inspection_id}.csv"},
        )

    raise HTTPException(400, "format must be 'json' or 'csv'")


@router.delete("/inspect/{inspection_id}")
async def delete_inspection(
    inspection_id: str,
    user=Depends(require_roles("ADMIN")),
):
    """Administratively delete a stored inspection (admin-only).

    Removes the inspection row and its image rows (CASCADE). Evidence files on
    disk are content-addressed (sha256 filenames) and may be shared across
    inspections, so they are intentionally retained.
    """
    deleted = inspection_repo.delete_inspection(inspection_id)
    if not deleted:
        raise HTTPException(404, "Inspection not found")
    return {"deleted": True, "inspection_id": inspection_id}


# ── PDF generation ─────────────────────────────────────────────────────────

FONT_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_DEVA_FONT = FONT_DIR / "Hind-Regular.ttf"
_DEVA_FONT_BOLD = FONT_DIR / "Hind-Bold.ttf"
_DEVA_RE = re.compile(r"[\u0900-\u097f]")


def _sanitize(text: str) -> str:
    """Normalize text for PDF rendering; keep Unicode (font routing handles scripts)."""
    if not text:
        return ""
    return (str(text)
        .replace('\u20b9', 'Rs.')
        .replace('\u2018', "'").replace('\u2019', "'")
        .replace('\u201c', '"').replace('\u201d', '"')
        .replace('\u2013', '-').replace('\u2014', '-')
        .replace('\u00b1', '+/-')
        .replace('\ufffd', '?')
        .replace('\r', ' ').replace('\n', ' '))


def _font_for(text) -> str:
    return "Deva" if text and _DEVA_RE.search(str(text)) else "Helvetica"


def _set_font(pdf, text, style, size, family=None):
    pdf.set_font(family or _font_for(text), style, size)


def _sha8(path) -> str:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()[:10]
    except OSError:
        return "n/a"


class _ReportPDF(FPDF):
    """A4 legal-metrology report with a page-number footer."""

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(200, 200, 200)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_font("Helvetica", "", 6.5)
        self.set_text_color(150, 150, 150)
        self.cell(0, 4,
                  "LegalMatrix  |  AI-generated compliance report  |  Page "
                  + str(self.page_no()) + " of {nb}",
                  new_x="LMARGIN", new_y="NEXT", align="C")


def _section(pdf, title, color=(37, 99, 235)):
    pdf.ln(2.2)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 6, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*color)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(1.6)


def _meta_cell(pdf, label, value, w) -> float:
    """Two-line meta cell (label over value). Returns the cell bottom y."""
    x0, y0 = pdf.get_x(), pdf.get_y()
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_text_color(140, 140, 140)
    pdf.set_xy(x0, y0)
    pdf.cell(w, 2.4, label, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    _set_font(pdf, value, "", 8.5)
    pdf.set_xy(x0, y0 + 2.4)
    pdf.multi_cell(w - 1, 3.3, _sanitize(value), new_x="RIGHT", new_y="NEXT")
    return pdf.get_y()


def _stat_box(pdf, w, title, value, fill):
    x0, y0 = pdf.get_x(), pdf.get_y()
    pdf.set_fill_color(*fill)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8.5)
    pdf.set_xy(x0, y0)
    pdf.multi_cell(w, 3.6, f"{title}\n{value}", border=1, align="C", fill=True,
                   new_x="LMARGIN", new_y="TOP")
    pdf.set_xy(x0 + w, y0)


def _table_row(pdf, cells, widths, row_fill=(255, 255, 255), cell_fills=None):
    """cells: (text, style, size, color) per column; cell_fills: per-col RGB or None."""
    x0, y0 = pdf.get_x(), pdf.get_y()
    max_h = 5.0
    for i, (txt, style, size, color) in enumerate(cells):
        pdf.set_xy(x0 + sum(widths[:i]), y0)
        _set_font(pdf, txt, style, size)
        pdf.set_text_color(*color)
        fill = row_fill
        if cell_fills and i < len(cell_fills) and cell_fills[i]:
            fill = cell_fills[i]
        pdf.set_fill_color(*fill)
        pdf.multi_cell(widths[i], 3.9, txt, border=1, align="L", fill=True,
                       new_x="LMARGIN", new_y="NEXT")
        bottom = pdf.get_y()
        if bottom - y0 > max_h:
            max_h = bottom - y0
    pdf.set_y(y0 + max_h)
    pdf.set_x(pdf.l_margin)


def _build_pdf(result: Dict) -> bytes:
    from app.config import OCR_ENGINE, FIELD_CLASSIFIER_MODEL, OCR_LANG

    pdf = _ReportPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(12, 12, 12)
    if _DEVA_FONT.exists():
        pdf.add_font("Deva", "", str(_DEVA_FONT))
        pdf.add_font("Deva", "B", str(_DEVA_FONT_BOLD) if _DEVA_FONT_BOLD.exists() else str(_DEVA_FONT))
    pdf.add_page()
    pdf.alias_nb_pages()

    usable = pdf.w - pdf.l_margin - pdf.r_margin
    status = result["status"]
    status_colors = {
        "COMPLIANT": (22, 163, 74),
        "REVIEW_REQUIRED": (234, 179, 8),
        "POTENTIAL_VIOLATION": (220, 38, 38),
    }
    sc = status_colors.get(status, (100, 100, 100))
    evidence = result.get("evidence", {})
    meta = result.get("meta") or {}

    # ── Header ──
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(0, 10, "LegalMatrix", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 5, "AI-Powered Legal Metrology Compliance Report",
             new_x="LMARGIN", new_y="NEXT", align="C")
    chip_w = pdf.get_string_width(status) + 12
    pdf.set_fill_color(*sc)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_x((pdf.w - chip_w) / 2)
    pdf.cell(chip_w, 6, f"  {status}  ", new_x="LMARGIN", new_y="NEXT", align="C", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    # ── Inspection meta (2-col grid) ──
    ts = result.get("timestamp") or result.get("created_at") or ""
    try:
        ts_disp = datetime.fromisoformat(ts).strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        ts_disp = str(ts)
    engine = meta.get("ocr_engine") or result.get("ocr_engine") or OCR_ENGINE
    classifier = meta.get("classifier") or result.get("classifier") or FIELD_CLASSIFIER_MODEL
    half = usable / 2
    meta_rows = [
        ("Inspection ID", str(result.get("inspection_id", "-")), "Date & Time", ts_disp),
        # Fresh pipeline results use images_processed/method; stored rows keep
        # the column names images_count/model — accept both.
        ("Images Processed", str(result.get("images_processed") or result.get("images_count") or "-"),
         "Method", str(result.get("method") or result.get("model") or "-")),
        ("OCR Engine", f"{engine} (lang {OCR_LANG})", "Classifier", str(classifier)),
        ("Evidence SHA-256", (evidence.get("hash", "n/a") or "n/a")[:20], "Rules Version", str(result.get("rule_version", "n/a"))),
    ]
    for k1, v1, k2, v2 in meta_rows:
        y0 = pdf.get_y()
        pdf.set_x(pdf.l_margin)
        b1 = _meta_cell(pdf, k1, v1, half)
        pdf.set_xy(pdf.l_margin + half, y0)
        b2 = _meta_cell(pdf, k2, v2, half)
        pdf.set_xy(pdf.l_margin, max(b1, b2) + 0.9)

    # ── Compliance strip ──
    score = result.get("compliance_score", 0)
    passed = result.get("passed_count", 0)
    total = result.get("total_rules", 0)
    conf = result.get("extraction_confidence") or {}
    overall_conf = conf.get("overall")
    box = usable / 3
    _stat_box(pdf, box, "COMPLIANCE SCORE", f"{score}%", sc)
    _stat_box(pdf, box, "RULES PASSED", f"{passed}/{total}", (37, 99, 235))
    _stat_box(pdf, box, "EXTRACTION CONFIDENCE",
              f"{overall_conf}%" if overall_conf is not None else "n/a", (100, 116, 139))
    pdf.set_text_color(0, 0, 0)
    pdf.set_xy(pdf.l_margin, pdf.get_y() + 8.6)
    pdf.ln(1.5)

    # ── Declarations table ──
    _section(pdf, "Extracted Declarations & Evidence")
    pdf.set_draw_color(170, 185, 200)
    field_labels = {
        "mrp": "MRP", "usp": "Unit Sale Price", "net_quantity": "Net Quantity",
        "product_name": "Product Name", "manufacturer": "Manufacturer",
        "manufacturer_address": "Manufacturer Address",
        "manufacturing_date": "Mfg Date", "expiry_date": "Expiry Date",
        "consumer_care": "Consumer Care", "dimensions": "Dimensions",
    }
    declarations = result.get("declarations", {})
    field_evidence = result.get("field_evidence", {})
    # manual_overrides sits at meta level on a fresh run, but _row_to_dict
    # flattens meta_json to the top level on a stored row — accept both.
    overrides = meta.get("manual_overrides") or result.get("manual_overrides") or {}
    widths = [30, 58, 72, 26]
    status_chip = {
        "OK": (22, 163, 74), "OVERRIDDEN": (217, 119, 6), "NOT DETECTED": (185, 28, 28),
    }
    _table_row(
        pdf,
        [("Field", "B", 7, (255, 255, 255)), ("Declared Value", "B", 7, (255, 255, 255)),
         ("Evidence (source: text)", "B", 7, (255, 255, 255)), ("Status", "B", 7, (255, 255, 255))],
        widths,
        row_fill=(37, 99, 235),
    )
    for i, (key, label) in enumerate(field_labels.items()):
        val = _sanitize(declarations.get(key, ""))
        ev = field_evidence.get(key) or {}
        ev_text = _sanitize(ev.get("text", ""))
        ev_src = ev.get("source", "")
        ev_disp = (f"{ev_src}: {ev_text}" if ev_src and ev_text else (ev_src or ev_text))[:60]
        if key in overrides:
            st, status_name = status_chip["OVERRIDDEN"], "OVERRIDDEN"
            val_disp = _sanitize(overrides[key].get("corrected", val))
        elif not val and not ev_disp:
            st, status_name = status_chip["NOT DETECTED"], "NOT DETECTED"
            val_disp = "-"
        else:
            st, status_name = status_chip["OK"], "OK"
            val_disp = val or ev_disp
        _table_row(
            pdf,
            [
                (label, "B", 7.5, (30, 30, 30)),
                (val_disp, "", 7.5, (20, 20, 20)),
                (ev_disp, "", 7, (120, 120, 120)),
                (status_name, "B", 7, (255, 255, 255)),
            ],
            widths,
            row_fill=(243, 247, 255) if i % 2 else (255, 255, 255),
            cell_fills=[None, None, None, st],
        )
    pdf.set_draw_color(37, 99, 235)
    fields_present = conf.get("fields_present")
    fields_required = conf.get("fields_required")
    coverage = conf.get("coverage_ratio")
    if fields_present is not None:
        pct = f" ({coverage * 100:.0f}%)" if coverage is not None else ""
        pdf.set_font("Helvetica", "I", 7.5)
        pdf.set_text_color(120, 120, 120)
        pdf.cell(0, 4, f"Extraction coverage: {fields_present}/{fields_required} key fields{pct}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    # ── Manual overrides audit trail ──
    if overrides:
        _section(pdf, "Manual Overrides (audit trail)", (217, 119, 6))
        for key, ov in overrides.items():
            ov = ov or {}
            label = field_labels.get(key, key)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_text_color(0, 0, 0)
            pdf.cell(0, 5, f"{label}:  {_sanitize(ov.get('corrected', ''))}",
                     new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 7)
            pdf.set_text_color(120, 120, 120)
            who = ov.get("by_user_id", "-")
            at = str(ov.get("at", "-"))[:19]
            prev = _sanitize(ov.get("original", "")) or "-"
            pdf.cell(0, 4, f"Original AI value: {prev}   |   Corrected by user id {who} on {at}",
                     new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.5)

    # ── Font measurement ──
    fm = result.get("font_measurement") or {}
    fm_status = fm.get("status")
    if fm_status:
        _section(pdf, "Font Measurement (Rule 4(1))")
        meas = fm.get("measured_mm")
        req = fm.get("required_mm")
        unc = fm.get("uncertainty")
        line = (f"Measured: {meas if meas is not None else 'n/a'} mm   |   "
                f"Required: {req if req is not None else 'n/a'} mm   |   "
                f"Uncertainty: +/-{unc if unc is not None else 'n/a'} mm")
        _set_font(pdf, line, "", 8.5)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
        fm_color = {"COMPLIANT": (22, 163, 74), "REVIEW_REQUIRED": (234, 179, 8),
                    "CANNOT_MEASURE": (100, 100, 100), "POTENTIAL_VIOLATION": (220, 38, 38)}
        pdf.set_text_color(*fm_color.get(fm_status, (100, 100, 100)))
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(0, 5, f"Font Status: {fm_status}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    # ── Violations / rules ──
    violations = result.get("violations", [])
    if violations:
        _section(pdf, f"Rule Violations ({len(violations)})", (220, 38, 38))
        sev_color = {"CRITICAL": (185, 28, 28), "HIGH": (234, 88, 12),
                     "MEDIUM": (217, 119, 6), "LOW": (100, 100, 100)}
        for v in violations:
            sev = v.get("severity", "HIGH")
            rule_label = f"{v.get('rule_no', 'N/A')} - {v.get('rule_id', '').replace('_', ' ').title()}"
            pdf.set_fill_color(*sev_color.get(sev, (100, 100, 100)))
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 7)
            pdf.cell(18, 5, f" {sev}", new_x="RIGHT", new_y="LAST", fill=True)
            pdf.set_text_color(0, 0, 0)
            extracted = _sanitize(v.get("extracted_value", ""))
            suffix = f"  |  Found: {extracted[:40]}" if extracted else ""
            pdf.set_font("Helvetica", "B", 8.5)
            pdf.cell(0, 5, f"  {rule_label}{suffix}", new_x="LMARGIN", new_y="NEXT")
            desc = _sanitize(v.get("description", ""))
            if desc:
                _set_font(pdf, desc, "", 7.5)
                pdf.set_text_color(90, 90, 90)
                pdf.set_x(pdf.l_margin + 3)
                pdf.multi_cell(0, 3.6, desc, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
            pdf.ln(1)
    else:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(22, 163, 74)
        pdf.ln(2)
        pdf.cell(0, 5, "No rule violations - all checked declarations are compliant.",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    # ── Evidence photos (2-up) ──
    images = evidence.get("images", [])
    if images:
        _section(pdf, "Product Photographs / Evidence")
        img_w = 88.0
        gap = 4.0
        for idx in range(0, len(images), 2):
            pair = images[idx:idx + 2]
            dims = []
            for item in pair:
                p = get_evidence_dir() / item["filename"]
                hgt = img_w
                if p.exists():
                    try:
                        with Image.open(p) as im:
                            iw, ih = im.size
                            if iw:
                                hgt = img_w * ih / iw
                    except Exception:
                        pass
                dims.append(hgt)
            row_h = max(dims) if dims else img_w
            y0 = pdf.get_y()
            if y0 + row_h + 4 > pdf.h - 18:
                pdf.add_page()
                y0 = pdf.get_y()
            x = pdf.l_margin
            for item, hgt in zip(pair, dims):
                img_path = get_evidence_dir() / item["filename"]
                if img_path.exists():
                    pdf.image(str(img_path), x=x, y=y0, w=img_w, h=hgt)
                pdf.set_font("Helvetica", "I", 7)
                pdf.set_text_color(110, 110, 110)
                pdf.set_xy(x, y0 + hgt + 0.6)
                name = _sanitize(item.get("original_name", ""))[:38]
                hash_txt = _sha8(img_path) if img_path.exists() else "missing"
                pdf.cell(img_w, 3, f"{name}  [{hash_txt}]", new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                x += img_w + gap
            pdf.set_y(y0 + row_h + 5)

    return pdf.output()