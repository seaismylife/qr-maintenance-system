"""
Integration workflow verification testing routes with Flask test_client.
"""

import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import app
from models import get_db


class TestRoutesWorkflow(unittest.TestCase):
    def setUp(self):
        self.app = app
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        # Find or use an admin user from the database
        db = get_db()
        cur = db.cursor(dictionary=True)
        cur.execute("SELECT id, name, email, role FROM users WHERE role = 'admin' LIMIT 1")
        self.admin_user = cur.fetchone()
        
        cur.execute("SELECT id, name, email, role FROM users WHERE role = 'technician' LIMIT 1")
        self.tech_user = cur.fetchone()

        cur.close()
        db.close()

    def test_admin_dashboard_loads(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user["id"]
            sess["user"] = self.admin_user
            sess["role"] = "admin"

        resp = self.client.get("/dashboard/admin")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Equipment Currently Under Repair", html)
        self.assertIn("Technician Repairs This Month", html)
        self.assertIn("Frequently Broken Equipment", html)

    def test_equipment_management_laboratory_options(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user["id"]
            sess["user"] = self.admin_user
            sess["role"] = "admin"

        resp = self.client.get("/equipment/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        for i in range(1, 8):
            self.assertIn(f"Laboratory {i}", html)
        self.assertIn("Under Repair", html)
        self.assertIn("Not Working", html)

    def test_admin_reports_all_sections(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user["id"]
            sess["user"] = self.admin_user
            sess["role"] = "admin"

        resp = self.client.get("/admin_reports/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        
        # Check Section 3.0 (7-Lab Matrix)
        for i in range(1, 8):
            self.assertIn(f"Laboratory {i}", html)
        
        # Check Section 4.0 (Problem Identification)
        self.assertIn("Equipment Needing Frequent Repair", html)
        self.assertIn("Equipment with Multiple Repair Records", html)
        
        # Check Section 5.0 (Technician Performance)
        self.assertIn("Technician Performance &amp; Workload", html)

        # Check Section 6.0 (Recurring Incidents)
        self.assertIn("Most Common Equipment Issues", html)

        # Check Section 7.0 (Audit Trail with Calculated Duration)
        self.assertIn("Complete Maintenance Log History", html)
        self.assertIn("Repair Duration", html)
        self.assertIn("Start Date &amp; Time", html)

    def test_admin_reports_individual_technician_dossier(self):
        if not self.tech_user:
            return
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user["id"]
            sess["user"] = self.admin_user
            sess["role"] = "admin"

        resp = self.client.get(f"/admin_reports/?technician_id={self.tech_user['id']}&time_window=90")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn(self.tech_user["name"], html)

    def test_logbook_view(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.admin_user["id"]
            sess["user"] = self.admin_user
            sess["role"] = "admin"

        # View Logbook
        resp = self.client.get("/logbook/")
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode("utf-8")
        self.assertIn("Action Taken / Resolution", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
