from flask import Blueprint, render_template, request, redirect, url_for, session, abort
from models import get_db, status_badge, oid, now_utc, log_activity
from routes.decorators import role_required
from models.security import csrf_protect

requests_bp = Blueprint("requests", __name__, url_prefix="/maintenance_requests")

ALLOWED_REQUEST_STATUSES = {
    "Pending",
    "In Progress",
    "Completed - Pending Verification",
    "Resolved",
    "Rejected",
}

@requests_bp.route("/assign/<int:request_id>", methods=["POST"])
@role_required("admin")
@csrf_protect
def assign_technician(request_id):
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        tech_val = (request.form.get("technician_id") or "").strip()
        new_tech_id = oid(tech_val) if tech_val else None

        cur.execute("SELECT technician_id FROM maintenance_requests WHERE id=%s", (request_id,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE maintenance_requests SET technician_id=%s WHERE id=%s", (new_tech_id, request_id))
            if new_tech_id:
                cur.execute(
                    "SELECT r.id, e.name AS equipment_name, u.name AS tech_name FROM maintenance_requests r "
                    "JOIN equipment e ON r.equipment_id = e.id "
                    "JOIN users u ON u.id = %s WHERE r.id = %s",
                    (new_tech_id, request_id)
                )
                tinfo = cur.fetchone()
                if tinfo:
                    from models.db import create_notification
                    create_notification(
                        db,
                        new_tech_id,
                        f"You have been assigned to repair equipment '{tinfo['equipment_name']}'",
                        url_for("requests.index")
                    )
                    try:
                        log_activity(db, session.get("user", {}).get("id"), "assign_technician", f"Assigned technician {tinfo['tech_name']} to request #{request_id}", "maintenance_request", request_id)
                    except Exception:
                        pass
            else:
                try:
                    log_activity(db, session.get("user", {}).get("id"), "unassign_technician", f"Unassigned technician from request #{request_id}", "maintenance_request", request_id)
                except Exception:
                    pass
            db.commit()
        cur.close()
    finally:
        db.close()
    return redirect(url_for("requests.index"))

@requests_bp.route("/", methods=["GET", "POST"])
@role_required("technician", "admin")
@csrf_protect
def index():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        if request.method == "POST":
            req_oid = oid(request.form.get("request_id"))
            if not req_oid:
                cur.close()
                return redirect(url_for("requests.index"))

            status = request.form.get("status", "Pending")
            if status not in ALLOWED_REQUEST_STATUSES:
                status = "Pending"

            logged_user = session.get("user", {})
            user_role = logged_user.get("role")

            if user_role == "technician" and status in ("Resolved", "Completed - Pending Verification"):
                action = (request.form.get("action_taken") or "").strip()
                if not action:
                    cur.close()
                    return redirect(url_for("requests.index", error="action_required"))
                status = "Completed - Pending Verification"

            if status == "Resolved":
                action = (request.form.get("action_taken") or "").strip()
                if not action:
                    cur.execute("SELECT technician_notes FROM maintenance_requests WHERE id=%s", (req_oid,))
                    prev_note_row = cur.fetchone()
                    action = (prev_note_row.get("technician_notes") or "").strip() if prev_note_row else ""
                if not action:
                    cur.close()
                    return redirect(url_for("requests.index", error="action_required"))
            else:
                action = (request.form.get("action_taken") or "").strip()

            now_time = now_utc().replace(tzinfo=None)

            cur.execute(
                "SELECT r.*, e.name AS equipment_name, u.name AS reporter_name "
                "FROM maintenance_requests r "
                "JOIN equipment e ON r.equipment_id = e.id "
                "LEFT JOIN users u ON r.reported_by = u.id "
                "WHERE r.id=%s",
                (req_oid,)
            )
            req_doc = cur.fetchone() or {}
            prev_status = req_doc.get("status")
            equipment_name = req_doc.get("equipment_name") or "Equipment"
            reported_by = req_doc.get("reported_by")
            tech_id = req_doc.get("technician_id")

            if user_role == "technician":
                if not tech_id or oid(tech_id) != oid(logged_user.get("id")):
                    cur.close()
                    abort(403)

            if user_role == "admin" and "technician_id" in request.form:
                tech_val = (request.form.get("technician_id") or "").strip()
                new_tech_id = oid(tech_val) if tech_val else None
                cur.execute("UPDATE maintenance_requests SET technician_id=%s WHERE id=%s", (new_tech_id, req_oid))
                if new_tech_id and new_tech_id != tech_id:
                    tech_id = new_tech_id
                    from models.db import create_notification
                    create_notification(
                        db,
                        new_tech_id,
                        f"You have been assigned to repair equipment '{equipment_name}'",
                        url_for("requests.index")
                    )

            if status == "In Progress":
                cur.execute(
                    "UPDATE maintenance_requests SET status=%s, date_responded=%s, repair_start=COALESCE(repair_start, %s) WHERE id=%s",
                    (status, now_time, now_time, req_oid),
                )
                eq_id = req_doc.get("equipment_id")
                if eq_id:
                    cur.execute("UPDATE equipment SET status='Under Repair' WHERE id=%s", (eq_id,))

                if user_role == "admin" and prev_status == "Completed - Pending Verification" and tech_id:
                    from models.db import create_notification
                    revision_msg = f"Admin requested rework on '{equipment_name}'."
                    if action:
                        revision_msg += f" Note: {action}"
                    create_notification(db, tech_id, revision_msg, url_for("requests.index"))

            elif status == "Completed - Pending Verification":
                cur.execute(
                    "UPDATE maintenance_requests SET status=%s, technician_notes=%s, date_responded=%s WHERE id=%s",
                    (status, action, now_time, req_oid),
                )
                from models.db import create_notification
                cur.execute("SELECT id FROM users WHERE role='admin' AND (is_deleted IS NULL OR is_deleted=0)")
                admin_rows = cur.fetchall()
                tech_display = logged_user.get("name") or "Technician"
                for adm in admin_rows:
                    create_notification(
                        db,
                        adm["id"],
                        f"Technician {tech_display} completed repair on '{equipment_name}'. Awaiting your verification.",
                        url_for("requests.index")
                    )
                if reported_by:
                    create_notification(
                        db,
                        reported_by,
                        f"Repair on '{equipment_name}' has been completed by technician and is currently awaiting Admin verification.",
                        url_for("my_req.index")
                    )

            elif status == "Resolved":
                cur.execute(
                    "UPDATE maintenance_requests SET status=%s, date_responded=%s WHERE id=%s",
                    (status, now_time, req_oid),
                )
                eq_id = req_doc.get("equipment_id")
                start_time = req_doc.get("repair_start") or req_doc.get("date_reported") or now_time

                try:
                    delta_seconds = (now_time - start_time).total_seconds()
                    duration_minutes = max(1, int(round(delta_seconds / 60.0)))
                except Exception:
                    duration_minutes = 0

                final_action = action or req_doc.get("technician_notes") or "Repair completed and verified."
                if eq_id:
                    cur.execute(
                        "INSERT INTO maintenance_logs (equipment_id, request_id, action_taken, date_completed, repair_start, duration_minutes, technician_id) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (eq_id, req_oid, final_action, now_time, start_time, duration_minutes, tech_id),
                    )
                    cur.execute(
                        "UPDATE equipment SET status='Working' WHERE id=%s",
                        (eq_id,),
                    )

                from models.db import create_notification
                if reported_by:
                    create_notification(
                        db,
                        reported_by,
                        f"Your request for '{equipment_name}' was verified and resolved by Admin. Equipment is now working.",
                        url_for("my_req.index")
                    )
                if tech_id and tech_id != logged_user.get("id"):
                    create_notification(
                        db,
                        tech_id,
                        f"Admin has verified and approved your repair for '{equipment_name}'.",
                        url_for("requests.index")
                    )

            elif status == "Rejected":
                cur.execute(
                    "UPDATE maintenance_requests SET status=%s, date_responded=%s WHERE id=%s",
                    (status, now_time, req_oid),
                )
                if reported_by:
                    from models.db import create_notification
                    create_notification(
                        db,
                        reported_by,
                        f"Your request for '{equipment_name}' was rejected: {action or 'No reason provided.'}",
                        url_for("my_req.index")
                    )
            else:
                cur.execute(
                    "UPDATE maintenance_requests SET status=%s, date_responded=%s WHERE id=%s",
                    (status, now_time, req_oid),
                )

            db.commit()
            try:
                log_activity(db, logged_user.get("id"), "update_request", f"Updated maintenance request id {req_oid} to '{status}'", "maintenance_request", req_oid)
            except Exception:
                pass

            cur.close()
            return redirect(url_for("requests.index"))

        logged_user = session.get("user", {})
        user_role = logged_user.get("role")
        user_id = oid(logged_user.get("id"))

        if user_role == "technician":
            cur.execute(
                "SELECT r.*, e.name AS equipment_name, e.location AS equipment_location, "
                "u.name AS reporter_name, tech.name AS technician_name, tech.email AS technician_email "
                "FROM maintenance_requests r "
                "LEFT JOIN equipment e ON r.equipment_id = e.id "
                "LEFT JOIN users u ON r.reported_by = u.id "
                "LEFT JOIN users tech ON r.technician_id = tech.id "
                "LEFT JOIN maintenance_logs ml ON r.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted=0) "
                "WHERE r.status NOT IN ('Resolved', 'Rejected') AND ml.id IS NULL AND (r.is_deleted IS NULL OR r.is_deleted=0) "
                "AND r.technician_id = %s "
                "ORDER BY (CASE WHEN r.urgency = 'Critical' THEN 0 WHEN r.urgency = 'High' THEN 1 WHEN r.urgency = 'Medium' THEN 2 WHEN r.urgency = 'Low' THEN 3 ELSE 4 END), "
                "(CASE WHEN r.status = 'Completed - Pending Verification' THEN 0 WHEN r.status = 'In Progress' THEN 1 ELSE 2 END), r.id DESC",
                (user_id,)
            )
        else:
            cur.execute(
                "SELECT r.*, e.name AS equipment_name, e.location AS equipment_location, "
                "u.name AS reporter_name, tech.name AS technician_name, tech.email AS technician_email "
                "FROM maintenance_requests r "
                "LEFT JOIN equipment e ON r.equipment_id = e.id "
                "LEFT JOIN users u ON r.reported_by = u.id "
                "LEFT JOIN users tech ON r.technician_id = tech.id "
                "LEFT JOIN maintenance_logs ml ON r.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted=0) "
                "WHERE r.status NOT IN ('Resolved', 'Rejected') AND ml.id IS NULL AND (r.is_deleted IS NULL OR r.is_deleted=0) "
                "ORDER BY (CASE WHEN r.urgency = 'Critical' THEN 0 WHEN r.urgency = 'High' THEN 1 WHEN r.urgency = 'Medium' THEN 2 WHEN r.urgency = 'Low' THEN 3 ELSE 4 END), "
                "(CASE WHEN r.status = 'Completed - Pending Verification' THEN 0 WHEN r.status = 'In Progress' THEN 1 ELSE 2 END), r.id DESC"
            )
        rows = cur.fetchall()

        cur.execute("SELECT id, name, email FROM users WHERE role='technician' AND (is_deleted IS NULL OR is_deleted=0) ORDER BY name ASC")
        technicians = cur.fetchall()
        cur.close()

        return render_template(
            "maintenance_requests.html",
            rows=rows,
            technicians=technicians,
            status_badge=status_badge,
        )
    finally:
        db.close()
