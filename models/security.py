import hmac
import re
import secrets
import time
from functools import wraps
from flask import abort, request, session

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PASSWORD_RE = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$")

ALLOWED_ROLES = {"admin", "custodian", "technician", "faculty"}
ALLOWED_LABORATORIES = [f"Laboratory {i}" for i in range(1, 8)]
ALLOWED_EQUIPMENT_STATUSES = {
    "Working",
    "Under Repair",
    "Not Working",
    "Under Maintenance",
    "Damaged",
    "In Progress",
    "Resolved",
    "Rejected",
}
ALLOWED_URGENCIES = {"Low", "Medium", "High", "Critical"}

_FAILED_LOGINS = {}
LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_SECONDS = 300

def normalize_text(value):
    return (value or "").strip()

def is_strong_password(password):
    if not isinstance(password, str):
        return False
    return bool(PASSWORD_RE.match(password.strip()))

def is_valid_email(email):
    if not isinstance(email, str):
        return False
    return bool(EMAIL_RE.match(email.strip()))

def is_valid_role(role):
    return role in ALLOWED_ROLES

def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return session["_csrf_token"]

def validate_csrf_token(token):
    session_token = session.get("_csrf_token")
    if not session_token or not token:
        return False
    return hmac.compare_digest(str(session_token), str(token))

def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            token = (
                request.form.get("csrf_token")
                or request.headers.get("X-CSRFToken")
                or request.headers.get("X-CSRF-Token")
            )
            if not token or not validate_csrf_token(token):
                abort(400, "Security validation failed: Invalid or missing CSRF token.")
        return f(*args, **kwargs)
    return decorated

def record_failed_login(ip):
    now = time.time()
    attempts = _FAILED_LOGINS.get(ip, [])
    attempts = [t for t in attempts if now - t < LOGIN_LOCKOUT_SECONDS]
    attempts.append(now)
    _FAILED_LOGINS[ip] = attempts

def clear_failed_logins(ip):
    _FAILED_LOGINS.pop(ip, None)

def is_login_rate_limited(ip):
    now = time.time()
    attempts = _FAILED_LOGINS.get(ip, [])
    recent_attempts = [t for t in attempts if now - t < LOGIN_LOCKOUT_SECONDS]
    _FAILED_LOGINS[ip] = recent_attempts
    return len(recent_attempts) >= LOGIN_MAX_ATTEMPTS

def validate_user_payload(name, email, role, password, is_update=False):
    errors = []
    name = normalize_text(name)
    email = normalize_text(email)
    role = normalize_text(role)

    if not name or len(name) > 120:
        errors.append("Please enter a valid name (up to 120 characters).")
    if not is_valid_email(email):
        errors.append("Please enter a valid email address.")
    if not is_valid_role(role):
        errors.append("Please select a valid role.")
    if not is_update or password:
        if not is_strong_password(password):
            errors.append("Password must be at least 12 characters long and include uppercase, lowercase, number, and special character.")
    return errors, name, email, role

def validate_equipment_payload(name, category, location, status):
    errors = []
    name = normalize_text(name)
    category = normalize_text(category)
    location = normalize_text(location)
    status = normalize_text(status)

    if not name or len(name) > 160:
        errors.append("Equipment name is required.")
    if len(category) > 160:
        errors.append("Category is too long.")
    if not location or location not in ALLOWED_LABORATORIES:
        errors.append("Equipment must be assigned to a valid laboratory (Laboratory 1 to Laboratory 7).")
    if status and status not in ALLOWED_EQUIPMENT_STATUSES:
        errors.append("Please select a valid equipment status.")
    return errors, name, category, location, status

def validate_report_payload(description, urgency):
    errors = []
    description = normalize_text(description)
    urgency = normalize_text(urgency)

    if not description:
        errors.append("Please describe the issue.")
    if len(description) > 2000:
        errors.append("Description is too long.")
    if urgency and urgency not in ALLOWED_URGENCIES:
        errors.append("Please select a valid urgency.")
    return errors, description, urgency
