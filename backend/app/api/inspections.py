import io
import json
import tempfile
from datetime import datetime
from typing import List, Dict, Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse, Response, FileResponse

from app.config import get_evidence_dir
from app.repositories import inspections as inspection_repo
from app.services import inspection_service
from app.services.auth_service import optional_auth, require_roles

from fpdf import FPDF

router = APIRouter()


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
    user=Depends(optional_auth),
):
    """Run a compliance inspection on 1-6 product label images and persist it.

    ``label_types`` is optional and aligned with ``images`` — one of
    front/back/side/top/other per photo (e.g. front label = PDP, back label =
    declaration block, top = cap/roof face). When present, each field is routed
    to the photo whose label type is its strongest source; absent/unknown
    entries fall back to the original best-photo heuristics.
    """
    try:
        paths = await _save_uploads(images)
        if label_types and len(label_types) != len(paths):
            raise HTTPException(400, "label_types must have one entry per image")
        normalized = [t.lower() for t in label_types] if label_types else None
        print(f"[Inspect] Received {len(paths)} image(s) at {datetime.now().isoformat()}", flush=True)
        user_id = user.get("uid") if user else None
        result = await run_in_thread(
            inspection_service.run_inspection, paths, user_id, None, None, normalized)
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


@router.get("/inspect/{inspection_id}")
async def get_inspection(inspection_id: str, user=Depends(optional_auth)):
    inspection = inspection_repo.get_inspection(inspection_id)
    if not inspection:
        raise HTTPException(404, f"Inspection {inspection_id} not found")
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
    from app.services.certificate_generator import build_certificate
    pdf_bytes = await run_in_thread(build_certificate, inspection, "/inspect/verify?inspection_id=")
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
    return inspection_repo.list_inspections(limit=min(limit, 200))


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


# ── PDF generation ─────────────────────────────────────────────────────────

def _sanitize(text: str) -> str:
    if not text:
        return ""
    return (text
        .replace('\u20b9', 'Rs.')
        .replace('\u2018', "'").replace('\u2019', "'")
        .replace('\u201c', '"').replace('\u201d', '"')
        .replace('\u2013', '-').replace('\u2014', '-')
        .replace('\u00b1', '+/-')
        .encode('latin-1', errors='replace')
        .decode('latin-1'))


def _build_pdf(result: Dict) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 22)
    pdf.set_text_color(37, 99, 235)
    pdf.cell(0, 12, "LegalMatrix", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, "AI-Powered Legal Metrology Compliance Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    # Inspection info
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 7, "Inspection Details", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(37, 99, 235)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    status = result["status"]
    compliance = result
    evidence = result.get("evidence", {})
    info = [
        ("Inspection ID", result["inspection_id"]),
        ("Date & Time", result["timestamp"]),
        ("Images Processed", str(result["images_processed"])),
        ("Model", result.get("method", "")),
        ("Evidence SHA-256", (evidence.get("hash") or "")[:40] + "..." if evidence.get("hash") else "N/A"),
    ]
    for label, value in info:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(40, 6, label + ":", new_x="RIGHT", new_y="LAST")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, _sanitize(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    score = result.get("compliance_score", 0)
    passed = result.get("passed_count", 0)
    total = result.get("total_rules", 0)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Compliance Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    if score >= 80:
        pdf.set_text_color(22, 163, 74)
    elif score >= 50:
        pdf.set_text_color(234, 179, 8)
    else:
        pdf.set_text_color(220, 38, 38)

    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, f"Compliance Score: {score}%", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"Status: {status}  |  Rules Passed: {passed}/{total}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    status_colors = {"COMPLIANT": (22, 163, 74), "REVIEW_REQUIRED": (234, 179, 8), "POTENTIAL_VIOLATION": (220, 38, 38)}
    sc = status_colors.get(status, (100, 100, 100))
    pdf.set_fill_color(*sc)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(60, 8, f"  {status}", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Extraction confidence (resource-adaptive cascade auditability)
    conf = result.get("extraction_confidence") or {}
    if conf.get("overall") is not None:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Extraction Confidence", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(37, 99, 235)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        overall = float(conf["overall"])
        corr = (22, 163, 74) if overall >= 70 else ((234, 179, 8) if overall >= 40 else (220, 38, 38))
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*corr)
        pdf.cell(0, 8, f"{overall:.0f}%", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(70, 70, 70)
        pdf.cell(0, 5,
                 f"Fields present: {conf.get('fields_present', '—')} / "
                 f"{conf.get('fields_required', '—')}  |  "
                 f"Coverage ratio: {conf.get('coverage_ratio', '—')}",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(3)

    # Evidence images
    images = evidence.get("images", [])
    if images:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Photographs / Evidence", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(200, 200, 200)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        for item in images:
            img_path = get_evidence_dir() / item["filename"]
            if img_path.exists():
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(90, 90, 90)
                pdf.cell(0, 5, _sanitize(item["original_name"]), new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                avail_w = pdf.w - pdf.l_margin - pdf.r_margin
                pdf.image(str(img_path), x=None, y=None, w=min(avail_w, 90))
                pdf.ln(2)
        pdf.ln(2)

    # Extracted Declarations
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Extracted Declarations", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(37, 99, 235)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)

    field_labels = {
        "mrp": "MRP", "usp": "Unit Sale Price", "net_quantity": "Net Quantity",
        "product_name": "Product Name", "manufacturer": "Manufacturer",
        "manufacturing_date": "Mfg Date", "expiry_date": "Expiry Date",
        "consumer_care": "Consumer Care", "dimensions": "Dimensions",
    }
    declarations = result.get("declarations", {})
    field_evidence = result.get("field_evidence", {})
    for key, label in field_labels.items():
        val = declarations.get(key, "")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(40, 6, _sanitize(label) + ":", new_x="RIGHT", new_y="LAST")
        if val:
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(22, 163, 74)
            pdf.cell(0, 6, _sanitize(val), new_x="LMARGIN", new_y="NEXT")
            ev = field_evidence.get(key, {})
            src = ev.get("source", "")
            txt = ev.get("text", "")
            if src or txt:
                pdf.set_text_color(120, 120, 120)
                pdf.set_font("Helvetica", "I", 7)
                src_label = f"[via {src}] " if src else ""
                pdf.cell(40, 4, "", new_x="RIGHT", new_y="LAST")
                pdf.multi_cell(0, 4, f'{src_label}"{_sanitize(txt)}"',
                               new_x="LMARGIN", new_y="NEXT")
        else:
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(220, 38, 38)
            pdf.cell(0, 6, "NOT DETECTED", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
    pdf.ln(4)

    # Font measurement
    fm = result.get("font_measurement")
    if fm:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Font Size & Readability", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(37, 99, 235)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        fm_status = fm.get("status", "N/A")
        fm_color = {
            "COMPLIANT": (22, 163, 74), "POTENTIAL_VIOLATION": (220, 38, 38),
            "REVIEW_REQUIRED": (234, 179, 8),
        }.get(fm_status, (100, 100, 100))
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6,
                 f"Measured: {fm.get('measured_mm')} mm   Required: "
                 f"{fm.get('required_mm') if fm.get('required_mm') is not None else 'n/a'} mm   "
                 f"Uncertainty: +/-{fm.get('uncertainty')} mm",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*fm_color)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, f"Font Status: {fm_status}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

    # Violations
    violations = result.get("violations", [])
    if violations:
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, f"Rule Violations ({len(violations)})", new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(220, 38, 38)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)
        for v in violations:
            sev = v.get("severity", "HIGH")
            sev_color = {"CRITICAL": (220, 38, 38), "HIGH": (234, 88, 12), "MEDIUM": (234, 179, 8), "LOW": (100, 100, 100)}
            rgb = sev_color.get(sev, (100, 100, 100))
            pdf.set_fill_color(*rgb)
            pdf.set_text_color(255, 255, 255)
            pdf.set_font("Helvetica", "B", 8)
            pdf.cell(18, 5, f" {sev}", new_x="RIGHT", new_y="LAST", fill=True)
            pdf.set_text_color(0, 0, 0)
            pdf.set_font("Helvetica", "B", 9)
            rule_label = _sanitize(f"{v.get('rule_no', 'N/A')} - {v.get('rule_id', '').replace('_', ' ').title()}")
            pdf.cell(0, 5, f"  {rule_label}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(60, 60, 60)
            desc = _sanitize(v.get("description", ""))
            if desc:
                pdf.multi_cell(0, 4, f"  {desc}", new_x="LMARGIN", new_y="NEXT")
            if v.get("extracted_value"):
                pdf.set_font("Helvetica", "I", 8)
                pdf.cell(0, 4, f"  Extracted: {_sanitize(v['extracted_value'])}", new_x="LMARGIN", new_y="NEXT")
            rem = _sanitize(v.get("remediation", ""))
            if rem:
                pdf.set_font("Helvetica", "I", 8)
                pdf.set_text_color(37, 99, 235)
                pdf.multi_cell(0, 4, f"  Fix: {rem}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
    else:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(22, 163, 74)
        pdf.cell(0, 7, "No Rule Violations - All Declarations Compliant", new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(0, 0, 0)

    pdf.ln(6)
    pdf.set_draw_color(200, 200, 200)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.multi_cell(0, 4,
        "This report is AI-generated by LegalMatrix for informational purposes only. "
        "Legal Metrology (Packaged Commodities) Rules, 2011 with amendments through 2026. "
        "Generated: " + datetime.now().strftime("%d %B %Y, %I:%M %p"),
        new_x="LMARGIN", new_y="NEXT", align="C",
    )

    return pdf.output()