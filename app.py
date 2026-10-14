import html
import os
import time
from datetime import timedelta
from flask import Flask, session, request, render_template, send_from_directory, redirect, url_for, jsonify
import config
from routes import (
    auth_bp,
    dashboard_bp,
    equipment_bp,
    requests_bp,
    reports_bp,
    user_mgmt_bp,
    submit_bp,
    my_req_bp,
    qr_bp,
    scan_bp,
    logbook_bp,
    notifications_bp,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["SESSION_REFRESH_EACH_REQUEST"] = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = config.SESSION_COOKIE_SECURE
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

# Ensure uploads directory exists on application start
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

# Support reverse proxy headers (Nginx, Apache, Cloudflare, AWS ALB)
if config.BEHIND_PROXY:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=config.PROXY_FIX_NUM_PROXIES,
        x_proto=config.PROXY_FIX_NUM_PROXIES,
        x_host=config.PROXY_FIX_NUM_PROXIES,
        x_prefix=config.PROXY_FIX_NUM_PROXIES,
    )

# Register Blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(dashboard_bp)
app.register_blueprint(equipment_bp)
app.register_blueprint(requests_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(user_mgmt_bp)
app.register_blueprint(submit_bp)
app.register_blueprint(my_req_bp)
app.register_blueprint(qr_bp)
app.register_blueprint(scan_bp)
app.register_blueprint(logbook_bp)
app.register_blueprint(notifications_bp)



@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=2592000"
    return response


@app.route("/health")
def health_check():
    """Production health check endpoint for monitoring, load balancers, and Docker."""
    db_status = "unknown"
    table_columns = {}
    try:
        from models import get_db
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        for tbl in ["users", "equipment", "maintenance_requests", "maintenance_logs"]:
            try:
                cur.execute(f"SHOW COLUMNS FROM `{tbl}`")
                table_columns[tbl] = [r[0] for r in cur.fetchall()]
            except Exception as te:
                table_columns[tbl] = f"error: {te}"
        cur.close()
        db.close()
        db_status = "connected"
    except Exception as e:
        return jsonify({
            "status": "unhealthy",
            "database": f"error: {str(e)}",
            "version": "1.0.6",
        }), 503

    return jsonify({
        "status": "healthy",
        "database": db_status,
        "environment": config.ENV,
        "version": "1.0.6",
        "table_columns": table_columns,
    }), 200



@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename)


@app.template_filter("clean")
def clean_filter(value):
    return html.escape(str(value)) if value is not None else ""


@app.template_filter("basename")
def basename_filter(value):
    return os.path.basename(str(value)) if value is not None else ""


@app.context_processor
def inject_global():
    from models.security import generate_csrf_token
    user = session.get("user")

    def filemtime(path):
        full_path = os.path.join(app.root_path, path)
        try:
            return int(os.path.getmtime(full_path))
        except OSError:
            return int(time.time())

    from models import status_badge
    return {
        "user": user,
        "BASE_URL": "",
        "filemtime": filemtime,
        "script_filename": request.endpoint,
        "csrf_token": generate_csrf_token,
        "status_badge": status_badge,
    }



@app.errorhandler(400)
def bad_request_error(e):
    err_msg = getattr(e, "description", "Bad Request.")
    user = session.get("user")
    if user:
        return render_template("error.html", code=400, title="Bad Request", message=f"Request error: {err_msg}", user=user), 400
    return render_template("login.html", error=f"Request error: {err_msg}"), 400


@app.errorhandler(403)
def forbidden_error(e):
    user = session.get("user")
    if user:
        return render_template(
            "error.html",
            code=403,
            title="Access Restricted",
            message="You do not have permission to access this area. If you need elevated access, please contact your laboratory administrator.",
            user=user
        ), 403
    return redirect(url_for("auth.login", next=request.path))


@app.errorhandler(404)
def not_found_error(e):
    user = session.get("user")
    if user:
        return render_template(
            "error.html",
            code=404,
            title="Page Not Found",
            message="The requested system resource or page could not be located.",
            user=user
        ), 404
    return render_template("login.html", error="The requested page was not found."), 404


@app.errorhandler(500)
def internal_server_error(e):
    app.logger.error(f"Internal Server Error: {e}", exc_info=True)
    user = session.get("user")
    orig_err = getattr(e, "original_exception", e)
    err_detail = f"An unexpected system error occurred: {orig_err}"
    if user:
        return render_template(
            "error.html",
            code=500,
            title="Server Error",
            message=err_detail,
            user=user
        ), 500
    return render_template("login.html", error=f"A server error occurred: {orig_err}"), 500


if __name__ == "__main__":
    app.run(host=config.HOST, debug=config.DEBUG, port=config.PORT)

