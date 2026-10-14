"""
Verification tests for technician task isolation, claiming, and backend security guards.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import get_db

class TestTechnicianTaskIsolation(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, name, email, role FROM users WHERE id IN (1, 6, 7)")
        self.users = {u["id"]: u for u in cur.fetchall()}
        cur.close()
        db.close()

    def test_technician_can_only_see_own_assigned_tasks(self):
        user6_str = dict(self.users[6])
        user6_str["id"] = str(user6_str["id"])
        with self.client.session_transaction() as sess:
            sess["user_id"] = str(user6_str["id"])
            sess["user"] = user6_str
            sess["role"] = "technician"

        resp = self.client.get("/maintenance_requests/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        self.assertIn('name="request_id" value="2"', html)
        self.assertIn('name="request_id" value="3"', html)
        self.assertIn('name="request_id" value="4"', html)

        self.assertIn('<select name="status"', html)
        self.assertIn('Submit', html)
        self.assertNotIn('Assigned to Technician User</div>', html)

        self.assertNotIn('name="request_id" value="1"', html)
        self.assertNotIn('name="request_id" value="5"', html)

    def test_tech2_can_only_see_own_assigned_tasks(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 7
            sess["user"] = self.users[7]
            sess["role"] = "technician"

        resp = self.client.get("/maintenance_requests/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        self.assertIn('name="request_id" value="1"', html)
        self.assertIn('name="request_id" value="5"', html)

        self.assertNotIn('name="request_id" value="2"', html)
        self.assertNotIn('name="request_id" value="3"', html)
        self.assertNotIn('name="request_id" value="4"', html)

    def test_technician_cannot_modify_another_technicians_task(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 6
            sess["user"] = self.users[6]
            sess["role"] = "technician"
            sess["_csrf_token"] = "valid_csrf_token"

        resp = self.client.post("/maintenance_requests/", data={
            "csrf_token": "valid_csrf_token",
            "request_id": 1,
            "equipment_id": 11,
            "status": "In Progress"
        })
        self.assertEqual(resp.status_code, 403)

    def test_admin_can_see_all_technician_tasks(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = 1
            sess["user"] = self.users[1]
            sess["role"] = "admin"

        resp = self.client.get("/maintenance_requests/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")

        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)
        self.assertIn('value="3"', html)
        self.assertIn('value="4"', html)
        self.assertIn('value="5"', html)

    def test_technician_cannot_see_or_claim_unassigned_task(self):
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute(
            "INSERT INTO maintenance_requests (equipment_id, reported_by, description, urgency, status, technician_id) "
            "VALUES (12, 1, 'Admin assignment test issue', 'Medium', 'Pending', NULL)"
        )
        test_req_id = cur.lastrowid
        db.commit()

        try:
            with self.client.session_transaction() as sess:
                sess["user_id"] = 6
                sess["user"] = self.users[6]
                sess["role"] = "technician"

            resp = self.client.get("/maintenance_requests/")
            html = resp.data.decode("utf-8")
            self.assertNotIn(f'value="{test_req_id}"', html)
            self.assertNotIn("Claim Task", html)

            with self.client.session_transaction() as sess:
                sess["user_id"] = 6
                sess["user"] = self.users[6]
                sess["role"] = "technician"
                sess["_csrf_token"] = "claim_token"

            claim_resp = self.client.post("/maintenance_requests/", data={
                "csrf_token": "claim_token",
                "request_id": test_req_id,
                "equipment_id": 12,
                "status": "In Progress"
            })
            self.assertEqual(claim_resp.status_code, 403)

            with self.client.session_transaction() as sess:
                sess["user_id"] = 1
                sess["user"] = self.users[1]
                sess["role"] = "admin"

            admin_resp = self.client.get("/maintenance_requests/")
            admin_html = admin_resp.data.decode("utf-8")
            self.assertIn(f'value="{test_req_id}"', admin_html)

            with self.client.session_transaction() as sess:
                sess["user_id"] = 1
                sess["user"] = self.users[1]
                sess["role"] = "admin"
                sess["_csrf_token"] = "assign_token"

            assign_resp = self.client.post(f"/maintenance_requests/assign/{test_req_id}", data={
                "csrf_token": "assign_token",
                "technician_id": 6
            }, follow_redirects=True)
            self.assertEqual(assign_resp.status_code, 200)

            with self.client.session_transaction() as sess:
                sess["user_id"] = 6
                sess["user"] = self.users[6]
                sess["role"] = "technician"

            resp_tech6 = self.client.get("/maintenance_requests/")
            html_tech6 = resp_tech6.data.decode("utf-8")
            self.assertIn(f'value="{test_req_id}"', html_tech6)

            with self.client.session_transaction() as sess:
                sess["user_id"] = 7
                sess["user"] = self.users[7]
                sess["role"] = "technician"

            resp_tech2 = self.client.get("/maintenance_requests/")
            html_tech2 = resp_tech2.data.decode("utf-8")
            self.assertNotIn(f'value="{test_req_id}"', html_tech2)

        finally:
            cur.execute("DELETE FROM maintenance_requests WHERE id=%s", (test_req_id,))
            db.commit()
            cur.close()
            db.close()

if __name__ == "__main__":
    unittest.main()
