from flask import Blueprint, jsonify, session, request
from models import get_db, oid, format_date

notifications_bp = Blueprint("notifications", __name__, url_prefix="/notifications")

@notifications_bp.route("/api/unread", methods=["GET"])
def get_unread():
    user = session.get("user")
    if not user:
        return jsonify({"count": 0, "notifications": []})

    user_id = oid(user.get("id"))
    if not user_id:
        return jsonify({"count": 0, "notifications": []})

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE user_id = %s AND is_read = 0",
            (user_id,)
        )
        count = cur.fetchone()["c"]

        cur.execute(
            "SELECT id, message, link, is_read, created_at FROM notifications WHERE user_id = %s ORDER BY created_at DESC LIMIT 15",
            (user_id,)
        )
        rows = cur.fetchall()
        cur.close()

        items = []
        for r in rows:
            items.append({
                "id": r["id"],
                "message": r["message"],
                "link": r["link"],
                "is_read": bool(r["is_read"]),
                "created_at": format_date(r["created_at"])
            })

        return jsonify({"count": count, "notifications": items})
    finally:
        db.close()

@notifications_bp.route("/api/read/<int:notif_id>", methods=["POST"])
def mark_read(notif_id):
    user = session.get("user")
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = oid(user.get("id"))
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = %s AND user_id = %s",
            (notif_id, user_id)
        )
        db.commit()
        cur.close()
        return jsonify({"success": True})
    finally:
        db.close()

@notifications_bp.route("/api/read-all", methods=["POST"])
def mark_all_read():
    user = session.get("user")
    if not user:
        return jsonify({"success": False, "error": "Unauthorized"}), 401

    user_id = oid(user.get("id"))
    db = get_db()
    try:
        cur = db.cursor()
        cur.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = %s",
            (user_id,)
        )
        db.commit()
        cur.close()
        return jsonify({"success": True})
    finally:
        db.close()
