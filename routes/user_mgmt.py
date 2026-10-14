import os
import subprocess
import bcrypt
from flask import Blueprint, render_template, request, redirect, url_for, flash, Response, session, current_app
from models import get_db, oid, now_utc, format_date, log_activity, backup_database, restore_database
import config
from routes.decorators import role_required
from models.security import validate_user_payload, normalize_text, csrf_protect

user_mgmt_bp = Blueprint("user_mgmt", __name__, url_prefix="/user_management")

@user_mgmt_bp.route("/", methods=["GET", "POST"])
@role_required("admin")
@csrf_protect
def index():
    db = get_db()
    try:
        cur = db.cursor(dictionary=True)

        if request.method == "POST":
            name = normalize_text(request.form.get("name"))
            email = normalize_text(request.form.get("email"))
            role = normalize_text(request.form.get("role", "faculty"))
            raw_pwd = request.form.get("password", "")

            errors, name, email, role = validate_user_payload(name, email, role, raw_pwd)
            if errors:
                flash(" ".join(errors), "error")
                cur.close()
                return redirect(url_for("user_mgmt.index"))

            cur.execute("SELECT id FROM users WHERE email=%s AND (is_deleted IS NULL OR is_deleted=0) LIMIT 1", (email,))
            if cur.fetchone():
                flash("A user with this email address already exists.", "error")
                cur.close()
                return redirect(url_for("user_mgmt.index"))

            hashed = bcrypt.hashpw(raw_pwd.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            cur.execute(
                "INSERT INTO users (name, email, password, role, created_at) VALUES (%s, %s, %s, %s, %s)",
                (name, email, hashed, role, now_utc().replace(tzinfo=None)),
            )
            new_uid = cur.lastrowid
            db.commit()

            admin_id = oid(session.get("user", {}).get("id"))
            try:
                log_activity(db, admin_id, "create_user", f"Created user {email} with role {role}", "user", new_uid)
            except Exception:
                pass
            cur.close()
            flash("User created successfully.", "success")
            return redirect(url_for("user_mgmt.index"))

        if "delete" in request.args or "archive" in request.args:
            uid = oid(request.args.get("archive") or request.args.get("delete"))
            admin_id = oid(session.get("user", {}).get("id"))
            if uid and uid != admin_id:
                cur.execute("SELECT id, role, email FROM users WHERE id=%s LIMIT 1", (uid,))
                u = cur.fetchone()
                if u and u.get("role") != "admin":
                    cur.execute("UPDATE users SET is_deleted=1, deleted_at=%s WHERE id=%s", (now_utc().replace(tzinfo=None), uid))
                    db.commit()
                    try:
                        log_activity(db, admin_id, "archive_user", f"Archived user {u.get('email')}", "user", uid)
                    except Exception:
                        pass
                    flash("User archived successfully.", "success")
            cur.close()
            return redirect(url_for("user_mgmt.index"))

        cur.execute("SELECT id, name, email, role, created_at FROM users WHERE (is_deleted IS NULL OR is_deleted=0) ORDER BY id ASC")
        users = cur.fetchall()
        cur.close()
        return render_template(
            "user_management.html",
            users=users,
            format_date=format_date
        )
    finally:
        db.close()

@user_mgmt_bp.route("/delete/<int:user_id>", methods=["POST"], endpoint="delete_user")
@user_mgmt_bp.route("/archive/<int:user_id>", methods=["POST"], endpoint="archive_user")
@role_required("admin")
@csrf_protect
def delete_user(user_id):
    admin_id = oid(session.get("user", {}).get("id"))
    if user_id == admin_id:
        flash("You cannot archive your own active administrator account.", "error")
        return redirect(url_for("user_mgmt.index"))

    db = get_db()
    try:
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, role, email FROM users WHERE id=%s LIMIT 1", (user_id,))
        u = cur.fetchone()
        if not u:
            flash("User not found.", "error")
        elif u.get("role") == "admin":
            flash("Cannot archive an administrator account directly.", "error")
        else:
            cur.execute("UPDATE users SET is_deleted=1, deleted_at=%s WHERE id=%s", (now_utc().replace(tzinfo=None), user_id))
            db.commit()
            try:
                log_activity(db, admin_id, "archive_user", f"Archived user {u.get('email')}", "user", user_id)
            except Exception:
                pass
            flash("User archived successfully.", "success")
        cur.close()
    finally:
        db.close()
    return redirect(url_for("user_mgmt.index"))

@user_mgmt_bp.route("/backup")
@role_required("admin")
def backup_db():
    try:
        timestamp = now_utc().strftime("%Y%m%d_%H%M%S")
        filename = f"db_backup_{config.MYSQL_DB}_{timestamp}.sql"
        upload_dir = current_app.config.get("UPLOAD_FOLDER", "uploads")
        os.makedirs(upload_dir, exist_ok=True)
        output_path = os.path.join(upload_dir, filename)

        backup_path = backup_database(output_path)
        with open(backup_path, "rb") as handle:
            content = handle.read()
        return Response(
            content,
            mimetype="application/sql",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as exc:
        flash(f"Database backup failed: {exc}", "error")
        return redirect(url_for("user_mgmt.index"))

@user_mgmt_bp.route("/restore", methods=["POST"])
@role_required("admin")
@csrf_protect
def restore_db():
    file_storage = request.files.get("backup_file")
    if not file_storage or not file_storage.filename:
        flash("Please choose a backup file (.sql) to restore.", "error")
        return redirect(url_for("user_mgmt.index"))

    try:
        sql_text = file_storage.read().decode("utf-8")
        restore_database(sql_text)
        flash("Database restore completed successfully.", "success")
    except Exception as exc:
        flash(f"Database restore failed: {exc}", "error")

    return redirect(url_for("user_mgmt.index"))
