import bcrypt
from unittest.mock import patch
from app import app as flask_app
import routes.auth as auth_module

def test_login_logs_activity_before_db_closes():
    class FakeCursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return {
                "id": 7,
                "name": "Admin User",
                "email": "admin@example.com",
                "role": "admin",
                "password": bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode(),
            }

        def close(self):
            return None

    class FakeDB:
        def __init__(self):
            self.closed = False

        def cursor(self, dictionary=True):
            return FakeCursor()

        def commit(self):
            return None

        def close(self):
            self.closed = True

    db = FakeDB()
    captured = {}

    def fake_log_activity(db_obj, actor_id, action, details=None, target_type=None, target_id=None):
        captured["db_closed"] = db_obj.closed
        captured["actor_id"] = actor_id
        captured["action"] = action

    with patch.object(auth_module, "get_db", return_value=db), \
         patch.object(auth_module, "log_activity", side_effect=fake_log_activity):
        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            response = client.post(
                "/login",
                data={"email": "admin@example.com", "password": "secret"},
                follow_redirects=False,
            )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard/admin")
    assert captured["db_closed"] is False
    assert captured["actor_id"] == 7
    assert captured["action"] == "login"

def test_technician_login_redirects_to_technician_dashboard():
    class FakeCursor:
        def execute(self, *args, **kwargs):
            return None

        def fetchone(self):
            return {
                "id": 4,
                "name": "Technician User",
                "email": "technician@example.com",
                "role": "technician",
                "password": bcrypt.hashpw(b"tech123", bcrypt.gensalt()).decode(),
            }

        def close(self):
            return None

    class FakeDB:
        def __init__(self):
            self.closed = False

        def cursor(self, dictionary=True):
            return FakeCursor()

        def commit(self):
            return None

        def close(self):
            self.closed = True

    with patch.object(auth_module, "get_db", return_value=FakeDB()), \
         patch.object(auth_module, "log_activity", return_value=None):
        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            response = client.post(
                "/login",
                data={"email": "technician@example.com", "password": "tech123"},
                follow_redirects=False,
            )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard/technician")
