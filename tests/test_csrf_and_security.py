from app import app as flask_app
from models.security import (
    generate_csrf_token,
    validate_csrf_token,
    record_failed_login,
    is_login_rate_limited,
    clear_failed_logins,
)

def _set_session(client, role="admin"):
    with client.session_transaction() as session:
        session["user"] = {
            "id": 1,
            "name": f"{role.title()} User",
            "email": f"{role}@neust.edu.ph",
            "role": role,
        }
        session["last_activity"] = "9999999999"

def test_csrf_token_generation_and_validation():
    flask_app.config.update(TESTING=True)
    with flask_app.test_request_context():
        token = generate_csrf_token()
        assert token is not None
        assert len(token) > 20
        assert validate_csrf_token(token) is True
        assert validate_csrf_token("invalid_token_123") is False
        assert validate_csrf_token("") is False
        assert validate_csrf_token(None) is False

def test_csrf_protection_rejects_missing_token_on_protected_routes():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        _set_session(client, "admin")
        response = client.post("/equipment/", data={"name": "PC #99", "category": "Desktop Workstation", "location": "Laboratory 1"})
        assert response.status_code == 400

def test_csrf_protection_allows_valid_token_in_form_or_header():
    flask_app.config.update(TESTING=True)
    with flask_app.test_request_context():
        from flask import session
        session["_csrf_token"] = "test-valid-csrf-token-12345"
        assert validate_csrf_token("test-valid-csrf-token-12345") is True
        assert validate_csrf_token("wrong-token") is False

def test_login_rate_limiting():
    ip = "192.0.2.1"

    clear_failed_logins(ip)
    assert is_login_rate_limited(ip) is False

    for _ in range(5):
        record_failed_login(ip)

    assert is_login_rate_limited(ip) is True

    clear_failed_logins(ip)
    assert is_login_rate_limited(ip) is False

def test_security_headers_present():
    flask_app.config.update(TESTING=True)
    with flask_app.test_client() as client:
        response = client.get("/login")
        assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert "strict-origin" in response.headers.get("Referrer-Policy", "")
