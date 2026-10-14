import unittest
from unittest.mock import patch
from app import app as flask_app
import routes.user_mgmt as user_mgmt_module
import routes.equipment as equipment_module
import routes.requests as requests_module
import routes.notifications as notif_module

def _set_session(client, role="admin", user_id=1, user_name=None):
    with client.session_transaction() as session:
        session["user"] = {
            "id": user_id,
            "name": user_name or f"{role.title()} User",
            "email": f"{role}@neust.edu.ph",
            "role": role,
        }
        session["last_activity"] = "9999999999"
        session["_csrf_token"] = "valid-token-for-test-xyz"

class TestAdminAndManagement(unittest.TestCase):
    def test_admin_cannot_delete_own_account(self):
        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            _set_session(client, "admin", user_id=1)
            response = client.post(
                "/user_management/delete/1",
                data={"csrf_token": "valid-token-for-test-xyz"},
                follow_redirects=False
            )
            self.assertEqual(response.status_code, 302)
            self.assertIn("/user_management", response.headers.get("Location", ""))

    def test_equipment_delete_endpoint_requires_csrf(self):
        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            _set_session(client, "admin", user_id=1)
            response = client.post("/equipment/delete/99")
            self.assertEqual(response.status_code, 400)

    def test_request_status_update_resolved_requires_action(self):
        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None
            def fetchone(self):
                return {"equipment_id": 1, "reported_by": 2, "equipment_name": "PC 01"}
            def close(self):
                return None

        class FakeDB:
            def cursor(self, dictionary=True):
                return FakeCursor()
            def commit(self):
                return None
            def close(self):
                return None

        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            _set_session(client, "technician", user_id=3)
            with patch.object(requests_module, "get_db", return_value=FakeDB()):
                response = client.post(
                    "/maintenance_requests/",
                    data={
                        "csrf_token": "valid-token-for-test-xyz",
                        "request_id": "10",
                        "status": "Resolved",
                        "action_taken": "",
                    },
                    follow_redirects=False
                )
                self.assertEqual(response.status_code, 302)
                self.assertIn("error=action_required", response.headers["Location"])

    def test_notifications_unread_api(self):
        class FakeCursor:
            def execute(self, *args, **kwargs):
                return None
            def fetchone(self):
                return {"c": 3}
            def fetchall(self):
                return [
                    {"id": 1, "message": "Test notif 1", "link": "/my_requests", "is_read": 0, "created_at": None},
                    {"id": 2, "message": "Test notif 2", "link": "/my_requests", "is_read": 0, "created_at": None},
                ]
            def close(self):
                return None

        class FakeDB:
            def cursor(self, dictionary=True):
                return FakeCursor()
            def commit(self):
                return None
            def close(self):
                return None

        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            resp = client.get("/notifications/api/unread")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.json["count"], 0)

            _set_session(client, "faculty", user_id=9)
            with patch.object(notif_module, "get_db", return_value=FakeDB()):
                resp = client.get("/notifications/api/unread")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json["count"], 3)
                self.assertEqual(len(resp.json["notifications"]), 2)

    def test_equipment_soft_delete_flow(self):
        deleted_queries = []

        class FakeCursor:
            def execute(self, sql, params=None):
                deleted_queries.append((sql, params))
            def fetchone(self):
                return {"id": 15, "name": "Lab 1 PC 05"}
            def close(self):
                return None

        class FakeDB:
            def cursor(self, dictionary=True):
                return FakeCursor()
            def commit(self):
                return None
            def close(self):
                return None

        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            _set_session(client, "admin", user_id=1)
            with patch.object(equipment_module, "get_db", return_value=FakeDB()):
                response = client.post(
                    "/equipment/delete/15",
                    data={"csrf_token": "valid-token-for-test-xyz"},
                    follow_redirects=False
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.headers["Location"].endswith("/equipment/"))
                self.assertTrue(any("is_deleted=1" in q[0] for q in deleted_queries))

    def test_technician_submit_verification_workflow(self):
        executed_queries = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed_queries.append((sql, params))
            def fetchone(self):
                return {
                    "id": 20,
                    "equipment_id": 5,
                    "reported_by": 2,
                    "equipment_name": "Projector 01",
                    "status": "In Progress",
                    "technician_id": 3
                }
            def fetchall(self):
                return [{"id": 1}]
            def close(self):
                return None

        class FakeDB:
            def cursor(self, dictionary=True):
                return FakeCursor()
            def commit(self):
                return None
            def close(self):
                return None

        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            _set_session(client, "technician", user_id=3, user_name="Tech Bob")
            with patch.object(requests_module, "get_db", return_value=FakeDB()):
                response = client.post(
                    "/maintenance_requests/",
                    data={
                        "csrf_token": "valid-token-for-test-xyz",
                        "request_id": "20",
                        "status": "Completed - Pending Verification",
                        "action_taken": "Cleaned lens and replaced bulb",
                    },
                    follow_redirects=False
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(any("technician_notes" in q[0] and "Completed - Pending Verification" in q[1] for q in executed_queries))
                self.assertTrue(any("notifications" in q[0] and "Awaiting your verification" in str(q[1]) for q in executed_queries))

    def test_admin_verify_and_resolve_workflow(self):
        executed_queries = []

        class FakeCursor:
            def execute(self, sql, params=None):
                executed_queries.append((sql, params))
            def fetchone(self):
                return {
                    "id": 20,
                    "equipment_id": 5,
                    "reported_by": 2,
                    "equipment_name": "Projector 01",
                    "status": "Completed - Pending Verification",
                    "technician_id": 3,
                    "technician_notes": "Cleaned lens and replaced bulb",
                    "repair_start": None,
                    "date_reported": None
                }
            def close(self):
                return None

        class FakeDB:
            def cursor(self, dictionary=True):
                return FakeCursor()
            def commit(self):
                return None
            def close(self):
                return None

        flask_app.config.update(TESTING=True)
        with flask_app.test_client() as client:
            _set_session(client, "admin", user_id=1, user_name="Admin Boss")
            with patch.object(requests_module, "get_db", return_value=FakeDB()):
                response = client.post(
                    "/maintenance_requests/",
                    data={
                        "csrf_token": "valid-token-for-test-xyz",
                        "request_id": "20",
                        "status": "Resolved",
                        "action_taken": "Cleaned lens and replaced bulb",
                    },
                    follow_redirects=False
                )
                self.assertEqual(response.status_code, 302)
                self.assertTrue(any("INSERT INTO maintenance_logs" in q[0] for q in executed_queries))
                self.assertTrue(any("UPDATE equipment SET status='Working'" in q[0] for q in executed_queries))
                self.assertTrue(any("notifications" in q[0] and "verified and resolved by Admin" in str(q[1]) for q in executed_queries))
