from flask import Blueprint, render_template, session
from models import get_db, status_badge, oid, format_date
from routes.decorators import role_required

my_req_bp = Blueprint("my_req", __name__, url_prefix="/my_requests")

@my_req_bp.route("/")
@role_required("faculty")
def index():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        my_id = oid(session["user"]["id"])
        rows = []
        if my_id:
            cur.execute(
                "SELECT r.*, e.name AS equipment_name, e.category AS equipment_category, e.location AS equipment_location, "
                "tech.name AS technician_name "
                "FROM maintenance_requests r "
                "JOIN equipment e ON r.equipment_id = e.id "
                "LEFT JOIN users tech ON r.technician_id = tech.id "
                "WHERE r.reported_by = %s AND (r.is_deleted IS NULL OR r.is_deleted=0) "
                "ORDER BY (CASE WHEN r.urgency = 'Critical' THEN 0 WHEN r.urgency = 'High' THEN 1 WHEN r.urgency = 'Medium' THEN 2 WHEN r.urgency = 'Low' THEN 3 ELSE 4 END), r.date_reported DESC",
                (my_id,),
            )
            rows = cur.fetchall()
        cur.close()
        return render_template(
            "my_requests.html",
            rows=rows,
            status_badge=status_badge,
            format_date=format_date,
        )
    finally:
        db.close()
