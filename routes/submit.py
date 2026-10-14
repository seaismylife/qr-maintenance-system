import os
import time
from flask import Blueprint, render_template, request, redirect, url_for, session, current_app
from werkzeug.utils import secure_filename
from models import get_db, oid, now_utc
from routes.decorators import role_required
from models.security import csrf_protect

submit_bp = Blueprint("submit", __name__, url_prefix="/request_submit")

ALLOWED = {"png", "jpg", "jpeg", "gif", "webp"}

def _allowed(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED

def save_maintenance_request(db, reporter_id, equipment_id, description, urgency, image_file, affected_component=None):
    eq_oid = oid(equipment_id)
    reporter = oid(reporter_id)
    if not eq_oid or not reporter:
        return "Invalid equipment or user."
    description = (description or "").strip()
    if not description:
        return "Please describe the issue."

    cur = db.cursor(dictionary=True)
    cur.execute("SELECT id FROM equipment WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)", (eq_oid,))
    if not cur.fetchone():
        cur.close()
        return "Equipment not found or inactive."

    image_path = None
    f = image_file
    if f and f.filename and _allowed(f.filename):
        upload_dir = current_app.config["UPLOAD_FOLDER"]
        os.makedirs(upload_dir, exist_ok=True)
        fname = secure_filename(f.filename)
        fname = f"{int(time.time())}_{fname}"
        f.save(os.path.join(upload_dir, fname))
        image_path = f"uploads/{fname}"

    affected = (affected_component or "Entire Workstation / Set").strip()

    cur.execute(
        "INSERT INTO maintenance_requests (equipment_id, reported_by, description, urgency, image, affected_component, date_reported) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (eq_oid, reporter, description, urgency or "Medium", image_path, affected, now_utc().replace(tzinfo=None)),
    )

    cur.execute("SELECT id FROM users WHERE role IN ('technician', 'admin') AND (is_deleted IS NULL OR is_deleted=0)")
    recipients = [r["id"] for r in cur.fetchall()]
    if reporter and reporter not in recipients:
        recipients.append(reporter)

    cur.execute("SELECT name FROM equipment WHERE id=%s", (eq_oid,))
    eq_doc = cur.fetchone()
    eq_name = eq_doc["name"] if eq_doc else "Equipment"
    
    from models.db import create_notification
    for uid in recipients:
        if uid == reporter:
            msg = f"Your request for '{eq_name}' was submitted successfully"
            link = url_for("my_req.index")
        else:
            msg = f"New maintenance request for '{eq_name}'"
            link = url_for("requests.index")
        create_notification(db, uid, msg, link)

    db.commit()
    cur.close()
    return None

@submit_bp.route("/", methods=["GET", "POST"])
@role_required("faculty", "admin", "custodian", "technician")
@csrf_protect
def index():
    eq_id = request.args.get("equipment_id") or request.form.get("equipment_id")
    eq_oid = oid(eq_id)

    if eq_oid:
        return redirect(url_for("equipment.scan", equipment_id=str(eq_oid)))

    if session.get("user", {}).get("role") != "faculty":
        return redirect(url_for("scan.camera"))

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        equipment = {}
        if eq_oid:
            cur.execute("SELECT * FROM equipment WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)", (eq_oid,))
            equipment = cur.fetchone() or {}

        if request.method == "POST":
            err = save_maintenance_request(
                db,
                session["user"]["id"],
                request.form.get("equipment_id"),
                request.form.get("description", ""),
                request.form.get("urgency", "Medium"),
                request.files.get("image"),
                request.form.get("affected_component"),
            )
            cur.close()
            if err:
                return err, 400
            return redirect(url_for("my_req.index"))

        cur.close()
        return redirect(url_for("scan.camera"))
    finally:
        db.close()
