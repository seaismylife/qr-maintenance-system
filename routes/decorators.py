from functools import wraps
from flask import session, redirect, url_for, abort, request
from datetime import datetime, timezone

def _enforce_session_timeout():
    if "user" not in session:
        return False
    last_activity = session.get("last_activity")
    if last_activity is None:
        session["last_activity"] = datetime.now(timezone.utc).timestamp()
        return True
    try:
        if (datetime.now(timezone.utc).timestamp() - float(last_activity)) > 1800:
            session.clear()
            return False
    except (TypeError, ValueError):
        session.clear()
        return False
    session["last_activity"] = datetime.now(timezone.utc).timestamp()
    return True

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("auth.login"))
        if not _enforce_session_timeout():
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user" not in session:
                return redirect(url_for("auth.login"))
            if not _enforce_session_timeout():
                return redirect(url_for("auth.login"))
            if session["user"]["role"] not in roles:
                abort(403)
            return f(*args, **kwargs)
        return decorated
    return decorator
