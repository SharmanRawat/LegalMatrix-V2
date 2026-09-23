"""Inspection repository — persistence for scans, compliance results and evidence."""
import json

from app.database.connection import get_connection
from app.services.clock import now_ist


def _now() -> str:
    return now_ist().isoformat()


def save_inspection(inspection: dict, db_path=None) -> str:
    """Insert a completed inspection. Returns its id."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO inspections "
                "(id, product_name, manufacturer, status, compliance_score, "
                " passed_count, total_rules, declarations_json, missing_json, "
                " violations_json, misleading_json, meta_json, evidence_hash, images_count, "
                " model, user_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    inspection["id"],
                    inspection.get("product_name") or None,
                    inspection.get("manufacturer") or None,
                    inspection["status"],
                    inspection.get("compliance_score", 0),
                    inspection.get("passed_count", 0),
                    inspection.get("total_rules", 0),
                    json.dumps(inspection.get("declarations", {})),
                    json.dumps(inspection.get("missing_declarations", [])),
                    json.dumps(inspection.get("violations", [])),
                    json.dumps(inspection.get("misleading_checks", [])),
                    json.dumps(inspection.get("meta", {})),
                    inspection.get("evidence_hash", ""),
                    inspection.get("images_count", 0),
                    inspection.get("model", ""),
                    inspection.get("user_id"),
                    inspection.get("timestamp") or _now(),
                ),
            )
        return inspection["id"]
    finally:
        conn.close()


def add_inspection_image(inspection_id: str, filename: str, original_name: str, sha256: str,
                         sort_order: int, db_path=None) -> None:
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO inspection_images "
                "(inspection_id, filename, original_name, sha256, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (inspection_id, filename, original_name, sha256, sort_order),
            )
    finally:
        conn.close()


def update_inspection_overrides(
    inspection_id: str,
    declarations: dict,
    status: str,
    compliance: dict,
    missing_declarations: list,
    misleading_checks: list,
    meta: dict,
    db_path=None,
) -> None:
    """Persist corrected declarations after a manual override, re-evaluating
    status / compliance in the service layer first."""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE inspections SET "
                " product_name = ?, manufacturer = ?, status = ?, "
                " compliance_score = ?, passed_count = ?, total_rules = ?, "
                " declarations_json = ?, missing_json = ?, violations_json = ?, "
                " misleading_json = ?, meta_json = ? "
                "WHERE id = ?",
                (
                    (declarations.get("product_name") or None),
                    (declarations.get("manufacturer") or None),
                    status,
                    compliance.get("compliance_score", 0),
                    compliance.get("passed_count", 0),
                    compliance.get("total_rules", 0),
                    json.dumps(declarations, ensure_ascii=False),
                    json.dumps(missing_declarations, ensure_ascii=False),
                    json.dumps(compliance.get("violations", []), ensure_ascii=False),
                    json.dumps(misleading_checks, ensure_ascii=False),
                    json.dumps(meta, ensure_ascii=False),
                    inspection_id,
                ),
            )
    finally:
        conn.close()


def _row_to_dict(row) -> dict:
    d = dict(row)
    d["inspection_id"] = d["id"]
    d["declarations"] = json.loads(d.pop("declarations_json") or "{}")
    d["missing_declarations"] = json.loads(d.pop("missing_json") or "[]")
    d["violations"] = json.loads(d.pop("violations_json") or "[]")
    d["misleading_checks"] = json.loads(d.pop("misleading_json") or "[]")
    if "meta_json" in d:
        meta = json.loads(d.pop("meta_json") or "{}")
        d.update(meta)
    return d


def get_inspection(inspection_id: str, db_path=None):
    conn = get_connection(db_path)
    try:
        row = conn.execute(
            "SELECT * FROM inspections WHERE id = ?", (inspection_id,)
        ).fetchone()
        inspection = _row_to_dict(row) if row else None
        if inspection:
            img_rows = conn.execute(
                "SELECT filename, original_name, sha256, sort_order "
                "FROM inspection_images WHERE inspection_id = ? ORDER BY sort_order",
                (inspection_id,),
            ).fetchall()
            inspection["images"] = [dict(r) for r in img_rows]
        return inspection
    finally:
        conn.close()


def list_inspections(limit: int = 100, db_path=None):
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM inspections ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_inspections_by_user(user_id: int, limit: int = 100, db_path=None):
    """All inspections run by a given user (for the admin user-audit view)."""
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM inspections WHERE user_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def delete_inspection(inspection_id: str, db_path=None) -> bool:
    """Administratively delete a stored inspection and its image rows.

    Returns True if a row was removed, False if the id did not exist.
    Evidence files on disk are left in place: they are content-addressed
    (sha256-derived filenames) and may be shared with other inspections.
    """
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute("DELETE FROM inspections WHERE id = ?", (inspection_id,))
        return cur.rowcount > 0
    finally:
        conn.close()


def search_inspections(
    q: str = None,
    status: str = None,
    product_name: str = None,
    manufacturer: str = None,
    date_from: str = None,
    date_to: str = None,
    user_id: int = None,
    limit: int = 100,
    offset: int = 0,
    db_path=None,
):
    clauses, params = [], []

    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if q:
        clauses.append(
            "(id LIKE ? OR product_name LIKE ? OR manufacturer LIKE ? "
            "OR declarations_json LIKE ?)"
        )
        like = f"%{q}%"
        params.extend([like, like, like, like])
    if status:
        clauses.append("status = ?")
        params.append(status)
    if product_name:
        clauses.append("product_name LIKE ?")
        params.append(f"%{product_name}%")
    if manufacturer:
        clauses.append("manufacturer LIKE ?")
        params.append(f"%{manufacturer}%")
    if date_from:
        clauses.append("created_at >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("created_at <= ?")
        params.append(date_to)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    conn = get_connection(db_path)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM inspections {where}", params
        ).fetchone()["c"]

        rows = conn.execute(
            f"SELECT * FROM inspections {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
        return {"total": total, "results": [_row_to_dict(r) for r in rows]}
    finally:
        conn.close()


def dashboard_stats(user_id: int = None, db_path=None):
    conn = get_connection(db_path)
    try:
        scope = " WHERE user_id = ?" if user_id is not None else ""
        scope_params = () if user_id is None else (user_id,)
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM inspections{scope}", scope_params
        ).fetchone()["c"]
        by_status = {
            r["status"]: r["c"]
            for r in conn.execute(
                f"SELECT status, COUNT(*) AS c FROM inspections{scope} GROUP BY status",
                scope_params,
            ).fetchall()
        }
        avg_score = conn.execute(
            f"SELECT AVG(compliance_score) AS a FROM inspections{scope}", scope_params
        ).fetchone()["a"]

        recent = conn.execute(
            f"SELECT id, product_name, manufacturer, status, compliance_score, "
            f"images_count, created_at FROM inspections{scope} "
            f"ORDER BY created_at DESC LIMIT 10",
            scope_params,
        ).fetchall()

        violations_raw = conn.execute(
            f"SELECT violations_json FROM inspections{scope}", scope_params
        ).fetchall()
        field_stats: dict[str, dict] = {}
        for row in violations_raw:
            for v in json.loads(row["violations_json"] or "[]"):
                rule_id = v.get("rule_id", "unknown")
                sev = v.get("severity", "HIGH")
                entry = field_stats.setdefault(rule_id, {"count": 0, "severity": sev})
                entry["count"] += 1

        trend_raw = conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS c "
            "FROM inspections" + scope + " GROUP BY day ORDER BY day DESC LIMIT 14",
            scope_params,
        ).fetchall()
        trend = [
            {"date": r["day"], "count": r["c"]}
            for r in reversed(trend_raw)
        ]

        return {
            "total_inspections": total,
            "by_status": by_status,
            "avg_compliance_score": round(float(avg_score), 1) if avg_score else 0.0,
            "recent": [dict(r) for r in recent],
            "field_violations": field_stats,
            "daily_trend": trend,
        }
    finally:
        conn.close()