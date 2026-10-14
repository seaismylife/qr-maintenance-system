import csv
import io
import os
import time
from datetime import datetime, timezone, timedelta
from flask import Blueprint, render_template, request, Response, redirect, url_for, session, current_app
from werkzeug.utils import secure_filename
from models import get_db, oid, now_utc, format_duration_minutes
from routes.decorators import role_required
from models.security import normalize_text, validate_report_payload, csrf_protect, ALLOWED_LABORATORIES

reports_bp = Blueprint("reports", __name__, url_prefix="/admin_reports")

ALLOWED_EXT = {"png", "jpg", "jpeg", "gif", "webp"}


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def _parse_date(s, fallback):
    try:
        return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return fallback


def _format_duration(hours):
    if hours is None:
        return "—"
    try:
        total_seconds = int(float(hours) * 3600)
    except Exception:
        return "—"
    if total_seconds <= 0:
        return "—"
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    if h >= 24:
        days = h // 24
        rem_h = h % 24
        return f"{days}d {rem_h}h"
    elif h > 0:
        return f"{h}h {m}m"
    elif m > 0:
        return f"{m}m"
    else:
        return f"{s}s"


@reports_bp.route("/")
@role_required("admin")
def index():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        now = datetime.now(timezone.utc)

        # Default to previous 30 days to ensure rich recent data is captured
        default_from = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        from_str = request.args.get("from", default_from)
        to_str   = request.args.get("to",   now.strftime("%Y-%m-%d"))
        category = request.args.get("category", "")
        status   = request.args.get("status", "")
        lab      = request.args.get("lab", "").strip()
        month    = request.args.get("month", "").strip()
        time_window = request.args.get("time_window", "90").strip()
        technician_id = oid(request.args.get("technician_id"))

        # If user picked a timely month (e.g. 2026-09)
        if month:
            try:
                parts = month.split("-")
                y = int(parts[0])
                m = int(parts[1])
                from_dt = datetime(y, m, 1, 0, 0, 0, tzinfo=timezone.utc)
                if m == 12:
                    to_dt = datetime(y + 1, 1, 1, 0, 0, 0, tzinfo=timezone.utc) - timedelta(seconds=1)
                else:
                    to_dt = datetime(y, m + 1, 1, 0, 0, 0, tzinfo=timezone.utc) - timedelta(seconds=1)
                from_str = from_dt.strftime("%Y-%m-%d")
                to_str = to_dt.strftime("%Y-%m-%d")
            except Exception:
                from_dt = _parse_date(from_str, datetime(now.year, now.month, 1, tzinfo=timezone.utc))
                to_dt   = _parse_date(to_str,   now).replace(hour=23, minute=59, second=59)
        else:
            from_dt = _parse_date(from_str, datetime(now.year, now.month, 1, tzinfo=timezone.utc))
            to_dt   = _parse_date(to_str,   now).replace(hour=23, minute=59, second=59)

        filter_parts = ["mr.date_reported BETWEEN %s AND %s"]
        params = [from_dt.replace(tzinfo=None), to_dt.replace(tzinfo=None)]
        if status:
            filter_parts.append("mr.status = %s")
            params.append(status)
        if category:
            filter_parts.append("e.category = %s")
            params.append(category)
        if lab:
            filter_parts.append("e.location = %s")
            params.append(lab)
        where_clause = " AND ".join(filter_parts)

        # 7 specific laboratories
        locations = ALLOWED_LABORATORIES

        # Query available recorded timely months
        cur.execute(
            """
            SELECT DISTINCT 
                DATE_FORMAT(date_reported, '%Y-%m') as m_key,
                DATE_FORMAT(date_reported, '%M %Y') as m_label
            FROM maintenance_requests
            WHERE (is_deleted IS NULL OR is_deleted=0)
            ORDER BY m_key DESC
            """
        )
        available_months = cur.fetchall()

        # Laboratory Specific Diagnostics (If a specific lab is selected)
        lab_stats = None
        lab_equipment = []
        lab_history = []
        if lab:
            cur.execute(
                """
                SELECT e.id, e.name, e.category, e.location, e.status, e.qr_code,
                       COUNT(DISTINCT mr.id) AS incident_count,
                       SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved_count,
                       SUM(CASE WHEN mr.status IN ('Pending', 'In Progress') THEN 1 ELSE 0 END) AS active_issue_count,
                       MAX(mr.date_reported) AS last_reported_date
                FROM equipment e
                LEFT JOIN maintenance_requests mr ON mr.equipment_id = e.id AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
                WHERE e.location = %s AND e.is_deleted = 0
                GROUP BY e.id, e.name, e.category, e.location, e.status, e.qr_code
                ORDER BY e.name ASC
                """,
                (lab,),
            )
            lab_equipment = cur.fetchall()
            lab_total = len(lab_equipment)
            lab_working = sum(1 for item in lab_equipment if item["status"] == "Working")
            lab_maintenance = sum(1 for item in lab_equipment if item["status"] in ("Under Repair", "Under Maintenance"))
            lab_damaged = sum(1 for item in lab_equipment if item["status"] in ("Not Working", "Damaged"))
            lab_readiness = round((lab_working / lab_total * 100), 1) if lab_total > 0 else 0.0
            lab_stats = {
                "name": lab,
                "total": lab_total,
                "working": lab_working,
                "maintenance": lab_maintenance,
                "damaged": lab_damaged,
                "readiness": lab_readiness,
            }

            # Laboratory maintenance history
            cur.execute(
                """
                SELECT mr.id AS request_id, e.name AS equipment_name, e.category, mr.description,
                       mr.urgency, mr.status, mr.date_reported, mr.repair_start, ml.date_completed,
                       ml.duration_minutes,
                       TIMESTAMPDIFF(SECOND, COALESCE(mr.repair_start, mr.date_reported), ml.date_completed) / 3600.0 AS duration_hours,
                       ml.action_taken, tech.name AS technician_name
                FROM maintenance_requests mr
                JOIN equipment e ON mr.equipment_id = e.id
                LEFT JOIN maintenance_logs ml ON mr.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
                LEFT JOIN users tech ON mr.technician_id = tech.id
                WHERE e.location = %s AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
                ORDER BY mr.date_reported DESC
                LIMIT 50
                """,
                (lab,),
            )
            lab_history = cur.fetchall()
            for lh in lab_history:
                if lh.get("duration_minutes") is not None:
                    lh["duration_str"] = format_duration_minutes(lh["duration_minutes"])
                else:
                    lh["duration_str"] = _format_duration(lh.get("duration_hours"))

        # Comparative overview guaranteeing all 7 institutional laboratories
        cur.execute(
            """
            SELECT 
                e.location,
                COUNT(e.id) AS total_assets,
                SUM(CASE WHEN e.status = 'Working' THEN 1 ELSE 0 END) AS working_count,
                SUM(CASE WHEN e.status IN ('Under Repair', 'Under Maintenance') THEN 1 ELSE 0 END) AS maintenance_count,
                SUM(CASE WHEN e.status IN ('Not Working', 'Damaged') THEN 1 ELSE 0 END) AS damaged_count,
                COUNT(DISTINCT mr.id) AS total_tickets
            FROM equipment e
            LEFT JOIN maintenance_requests mr ON mr.equipment_id = e.id AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
            WHERE e.is_deleted = 0 AND e.location IS NOT NULL AND e.location <> ''
            GROUP BY e.location
            """
        )
        labs_query_rows = cur.fetchall()
        labs_query_map = {r["location"]: r for r in labs_query_rows}
        all_labs_summary = []
        for lab_name in ALLOWED_LABORATORIES:
            row_data = labs_query_map.get(lab_name, {
                "location": lab_name,
                "total_assets": 0,
                "working_count": 0,
                "maintenance_count": 0,
                "damaged_count": 0,
                "total_tickets": 0,
            })
            tot = row_data["total_assets"] or 0
            w = int(row_data["working_count"] or 0)
            row_data["readiness_rate"] = round((w / tot * 100), 1) if tot > 0 else 0.0
            all_labs_summary.append(row_data)

        # 1. Total institutional equipment count
        cur.execute("SELECT COUNT(*) AS total FROM equipment WHERE (is_deleted IS NULL OR is_deleted=0)")
        total_equipment = cur.fetchone()["total"] or 0

        # 2. Overall KPI Counts within filter period
        cur.execute(
            f"""
            SELECT 
                COUNT(*) AS total_req,
                SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved_req,
                SUM(CASE WHEN mr.status = 'Pending' THEN 1 ELSE 0 END) AS pending_req,
                SUM(CASE WHEN mr.status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress_req,
                SUM(CASE WHEN mr.status = 'Rejected' THEN 1 ELSE 0 END) AS rejected_req
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            WHERE {where_clause}
            """,
            tuple(params),
        )
        kpi_counts = cur.fetchone() or {}
        total_req = kpi_counts.get("total_req") or 0
        resolved_req = int(kpi_counts.get("resolved_req") or 0)
        pending_req = int(kpi_counts.get("pending_req") or 0)
        in_progress_req = int(kpi_counts.get("in_progress_req") or 0)
        rejected_req = int(kpi_counts.get("rejected_req") or 0)
        resolution_rate = round((resolved_req / total_req * 100), 1) if total_req > 0 else 0.0

        # 3. Frequency by equipment
        cur.execute(
            f"""
            SELECT e.name AS name, e.location, COUNT(*) AS total
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            WHERE {where_clause}
            GROUP BY e.name, e.location
            ORDER BY total DESC
            LIMIT 10
            """,
            tuple(params),
        )
        freq_rows = cur.fetchall()

        # 4. Monthly Trend Data (for charts and breakdown table)
        cur.execute(
            f"""
            SELECT 
                DATE_FORMAT(mr.date_reported, '%Y-%m') AS m,
                DATE_FORMAT(mr.date_reported, '%M %Y') AS month_label,
                COUNT(mr.id) AS total,
                SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved,
                SUM(CASE WHEN mr.status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress,
                SUM(CASE WHEN mr.status = 'Pending' THEN 1 ELSE 0 END) AS pending,
                AVG(CASE WHEN mr.status = 'Resolved' AND ml.date_completed IS NOT NULL 
                    THEN TIMESTAMPDIFF(SECOND, mr.date_reported, ml.date_completed) / 3600.0 END) AS avg_hours
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            LEFT JOIN maintenance_logs ml ON mr.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
            WHERE {where_clause}
            GROUP BY DATE_FORMAT(mr.date_reported, '%Y-%m'), DATE_FORMAT(mr.date_reported, '%M %Y')
            ORDER BY m DESC
            """,
            tuple(params),
        )
        monthly_breakdown = cur.fetchall()
        for mb in monthly_breakdown:
            tot = mb["total"] or 0
            res = int(mb["resolved"] or 0)
            mb["rate"] = round((res / tot * 100), 1) if tot > 0 else 0.0
            mb["avg_hours_val"] = float(mb["avg_hours"]) if mb["avg_hours"] else None
            mb["avg_duration_str"] = _format_duration(mb["avg_hours_val"])

        # Chart format (ascending order)
        monthly_chart = sorted(monthly_breakdown, key=lambda x: x["m"])

        # 5. Average response & resolution times
        cur.execute(
            f"""
            SELECT AVG(TIMESTAMPDIFF(SECOND, mr.date_reported, COALESCE(mr.date_responded, NOW())) / 3600) AS avg_hours
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            WHERE {where_clause}
            """,
            tuple(params),
        )
        avg_resp = float(cur.fetchone()["avg_hours"] or 0.0)

        cur.execute(
            f"""
            SELECT AVG(TIMESTAMPDIFF(SECOND, mr.date_reported, ml.date_completed) / 3600) AS avg_hours
            FROM maintenance_requests mr
            JOIN maintenance_logs ml ON mr.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
            JOIN equipment e ON e.id = mr.equipment_id
            WHERE {where_clause}
            """,
            tuple(params),
        )
        avg_res_val = cur.fetchone()["avg_hours"]
        avg_res = float(avg_res_val) if avg_res_val is not None else None

        # 6. Most common issues by category
        cur.execute(
            f"""
            SELECT e.category, COUNT(mr.id) AS count
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            WHERE {where_clause}
            GROUP BY e.category
            ORDER BY count DESC
            LIMIT 5
            """,
            tuple(params),
        )
        common_issues = cur.fetchall()

        # 7. Peak reporting hour
        cur.execute(
            f"""
            SELECT HOUR(mr.date_reported) AS peak_hour, COUNT(*) as c
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            WHERE {where_clause}
            GROUP BY peak_hour
            ORDER BY c DESC
            LIMIT 1
            """,
            tuple(params),
        )
        peak_row = cur.fetchone()
        peak_hour_str = f"{int(peak_row['peak_hour']):02d}:00" if peak_row and peak_row["peak_hour"] is not None else "N/A"

        # 8. Technician Performance & Turnaround Analysis
        cur.execute(
            f"""
            SELECT 
                u.id AS technician_id,
                u.name AS technician_name,
                u.email AS technician_email,
                COUNT(DISTINCT mr.id) AS total_assigned,
                COUNT(DISTINCT CASE WHEN mr.status = 'Resolved' THEN mr.id END) AS completed_repairs,
                COUNT(DISTINCT CASE WHEN mr.status = 'In Progress' THEN mr.id END) AS in_progress_count,
                COUNT(DISTINCT CASE WHEN mr.status = 'Pending' THEN mr.id END) AS pending_count,
                AVG(CASE WHEN mr.status = 'Resolved' AND ml.date_completed IS NOT NULL 
                    THEN TIMESTAMPDIFF(SECOND, mr.date_reported, ml.date_completed) / 3600.0 END) AS avg_fix_hours,
                SUM(CASE WHEN mr.status = 'Resolved' AND ml.date_completed IS NOT NULL 
                    THEN TIMESTAMPDIFF(SECOND, mr.date_reported, ml.date_completed) / 3600.0 END) AS total_fix_hours
            FROM users u
            LEFT JOIN maintenance_requests mr ON mr.technician_id = u.id AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
            LEFT JOIN equipment e ON e.id = mr.equipment_id
            LEFT JOIN maintenance_logs ml ON mr.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
            WHERE u.role = 'technician' AND (u.is_deleted IS NULL OR u.is_deleted = 0)
                  AND (mr.id IS NULL OR ({where_clause}))
            GROUP BY u.id, u.name, u.email
            ORDER BY completed_repairs DESC, total_assigned DESC, u.name ASC
            """,
            tuple(params),
        )
        tech_stats = cur.fetchall()

        # Detailed breakdown of equipment fixed per technician
        cur.execute(
            f"""
            SELECT 
                u.id AS technician_id,
                u.name AS technician_name,
                e.name AS equipment_name,
                e.category AS equipment_category,
                e.location AS equipment_location,
                mr.id AS request_id,
                mr.description,
                mr.urgency,
                mr.date_reported,
                ml.date_completed,
                TIMESTAMPDIFF(SECOND, mr.date_reported, ml.date_completed) / 3600.0 AS duration_hours,
                ml.action_taken
            FROM maintenance_requests mr
            JOIN equipment e ON mr.equipment_id = e.id
            JOIN maintenance_logs ml ON mr.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
            LEFT JOIN users u ON mr.technician_id = u.id
            WHERE mr.status = 'Resolved' AND ({where_clause})
            ORDER BY ml.date_completed DESC
            """,
            tuple(params),
        )
        fixed_logs = cur.fetchall()

        # Group fixed equipment under each technician
        fixed_by_tech = {}
        for fl in fixed_logs:
            tid = fl["technician_id"] or 0
            fl["duration_str"] = _format_duration(fl["duration_hours"])
            if tid not in fixed_by_tech:
                fixed_by_tech[tid] = []
            fixed_by_tech[tid].append(fl)

        for ts in tech_stats:
            tid = ts["technician_id"]
            avg_h = float(ts["avg_fix_hours"]) if ts["avg_fix_hours"] else None
            tot_h = float(ts["total_fix_hours"]) if ts["total_fix_hours"] else None
            ts["avg_fix_hours_val"] = avg_h
            ts["avg_fix_str"] = _format_duration(avg_h)
            ts["total_fix_str"] = _format_duration(tot_h)
            ts["fixed_items"] = fixed_by_tech.get(tid, [])
            tot_a = ts["total_assigned"] or 0
            comp = ts["completed_repairs"] or 0
            ts["efficiency_rate"] = round((comp / tot_a * 100), 1) if tot_a > 0 else 0.0

        # 9. Problem Identification & Problematic Device Analytics
        window_days = None
        if time_window != "all":
            try:
                window_days = int(time_window)
            except Exception:
                window_days = 90

        pw_params = []
        pw_where = "WHERE e.is_deleted = 0 AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)"
        if window_days:
            pw_where += " AND mr.date_reported >= (NOW() - INTERVAL %s DAY)"
            pw_params.append(window_days)
        if lab:
            pw_where += " AND e.location = %s"
            pw_params.append(lab)

        cur.execute(
            f"""
            SELECT 
                e.id AS equipment_id,
                e.name AS equipment_name,
                e.category,
                e.location,
                e.status AS current_status,
                COUNT(mr.id) AS failure_count,
                SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved_count,
                SUM(CASE WHEN mr.status IN ('Pending', 'In Progress') THEN 1 ELSE 0 END) AS active_count,
                MAX(mr.date_reported) AS last_failure_date,
                MIN(mr.date_reported) AS first_failure_date,
                GROUP_CONCAT(DISTINCT COALESCE(mr.affected_component, 'General Set') ORDER BY mr.id DESC SEPARATOR ', ') AS recurring_components,
                GROUP_CONCAT(DISTINCT mr.description ORDER BY mr.id DESC SEPARATOR ' | ') AS issue_descriptions
            FROM equipment e
            JOIN maintenance_requests mr ON mr.equipment_id = e.id
            {pw_where}
            GROUP BY e.id, e.name, e.category, e.location, e.status
            ORDER BY failure_count DESC, last_failure_date DESC
            """,
            tuple(pw_params),
        )
        problematic_devices = cur.fetchall()
        for pd in problematic_devices:
            fc = pd["failure_count"]
            if fc >= 3:
                pd["flag_level"] = "Critical"
                pd["flag_label"] = "High Failure Alert"
                pd["badge_class"] = "badge-danger"
            elif fc == 2:
                pd["flag_level"] = "Warning"
                pd["flag_label"] = "Elevated Failures"
                pd["badge_class"] = "badge-warning"
            else:
                pd["flag_level"] = "Monitored"
                pd["flag_label"] = "Monitored Incident"
                pd["badge_class"] = "badge-info"

        # Problem Identification: Component failure patterns
        cur.execute(
            f"""
            SELECT 
                COALESCE(mr.affected_component, 'General Workstation / Set') AS component,
                COUNT(mr.id) AS failure_count,
                COUNT(DISTINCT e.id) AS affected_devices,
                GROUP_CONCAT(DISTINCT e.location ORDER BY e.location ASC SEPARATOR ', ') AS affected_labs
            FROM maintenance_requests mr
            JOIN equipment e ON mr.equipment_id = e.id
            {pw_where}
            GROUP BY component
            ORDER BY failure_count DESC
            LIMIT 8
            """,
            tuple(pw_params),
        )
        component_failures = cur.fetchall()

        # 10. Dedicated Individual Technician Reporting
        cur.execute("SELECT id, name, email FROM users WHERE role='technician' AND (is_deleted IS NULL OR is_deleted=0) ORDER BY name ASC")
        technicians_list = cur.fetchall()

        selected_technician = None
        individual_tech_report = None
        if technician_id:
            cur.execute("SELECT id, name, email, role, created_at FROM users WHERE id=%s AND role='technician' AND (is_deleted IS NULL OR is_deleted=0)", (technician_id,))
            selected_technician = cur.fetchone()
            if selected_technician:
                cur.execute(
                    """
                    SELECT 
                        COUNT(DISTINCT mr.id) AS total_assigned,
                        COUNT(DISTINCT CASE WHEN mr.status = 'Resolved' THEN mr.id END) AS completed_repairs,
                        COUNT(DISTINCT CASE WHEN mr.status = 'In Progress' THEN mr.id END) AS in_progress_repairs,
                        COUNT(DISTINCT CASE WHEN mr.status = 'Pending' THEN mr.id END) AS pending_repairs,
                        AVG(CASE WHEN ml.duration_minutes IS NOT NULL THEN ml.duration_minutes
                                 WHEN mr.status = 'Resolved' AND ml.date_completed IS NOT NULL
                                 THEN TIMESTAMPDIFF(MINUTE, COALESCE(mr.repair_start, mr.date_reported), ml.date_completed) END) AS avg_duration_mins,
                        SUM(CASE WHEN ml.duration_minutes IS NOT NULL THEN ml.duration_minutes
                                 WHEN mr.status = 'Resolved' AND ml.date_completed IS NOT NULL
                                 THEN TIMESTAMPDIFF(MINUTE, COALESCE(mr.repair_start, mr.date_reported), ml.date_completed) END) AS total_duration_mins
                    FROM maintenance_requests mr
                    LEFT JOIN maintenance_logs ml ON ml.request_id = mr.id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
                    WHERE mr.technician_id = %s AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
                    """,
                    (technician_id,)
                )
                t_kpis = cur.fetchone() or {}
                tot_ass = t_kpis.get("total_assigned") or 0
                comp_rep = t_kpis.get("completed_repairs") or 0
                act_rep = t_kpis.get("in_progress_repairs") or 0
                pend_rep = t_kpis.get("pending_repairs") or 0
                avg_dm = t_kpis.get("avg_duration_mins")
                tot_dm = t_kpis.get("total_duration_mins")
                eff_rate = round((comp_rep / tot_ass * 100), 1) if tot_ass > 0 else (100.0 if comp_rep > 0 else 0.0)

                cur.execute(
                    """
                    SELECT e.location, COUNT(mr.id) AS total,
                           SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved
                    FROM maintenance_requests mr
                    JOIN equipment e ON mr.equipment_id = e.id
                    WHERE mr.technician_id = %s AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
                    GROUP BY e.location
                    ORDER BY e.location ASC
                    """,
                    (technician_id,)
                )
                tech_lab_breakdown = cur.fetchall()

                cur.execute(
                    """
                    SELECT 
                        DATE_FORMAT(mr.date_reported, '%Y-%m') AS m_key,
                        DATE_FORMAT(mr.date_reported, '%M %Y') AS m_label,
                        COUNT(DISTINCT mr.id) AS assigned_count,
                        COUNT(DISTINCT CASE WHEN mr.status = 'Resolved' THEN mr.id END) AS completed_count
                    FROM maintenance_requests mr
                    WHERE mr.technician_id = %s AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
                    GROUP BY m_key, m_label
                    ORDER BY m_key DESC
                    LIMIT 12
                    """,
                    (technician_id,)
                )
                tech_monthly_metrics = cur.fetchall()

                cur.execute(
                    """
                    SELECT 
                        mr.id AS request_id,
                        e.name AS equipment_name,
                        e.category AS equipment_category,
                        e.location AS equipment_location,
                        mr.description,
                        mr.urgency,
                        mr.status,
                        mr.affected_component,
                        mr.date_reported,
                        mr.repair_start,
                        ml.date_completed,
                        ml.duration_minutes,
                        ml.action_taken,
                        u.name AS reporter_name
                    FROM maintenance_requests mr
                    JOIN equipment e ON mr.equipment_id = e.id
                    LEFT JOIN maintenance_logs ml ON ml.request_id = mr.id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
                    LEFT JOIN users u ON u.id = mr.reported_by
                    WHERE mr.technician_id = %s AND (mr.is_deleted IS NULL OR mr.is_deleted = 0)
                    ORDER BY COALESCE(ml.date_completed, mr.date_reported) DESC
                    """,
                    (technician_id,)
                )
                tech_audit_logs = cur.fetchall()
                for al in tech_audit_logs:
                    if al.get("duration_minutes") is not None:
                        al["duration_str"] = format_duration_minutes(al["duration_minutes"])
                    elif al.get("date_completed") and (al.get("repair_start") or al.get("date_reported")):
                        st = al.get("repair_start") or al.get("date_reported")
                        diff_m = max(1, int(round((al["date_completed"] - st).total_seconds() / 60.0)))
                        al["duration_str"] = format_duration_minutes(diff_m)
                    else:
                        al["duration_str"] = "—"

                individual_tech_report = {
                    "technician": selected_technician,
                    "total_assigned": tot_ass,
                    "completed_repairs": comp_rep,
                    "in_progress_repairs": act_rep,
                    "pending_repairs": pend_rep,
                    "efficiency_rate": eff_rate,
                    "avg_duration_str": format_duration_minutes(avg_dm) if avg_dm else "—",
                    "total_duration_str": format_duration_minutes(tot_dm) if tot_dm else "—",
                    "lab_breakdown": tech_lab_breakdown,
                    "monthly_metrics": tech_monthly_metrics,
                    "audit_logs": tech_audit_logs,
                }

        # Individual Technician CSV Export
        if request.args.get("export") == "tech_csv" and individual_tech_report:
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([
                "Request ID", "Equipment Name", "Category", "Laboratory",
                "Issue Description", "Urgency", "Status", "Reported Date",
                "Repair Start Date", "Completion Date", "Repair Duration", "Resolution Details", "Reported By"
            ])
            for r in individual_tech_report["audit_logs"]:
                dr = r["date_reported"].strftime("%Y-%m-%d %H:%M") if r["date_reported"] else ""
                ds = r["repair_start"].strftime("%Y-%m-%d %H:%M") if r["repair_start"] else ""
                dc = r["date_completed"].strftime("%Y-%m-%d %H:%M") if r["date_completed"] else "N/A"
                w.writerow([
                    r["request_id"],
                    r["equipment_name"],
                    r["equipment_category"],
                    r["equipment_location"] or "",
                    r["description"],
                    r["urgency"],
                    r["status"],
                    dr,
                    ds,
                    dc,
                    r["duration_str"],
                    r["action_taken"] or "",
                    r["reporter_name"] or "Unknown"
                ])
            t_name_slug = individual_tech_report["technician"]["name"].replace(" ", "_")
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=Technician_Report_{t_name_slug}_{to_str}.csv"}
            )

        # 11. Detailed Maintenance Logs (Audit Trail)
        cur.execute(
            f"""
            SELECT e.name AS equipment_name, e.category, e.location, mr.description, mr.urgency, mr.status, 
                   mr.date_reported, mr.repair_start, ml.date_completed, ml.duration_minutes,
                   TIMESTAMPDIFF(SECOND, COALESCE(mr.repair_start, mr.date_reported), ml.date_completed) / 3600.0 AS duration_hours,
                   ml.action_taken,
                   COALESCE(tech.name, req_tech.name) AS technician_name
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            LEFT JOIN maintenance_logs ml ON mr.id = ml.request_id AND (ml.is_deleted IS NULL OR ml.is_deleted = 0)
            LEFT JOIN users tech ON ml.technician_id = tech.id
            LEFT JOIN users req_tech ON mr.technician_id = req_tech.id
            WHERE {where_clause}
            ORDER BY mr.date_reported DESC
            """,
            tuple(params),
        )
        detailed_logs = cur.fetchall()
        for dl in detailed_logs:
            if dl.get("duration_minutes") is not None:
                dl["duration_str"] = format_duration_minutes(dl["duration_minutes"])
            else:
                dl["duration_str"] = _format_duration(dl.get("duration_hours"))

        # CSV Export Handling
        if request.args.get("export") == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow([
                "Equipment Name", "Category", "Location", "Description",
                "Urgency", "Status", "Assigned Technician", "Date Reported",
                "Start Date/Time", "Date Completed", "Fix Duration", "Action Taken / Resolution"
            ])
            for r in detailed_logs:
                dr = r["date_reported"].strftime("%Y-%m-%d %H:%M") if r["date_reported"] else ""
                ds = r["repair_start"].strftime("%Y-%m-%d %H:%M") if r["repair_start"] else ""
                dc = r["date_completed"].strftime("%Y-%m-%d %H:%M") if r["date_completed"] else "N/A"
                w.writerow([
                    r["equipment_name"],
                    r["category"],
                    r.get("location") or "",
                    r["description"],
                    r["urgency"],
                    r["status"],
                    r["technician_name"] or "Unassigned",
                    dr,
                    ds,
                    dc,
                    r["duration_str"],
                    r["action_taken"] or ""
                ])
            return Response(
                buf.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename=NEUST_CICT_Maintenance_Report_{to_str}.csv"}
            )

        cur.execute("SELECT DISTINCT category FROM equipment WHERE category IS NOT NULL AND category <> '' ORDER BY category ASC")
        categories = [r["category"] for r in cur.fetchall()]
        cur.close()

        # Prepare document header metadata for print view
        doc_metadata = {
            "ref_no": f"NEUST-CICT-MR-{now.strftime('%Y%m%d')}",
            "generated_at": now.strftime("%B %d, %Y %I:%M %p"),
            "prepared_by": session.get("user", {}).get("name", "System Administrator"),
            "user_role": session.get("user", {}).get("role", "Administrator").capitalize(),
        }

        return render_template(
            "admin_reports.html",
            from_str=from_str, to_str=to_str,
            category=category, status=status,
            categories=categories,
            total_equipment=total_equipment,
            total_req=total_req,
            resolved_req=resolved_req,
            pending_req=pending_req,
            in_progress_req=in_progress_req,
            rejected_req=rejected_req,
            resolution_rate=resolution_rate,
            avg_resp=round(avg_resp, 2),
            avg_resp_str=_format_duration(avg_resp),
            avg_res=round(avg_res, 2) if avg_res is not None else None,
            avg_res_str=_format_duration(avg_res),
            peak_hour_str=peak_hour_str,
            common_issues=common_issues,
            freq_rows=freq_rows,
            monthly_breakdown=monthly_breakdown,
            monthly=monthly_chart,
            tech_stats=tech_stats,
            detailed_logs=detailed_logs,
            doc_metadata=doc_metadata,
            lab=lab,
            locations=locations,
            month=month,
            available_months=available_months,
            lab_stats=lab_stats,
            lab_equipment=lab_equipment,
            lab_history=lab_history,
            all_labs_summary=all_labs_summary,
            time_window=time_window,
            problematic_devices=problematic_devices,
            component_failures=component_failures,
            technicians_list=technicians_list,
            technician_id=technician_id,
            selected_technician=selected_technician,
            individual_tech_report=individual_tech_report,
        )
    finally:
        db.close()


def _get_manual_report_data(cur):
    cur.execute(
        "SELECT id, name, category, location FROM equipment "
        "WHERE (is_deleted IS NULL OR is_deleted=0) "
        "ORDER BY location ASC, name ASC"
    )
    equipment_list = cur.fetchall()

    labs_set = set(ALLOWED_LABORATORIES)
    for eq in equipment_list:
        loc = normalize_text(eq.get("location"))
        if loc:
            labs_set.add(loc)

    def _lab_sort_key(name):
        import re
        m = re.search(r"(\d+)", name)
        return (int(m.group(1)) if m else 999, name)

    laboratories = sorted(list(labs_set), key=_lab_sort_key)
    return equipment_list, laboratories


@reports_bp.route("/manual_report", methods=["GET", "POST"])
@role_required("faculty", "admin")
@csrf_protect
def manual_report():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        if request.method == "POST":
            equipment_id = oid(request.form.get("equipment_id"))
            description  = normalize_text(request.form.get("description"))
            urgency      = normalize_text(request.form.get("urgency", "Medium"))
            reporter_id  = oid(session["user"]["id"])
            image_file   = request.files.get("image")

            errors = []
            if not equipment_id:
                errors.append("Please select an equipment.")
            payload_errors, description, urgency = validate_report_payload(description, urgency)
            errors.extend(payload_errors)

            if not errors:
                cur.execute("SELECT id FROM equipment WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)", (equipment_id,))
                if not cur.fetchone():
                    errors.append("Selected equipment not found or inactive.")

            if errors:
                equipment_list, laboratories = _get_manual_report_data(cur)
                cur.close()
                return render_template(
                    "manual_report.html",
                    equipment_list=equipment_list,
                    laboratories=laboratories,
                    errors=errors,
                    form=request.form,
                ), 400

            image_path = None
            if image_file and image_file.filename and _allowed_file(image_file.filename):
                upload_dir = current_app.config["UPLOAD_FOLDER"]
                os.makedirs(upload_dir, exist_ok=True)
                fname = secure_filename(image_file.filename)
                fname = f"{int(time.time())}_{fname}"
                image_file.save(os.path.join(upload_dir, fname))
                image_path = f"uploads/{fname}"

            affected = normalize_text(request.form.get("affected_component", "Entire Workstation / Set")) or "Entire Workstation / Set"

            cur.execute(
                "INSERT INTO maintenance_requests (equipment_id, reported_by, description, urgency, image, status, affected_component, date_reported) "
                "VALUES (%s, %s, %s, %s, %s, 'Pending', %s, %s)",
                (equipment_id, reporter_id, description, urgency, image_path, affected, now_utc().replace(tzinfo=None)),
            )

            # Trigger notifications for Technicians/Admins & Reporter confirmation
            cur.execute("SELECT id FROM users WHERE role IN ('technician', 'admin') AND (is_deleted IS NULL OR is_deleted=0)")
            recipients = [r["id"] for r in cur.fetchall()]
            if reporter_id and reporter_id not in recipients:
                recipients.append(reporter_id)

            cur.execute("SELECT name FROM equipment WHERE id=%s", (equipment_id,))
            eq_doc = cur.fetchone()
            eq_name = eq_doc["name"] if eq_doc else "Equipment"
            
            from models.db import create_notification
            for uid in recipients:
                if uid == reporter_id:
                    msg = f"Your request for '{eq_name}' was submitted successfully"
                    link = url_for("my_req.index")
                else:
                    msg = f"New maintenance request for '{eq_name}'"
                    link = url_for("requests.index")
                create_notification(db, uid, msg, link)

            db.commit()
            cur.close()
            return redirect(url_for("my_req.index"))

        # GET
        equipment_list, laboratories = _get_manual_report_data(cur)
        cur.close()
        return render_template(
            "manual_report.html",
            equipment_list=equipment_list,
            laboratories=laboratories,
            errors=[],
            form={},
            success=request.args.get("success"),
        )
    finally:
        db.close()

@reports_bp.route('/maintenance_summary')
@role_required('admin')
def maintenance_summary():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT COUNT(*) as total FROM maintenance_requests")
        total_requests = cur.fetchone()['total'] or 0

        cur.execute("SELECT status, COUNT(*) as cnt FROM maintenance_requests GROUP BY status")
        status_breakdown = cur.fetchall()

        cur.execute("SELECT AVG(TIMESTAMPDIFF(SECOND, mr.date_reported, COALESCE(mr.date_responded, NOW())) / 3600) AS avg_hours FROM maintenance_requests mr")
        avg_resolution = float(cur.fetchone()['avg_hours'] or 0)

        return render_template('reports/maintenance_summary.html',
                               total_requests=total_requests,
                               status_breakdown=status_breakdown,
                               avg_resolution=avg_resolution)
    finally:
        db.close()

@reports_bp.route('/maintenance_summary_csv')
@role_required('admin')
def maintenance_summary_csv():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT status, COUNT(*) as cnt FROM maintenance_requests GROUP BY status")
        rows = cur.fetchall()
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(['Status', 'Count'])
        for r in rows:
            w.writerow([r['status'], r['cnt']])
        return Response(buf.getvalue(), mimetype='text/csv',
                        headers={"Content-Disposition": "attachment; filename=maintenance_summary.csv"})
    finally:
        db.close()
