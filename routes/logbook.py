import csv
import io
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, Response, redirect, url_for, session

from models import get_db, format_date, log_activity, now_utc
from routes.decorators import role_required
from models.security import csrf_protect

logbook_bp = Blueprint("logbook", __name__, url_prefix="/logbook")


def _parse_date(s, fallback):
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return fallback


@logbook_bp.route("/")
@role_required("technician", "admin", "custodian")
def index():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        now = datetime.now(timezone.utc)

        from_str = request.args.get("from", "")
        to_str = request.args.get("to", "")
        category = request.args.get("category", "")
        search = request.args.get("search", "").strip()

        filter_parts = []
        params = []

        if from_str:
            from_dt = _parse_date(from_str, None)
            if from_dt:
                filter_parts.append("ml.date_completed >= %s")
                params.append(from_dt.replace(tzinfo=None))

        if to_str:
            to_dt = _parse_date(to_str, None)
            if to_dt:
                to_dt_end = to_dt.replace(hour=23, minute=59, second=59, tzinfo=None)
                filter_parts.append("ml.date_completed <= %s")
                params.append(to_dt_end)

        if category:
            filter_parts.append("e.category = %s")
            params.append(category)

        if search:
            filter_parts.append(
                "(e.name LIKE %s OR e.location LIKE %s OR ml.action_taken LIKE %s OR mr.description LIKE %s OR u.name LIKE %s)"
            )
            like_str = f"%{search}%"
            params.extend([like_str, like_str, like_str, like_str, like_str])

        where_clause = (" AND " + " AND ".join(filter_parts)) if filter_parts else ""

        sql = f"""
            SELECT ml.id AS log_id,
                   ml.equipment_id,
                   ml.request_id,
                   ml.action_taken,
                   ml.date_completed,
                   ml.repair_start,
                   ml.duration_minutes,
                   e.name AS equipment_name,
                   e.category AS category,
                   e.location AS location,
                   mr.description AS description,
                   mr.urgency AS urgency,
                   mr.affected_component AS affected_component,
                   mr.date_reported AS date_reported,
                   mr.image AS image,
                   u.name AS reporter_name,
                   tech.name AS technician_name
            FROM maintenance_logs ml
            JOIN equipment e ON e.id = ml.equipment_id
            JOIN maintenance_requests mr ON mr.id = ml.request_id
            LEFT JOIN users u ON u.id = mr.reported_by
            LEFT JOIN users tech ON tech.id = COALESCE(ml.technician_id, mr.technician_id)
            WHERE (ml.is_deleted IS NULL OR ml.is_deleted=0) {where_clause}
            ORDER BY ml.date_completed DESC
        """

        cur.execute(sql, tuple(params))
        logs = cur.fetchall()

        from models import format_duration_minutes
        for r in logs:
            if r["duration_minutes"] is not None:
                r["duration_str"] = format_duration_minutes(r["duration_minutes"])
            elif r["date_completed"] and (r["repair_start"] or r["date_reported"]):
                st = r["repair_start"] or r["date_reported"]
                diff_m = max(1, int(round((r["date_completed"] - st).total_seconds() / 60.0)))
                r["duration_str"] = format_duration_minutes(diff_m)
            else:
                r["duration_str"] = "—"

        # CSV Export
        if request.args.get("export") == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(
                [
                    "Log ID",
                    "Start Date/Time",
                    "Completion Date/Time",
                    "Calculated Duration",
                    "Equipment Name",
                    "Category",
                    "Location",
                    "Reporter",
                    "Assigned Technician",
                    "Urgency",
                    "Issue Description",
                    "Action Taken / Resolution",
                ]
            )
            for r in logs:
                ds = (
                    r["repair_start"].strftime("%Y-%m-%d %H:%M")
                    if r.get("repair_start")
                    else (r["date_reported"].strftime("%Y-%m-%d %H:%M") if r.get("date_reported") else "")
                )
                dc = (
                    r["date_completed"].strftime("%Y-%m-%d %H:%M")
                    if r["date_completed"]
                    else ""
                )
                w.writerow(
                    [
                        r["log_id"],
                        ds,
                        dc,
                        r["duration_str"],
                        r["equipment_name"],
                        r["category"] or "",
                        r["location"] or "",
                        r["reporter_name"] or "Unknown",
                        r["technician_name"] or "Unassigned",
                        r["urgency"] or "",
                        r["description"] or "",
                        r["action_taken"] or "",
                    ]
                )
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment; filename=repair_logbook.csv"},
            )

        # Categories for dropdown
        cur.execute(
            "SELECT DISTINCT category FROM equipment WHERE category IS NOT NULL AND category <> '' AND (is_deleted IS NULL OR is_deleted=0) ORDER BY category ASC"
        )
        categories = [r["category"] for r in cur.fetchall()]

        # Summary Statistics
        cur.execute("SELECT COUNT(*) AS total FROM maintenance_logs WHERE (is_deleted IS NULL OR is_deleted=0)")
        total_repairs = cur.fetchone()["total"]

        thirty_days_ago = (now - timedelta(days=30)).replace(tzinfo=None)
        cur.execute(
            "SELECT COUNT(*) AS recent FROM maintenance_logs WHERE date_completed >= %s AND (is_deleted IS NULL OR is_deleted=0)",
            (thirty_days_ago,),
        )
        recent_30_days = cur.fetchone()["recent"]

        cur.execute(
            """
            SELECT e.category, COUNT(*) AS cnt
            FROM maintenance_logs ml
            JOIN equipment e ON e.id = ml.equipment_id
            WHERE e.category IS NOT NULL AND e.category <> '' AND (ml.is_deleted IS NULL OR ml.is_deleted=0)
            GROUP BY e.category
            ORDER BY cnt DESC
            LIMIT 1
            """
        )
        top_cat_row = cur.fetchone()
        top_category = top_cat_row["category"] if top_cat_row else "N/A"

        cur.close()

        return render_template(
            "logbook.html",
            logs=logs,
            categories=categories,
            from_str=from_str,
            to_str=to_str,
            category=category,
            search=search,
            total_repairs=total_repairs,
            recent_30_days=recent_30_days,
            top_category=top_category,
            format_date=format_date,
        )
    finally:
        db.close()


@logbook_bp.route("/delete", methods=["POST"], endpoint="delete_logs")
@logbook_bp.route("/archive", methods=["POST"], endpoint="archive_logs")
@role_required("technician", "admin")
@csrf_protect
def delete_logs():
    log_ids = request.form.getlist("log_ids")
    if not log_ids:
        return redirect(url_for("logbook.index"))

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        deleted_count = 0

        for lid in log_ids:
            try:
                lid_int = int(lid)
            except (ValueError, TypeError):
                continue

            cur.execute("SELECT request_id FROM maintenance_logs WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)", (lid_int,))
            row = cur.fetchone()
            if row:
                cur.execute(
                    "UPDATE maintenance_logs SET is_deleted=1, deleted_at=%s WHERE id=%s",
                    (now_utc().replace(tzinfo=None), lid_int),
                )
                cur.execute(
                    "UPDATE maintenance_requests SET status='Pending', date_responded=NULL WHERE id=%s",
                    (row["request_id"],),
                )
                deleted_count += 1

        db.commit()
        if deleted_count > 0:
            try:
                log_activity(db, session.get("user", {}).get("id"), "archive_logs", f"Archived {deleted_count} maintenance log record(s)", "maintenance_log", None)
            except Exception:
                pass
        cur.close()
    finally:
        db.close()
    return redirect(url_for("logbook.index"))
