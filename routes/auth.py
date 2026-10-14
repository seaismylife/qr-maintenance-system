from datetime import datetime, timezone
from urllib.parse import urlparse
import bcrypt
from flask import Blueprint, render_template, request, session, redirect, url_for
from models import get_db, log_activity
from models.security import (
    normalize_text,
    is_valid_email,
    is_login_rate_limited,
    record_failed_login,
    clear_failed_logins,
)

auth_bp = Blueprint("auth", __name__)

def _safe_next(target):
    if not target:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    return target

@auth_bp.route("/", methods=["GET", "POST"])
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        nxt = _safe_next(request.args.get("next"))
        if nxt:
            return redirect(nxt)
        return redirect(url_for(f"dashboard.{session['user']['role']}"))

    error = ""
    next_url = _safe_next(request.args.get("next") or request.form.get("next"))
    ip_addr = request.remote_addr or "127.0.0.1"

    if request.method == "POST":
        if is_login_rate_limited(ip_addr):
            error = "Too many failed login attempts. Please wait 5 minutes before trying again."
            return render_template("login.html", error=error, next_url=next_url), 429

        email = normalize_text(request.form.get("email"))
        pwd = request.form.get("password", "")
        remember = bool(request.form.get("remember"))

        if not is_valid_email(email):
            error = "Please enter a valid email address."
        else:
            db = get_db()
            try:
                cur = db.cursor(dictionary=True)
                cur.execute(
                    "SELECT id, name, email, role, password FROM users WHERE email=%s AND (is_deleted IS NULL OR is_deleted=0) LIMIT 1",
                    (email,),
                )
                user = cur.fetchone()
                cur.close()

                if user and bcrypt.checkpw(pwd.encode("utf-8"), user["password"].encode("utf-8")):
                    clear_failed_logins(ip_addr)
                    session.clear()
                    session.permanent = remember
                    session["user"] = {
                        "id": int(user["id"]),
                        "name": user["name"],
                        "email": user["email"],
                        "role": user["role"],
                    }
                    session["last_activity"] = str(datetime.now(timezone.utc).timestamp())

                    try:
                        log_activity(db, user["id"], "login", f"User logged in: {user['email']}", "user", user["id"])
                    except Exception:
                        pass

                    nxt = _safe_next(request.form.get("next"))
                    if nxt:
                        return redirect(nxt)
                    return redirect(url_for(f"dashboard.{user['role']}"))
                else:
                    record_failed_login(ip_addr)
                    error = "Invalid email or password."
            finally:
                db.close()

    return render_template("login.html", error=error, next_url=next_url)

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
