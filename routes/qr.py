import re
from flask import Blueprint, render_template, request, Response, redirect, url_for, abort
import requests as http_req
from models import get_db, oid
from routes.decorators import role_required

qr_bp = Blueprint("qr", __name__, url_prefix="/qr")

@qr_bp.route("/download")
@qr_bp.route("/download/")
@qr_bp.route("/download/<equipment_id>")
@role_required("custodian", "technician", "admin", "faculty")
def download(equipment_id=None):
    if not equipment_id or str(equipment_id).strip().lower() in ("none", "null", ""):
        return redirect(url_for("qr.print_sheet"))

    eq_oid = oid(equipment_id)
    if not eq_oid:
        return redirect(url_for("qr.print_sheet"))

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT id, id AS _id, name, qr_code FROM equipment WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)",
            (eq_oid,)
        )
        eq = cur.fetchone()

        if not eq:
            cur.close()
            abort(404, "Equipment asset not found.")

        qr_url = eq.get("qr_code")
        if not qr_url:
            from routes.equipment import equipment_scan_public_url, _make_qr_image_url
            scan_url = equipment_scan_public_url(str(eq_oid), request)
            qr_url = _make_qr_image_url(scan_url)
            cur.execute("UPDATE equipment SET qr_code=%s WHERE id=%s", (qr_url, eq_oid))
            db.commit()

        cur.close()
    finally:
        db.close()

    name = re.sub(r'[^a-z0-9_\-]', '_', eq.get("name", "equipment"), flags=re.IGNORECASE)
    filename = f"QR_{name}.png"

    try:
        resp = http_req.get(qr_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        if resp.status_code == 200 and resp.content:
            return Response(
                resp.content,
                mimetype="image/png",
                headers={
                    "Content-Disposition": f'attachment; filename="{filename}"',
                    "Cache-Control": "no-store",
                }
            )
    except Exception:
        pass

    return redirect(qr_url)

@qr_bp.route("/print")
@role_required("custodian", "technician", "admin", "faculty")
def print_sheet():
    filter_ids = []
    ids_param = request.args.get("ids", "")
    if ids_param:
        for raw in ids_param.split(","):
            o = oid(raw.strip())
            if o:
                filter_ids.append(o)

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        base_sql = """
            SELECT id, id AS _id, name, category, location, qr_code
            FROM equipment
            WHERE (is_deleted IS NULL OR is_deleted=0)
        """
        params = []
        if filter_ids:
            placeholders = ",".join(["%s"] * len(filter_ids))
            base_sql += f" AND id IN ({placeholders})"
            params.extend(filter_ids)
        base_sql += " ORDER BY name ASC"
        cur.execute(base_sql, tuple(params))
        equipment = cur.fetchall() or []

        from routes.equipment import equipment_scan_public_url, _make_qr_image_url
        needs_commit = False
        for eq in equipment:
            if not eq.get("qr_code"):
                scan_url = equipment_scan_public_url(str(eq["_id"]), request)
                eq["qr_code"] = _make_qr_image_url(scan_url)
                cur.execute("UPDATE equipment SET qr_code=%s WHERE id=%s", (eq["qr_code"], eq["_id"]))
                needs_commit = True
        if needs_commit:
            db.commit()

        cur.close()
    finally:
        db.close()

    return render_template("qr_print.html", equipment=equipment)
