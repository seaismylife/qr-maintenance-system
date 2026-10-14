import urllib.parse
import config
from flask import Blueprint, render_template, request, redirect, url_for, abort, session, flash
from models import get_db, status_badge, oid, now_utc, log_activity
from routes.decorators import role_required
from routes.submit import save_maintenance_request
from models.security import validate_equipment_payload, normalize_text, csrf_protect

equipment_bp = Blueprint("equipment", __name__, url_prefix="/equipment")


def _public_base(request) -> str:
    if config.PUBLIC_BASE_URL:
        return config.PUBLIC_BASE_URL
    return request.url_root.rstrip("/")


def equipment_scan_path(equipment_id: str) -> str:
    return f"/equipment/scan/{equipment_id}"


def equipment_scan_public_url(equipment_id: str, request) -> str:
    return _public_base(request) + equipment_scan_path(str(equipment_id))


def _make_qr_image_url(scan_page_url: str) -> str:
    return (
        "https://api.qrserver.com/v1/create-qr-code/?size=300x300&data="
        + urllib.parse.quote(scan_page_url, safe="")
    )


def _load_equipment(cur, eq_oid):
    cur.execute("SELECT * FROM equipment WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)", (eq_oid,))
    return cur.fetchone()


@equipment_bp.route("/", methods=["GET", "POST"])
@role_required("custodian", "technician", "admin")
@csrf_protect
def index():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        user_role = session.get("user", {}).get("role")

        if request.method == "POST":
            if user_role not in ("admin", "custodian"):
                abort(403, "Technicians have read-only access to equipment inventory.")

            name     = normalize_text(request.form.get("name"))
            category = normalize_text(request.form.get("category"))
            location = normalize_text(request.form.get("location"))
            status   = normalize_text(request.form.get("status", "Working"))

            errors, name, category, location, status = validate_equipment_payload(name, category, location, status)
            if errors:
                cur.execute("SELECT * FROM equipment WHERE (is_deleted IS NULL OR is_deleted=0) ORDER BY id DESC")
                rows = cur.fetchall()
                cur.close()
                return render_template("equipment.html", rows=rows, edit_doc=None, status_badge=status_badge, errors=errors), 400

            existing_id = oid(request.form.get("equipment_id"))

            if existing_id:
                cur.execute(
                    "UPDATE equipment SET name=%s, category=%s, location=%s, status=%s WHERE id=%s",
                    (name, category, location, status, existing_id),
                )
                eq_id_hex = str(existing_id)
                action_desc = f"Updated equipment id {existing_id} ({name})"
            else:
                cur.execute(
                    "INSERT INTO equipment (name, category, location, status, qr_code, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
                    (name, category, location, status, "", now_utc().replace(tzinfo=None)),
                )
                eq_id_hex = str(cur.lastrowid)
                action_desc = f"Added equipment id {eq_id_hex} ({name})"

            scan_url = equipment_scan_public_url(eq_id_hex, request)
            qr_url = _make_qr_image_url(scan_url)
            cur.execute("UPDATE equipment SET qr_code=%s WHERE id=%s", (qr_url, int(eq_id_hex)))
            db.commit()

            try:
                log_activity(db, session.get("user", {}).get("id"), "save_equipment", action_desc, "equipment", int(eq_id_hex))
            except Exception:
                pass

            cur.close()
            return redirect(url_for("equipment.index"))

        # Fallback query parameter deletion (guarded by role_required)
        if "delete" in request.args or "archive" in request.args:
            if user_role not in ("admin", "custodian"):
                abort(403, "Technicians cannot archive equipment.")
            del_id = oid(request.args.get("archive") or request.args.get("delete"))
            if del_id:
                cur.execute("UPDATE equipment SET is_deleted=1, deleted_at=%s WHERE id=%s", (now_utc().replace(tzinfo=None), del_id))
                db.commit()
                try:
                    log_activity(db, session.get("user", {}).get("id"), "archive_equipment", f"Archived equipment id {del_id}", "equipment", del_id)
                except Exception:
                    pass
            cur.close()
            return redirect(url_for("equipment.index"))

        edit_doc = None
        if "edit" in request.args and user_role in ("admin", "custodian"):
            edit_oid = oid(request.args["edit"])
            if edit_oid:
                edit_doc = _load_equipment(cur, edit_oid)

        cur.execute("SELECT * FROM equipment WHERE (is_deleted IS NULL OR is_deleted=0) ORDER BY id DESC")
        rows = cur.fetchall()
        cur.close()
        return render_template(
            "equipment.html",
            rows=rows,
            edit_doc=edit_doc,
            status_badge=status_badge,
        )
    finally:
        db.close()


@equipment_bp.route("/delete/<int:equipment_id>", methods=["POST"], endpoint="delete")
@equipment_bp.route("/delete_equipment/<int:equipment_id>", methods=["POST"], endpoint="delete_equipment")
@equipment_bp.route("/archive/<int:equipment_id>", methods=["POST"], endpoint="archive")
@role_required("custodian", "admin")
@csrf_protect
def delete_equipment(equipment_id):
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute("UPDATE equipment SET is_deleted=1, deleted_at=%s WHERE id=%s", (now_utc().replace(tzinfo=None), equipment_id))
        db.commit()
        cur.close()
        try:
            log_activity(db, session.get("user", {}).get("id"), "archive_equipment", f"Archived equipment id {equipment_id}", "equipment", equipment_id)
        except Exception:
            pass
    finally:
        db.close()
    return redirect(url_for("equipment.index"))


@equipment_bp.route("/scan/<equipment_id>", methods=["GET", "POST"])
@csrf_protect
def scan(equipment_id):
    eq_oid = oid(equipment_id)
    if not eq_oid:
        abort(404, "Equipment not found.")

    if "user" not in session:
        return redirect(url_for("auth.login", next=equipment_scan_path(str(eq_oid))))

    role = session["user"]["role"]
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        equipment = _load_equipment(cur, eq_oid)
        if not equipment:
            cur.close()
            abort(404, "Equipment not found or has been removed.")

        if request.method == "POST":
            if role in ("admin", "custodian", "technician"):
                name     = normalize_text(request.form.get("name"))
                category = normalize_text(request.form.get("category"))
                location = normalize_text(request.form.get("location"))
                status   = normalize_text(request.form.get("status", "Working"))
                errors, name, category, location, status = validate_equipment_payload(name, category, location, status)
                if errors:
                    cur.close()
                    return render_template("equipment_scan.html", equipment=equipment, role=role, can_edit=True, status_badge=status_badge, report_error=" ".join(errors)), 400
                cur.execute(
                    "UPDATE equipment SET name=%s, category=%s, location=%s, status=%s WHERE id=%s",
                    (name, category, location, status, eq_oid),
                )
                scan_url = equipment_scan_public_url(str(eq_oid), request)
                qr_url = _make_qr_image_url(scan_url)
                cur.execute("UPDATE equipment SET qr_code=%s WHERE id=%s", (qr_url, eq_oid))
                db.commit()
                try:
                    log_activity(db, session.get("user", {}).get("id"), "update_equipment", f"Updated equipment id {eq_oid}", "equipment", eq_oid)
                except Exception:
                    pass
                cur.close()
                return redirect(url_for("equipment.scan", equipment_id=str(eq_oid)))

            if role == "faculty":
                cur.close()
                err = save_maintenance_request(
                    db,
                    session["user"]["id"],
                    str(eq_oid),
                    request.form.get("description", ""),
                    request.form.get("urgency", "Medium"),
                    request.files.get("image"),
                    request.form.get("affected_component"),
                )
                if err:
                    return render_template(
                        "equipment_scan.html",
                        equipment=equipment,
                        role=role,
                        can_edit=False,
                        status_badge=status_badge,
                        report_error=err,
                    ), 400
                return redirect(url_for("my_req.index"))

        cur.close()
        can_edit = role in ("admin", "custodian", "technician")
        return render_template(
            "equipment_scan.html",
            equipment=equipment,
            role=role,
            can_edit=can_edit,
            status_badge=status_badge,
            report_error="",
        )
    finally:
        db.close()
