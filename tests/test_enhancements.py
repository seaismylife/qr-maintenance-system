"""
Automated unit and integration test suite for multi-laboratory tracking,
technician performance metrics, equipment status indicators, and problematic device analytics.
"""

import sys
import os
import unittest
from datetime import datetime, timedelta

# Ensure project root is on path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from models import (
    format_duration_minutes,
    status_badge,
    ALLOWED_LABORATORIES,
    ALLOWED_EQUIPMENT_STATUSES,
    validate_equipment_payload,
    get_db,
)


class TestLaboratoryAndStatusScope(unittest.TestCase):
    """Verifies strict Laboratory 1 through 7 and equipment condition indicators."""

    def test_allowed_laboratories(self):
        expected_labs = [
            "Laboratory 1",
            "Laboratory 2",
            "Laboratory 3",
            "Laboratory 4",
            "Laboratory 5",
            "Laboratory 6",
            "Laboratory 7",
        ]
        self.assertEqual(ALLOWED_LABORATORIES, expected_labs)
        self.assertEqual(len(ALLOWED_LABORATORIES), 7)

    def test_allowed_equipment_statuses(self):
        self.assertIn("Working", ALLOWED_EQUIPMENT_STATUSES)
        self.assertIn("Under Repair", ALLOWED_EQUIPMENT_STATUSES)
        self.assertIn("Not Working", ALLOWED_EQUIPMENT_STATUSES)

    def test_validate_equipment_payload_valid(self):
        for lab in ALLOWED_LABORATORIES:
            for status in ("Working", "Under Repair", "Not Working"):
                errors, name, cat, loc, st = validate_equipment_payload(
                    "Dell OptiPlex 7090", "Computer", lab, status
                )
                self.assertEqual(errors, [], f"Unexpected error for {lab} with status {status}")
                self.assertEqual(loc, lab)
                self.assertEqual(st, status)

    def test_validate_equipment_payload_invalid_lab(self):
        invalid_labs = ["Laboratory 8", "Laboratory 0", "RM101", "Lab 1", "", "Other Lab"]
        for lab in invalid_labs:
            errors, name, cat, loc, st = validate_equipment_payload(
                "Dell OptiPlex 7090", "Computer", lab, "Working"
            )
            self.assertTrue(
                any("Laboratory" in e for e in errors),
                f"Expected error for invalid laboratory '{lab}'",
            )

    def test_validate_equipment_payload_invalid_status(self):
        invalid_statuses = ["Broken", "Discarded", "In Use", "Archived", "Active"]
        for status in invalid_statuses:
            errors, name, cat, loc, st = validate_equipment_payload(
                "Dell OptiPlex 7090", "Computer", "Laboratory 1", status
            )
            self.assertTrue(
                any("status" in e.lower() for e in errors),
                f"Expected status validation error for '{status}'",
            )


class TestStatusBadgesAndDurationFormatting(unittest.TestCase):
    """Tests badge styling mapping and duration string calculations."""

    def test_status_badge_classes(self):
        self.assertEqual(status_badge("Working"), "badge-success")
        self.assertEqual(status_badge("Under Repair"), "badge-warning")
        self.assertEqual(status_badge("Under Maintenance"), "badge-warning")
        self.assertEqual(status_badge("Not Working"), "badge-danger")
        self.assertEqual(status_badge("Damaged"), "badge-danger")
        self.assertEqual(status_badge("In Progress"), "badge-warning")
        self.assertEqual(status_badge("Completed - Pending Verification"), "badge-info")
        self.assertEqual(status_badge("Pending Verification"), "badge-info")
        self.assertEqual(status_badge("Resolved"), "badge-success")
        self.assertEqual(status_badge("Pending"), "badge-warning")

    def test_format_duration_minutes(self):
        self.assertEqual(format_duration_minutes(0), "< 1m")
        self.assertEqual(format_duration_minutes(15), "15m")
        self.assertEqual(format_duration_minutes(59), "59m")
        self.assertEqual(format_duration_minutes(60), "1h")
        self.assertEqual(format_duration_minutes(90), "1h 30m")
        self.assertEqual(format_duration_minutes(1440), "24h")
        self.assertEqual(format_duration_minutes(1530), "25h 30m")
        self.assertEqual(format_duration_minutes(None), "—")
        self.assertEqual(format_duration_minutes(-5), "—")


class TestDatabaseSchemaAndQueries(unittest.TestCase):
    """Integration tests checking database columns, queries, and constraints."""

    def setUp(self):
        self.db = get_db()
        self.cur = self.db.cursor(dictionary=True)

    def tearDown(self):
        self.cur.close()
        self.db.close()

    def test_maintenance_requests_repair_start_column(self):
        self.cur.execute("SHOW COLUMNS FROM maintenance_requests LIKE 'repair_start'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "repair_start column must exist on maintenance_requests")

    def test_maintenance_requests_technician_notes_column(self):
        self.cur.execute("SHOW COLUMNS FROM maintenance_requests LIKE 'technician_notes'")
        row = self.cur.fetchone()
        self.assertIsNotNone(row, "technician_notes column must exist on maintenance_requests")

    def test_maintenance_logs_enhancement_columns(self):
        self.cur.execute("SHOW COLUMNS FROM maintenance_logs LIKE 'repair_start'")
        self.assertIsNotNone(self.cur.fetchone(), "repair_start column must exist on maintenance_logs")

        self.cur.execute("SHOW COLUMNS FROM maintenance_logs LIKE 'duration_minutes'")
        self.assertIsNotNone(self.cur.fetchone(), "duration_minutes column must exist on maintenance_logs")

        self.cur.execute("SHOW COLUMNS FROM maintenance_logs LIKE 'technician_id'")
        self.assertIsNotNone(self.cur.fetchone(), "technician_id column must exist on maintenance_logs")

        self.cur.execute("SHOW COLUMNS FROM maintenance_logs LIKE 'is_deleted'")
        self.assertIsNotNone(self.cur.fetchone(), "is_deleted column must exist on maintenance_logs")

        self.cur.execute("SHOW COLUMNS FROM maintenance_logs LIKE 'deleted_at'")
        self.assertIsNotNone(self.cur.fetchone(), "deleted_at column must exist on maintenance_logs")

    def test_active_under_repair_query(self):
        """Checks query structure used in Admin Dashboard Active Work Tracker."""
        sql = """
            SELECT 
                mr.id AS request_id,
                mr.equipment_id,
                mr.description,
                mr.urgency,
                mr.affected_component,
                mr.status,
                mr.repair_start,
                mr.date_reported,
                e.name AS equipment_name,
                e.category AS equipment_category,
                e.location AS equipment_location,
                u.name AS technician_name
            FROM maintenance_requests mr
            JOIN equipment e ON e.id = mr.equipment_id
            LEFT JOIN users u ON u.id = mr.technician_id
            WHERE mr.status = 'In Progress' AND (e.is_deleted IS NULL OR e.is_deleted = 0)
            ORDER BY COALESCE(mr.repair_start, mr.date_reported) ASC
        """
        self.cur.execute(sql)
        rows = self.cur.fetchall()
        self.assertIsInstance(rows, list)

    def test_monthly_technician_workload_query(self):
        """Checks monthly technician assigned vs completed metrics."""
        sql = """
            SELECT 
                u.id AS technician_id,
                u.name AS technician_name,
                COUNT(mr.id) AS assigned_count,
                SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS completed_count,
                SUM(CASE WHEN mr.status = 'In Progress' THEN 1 ELSE 0 END) AS in_progress_count,
                AVG(CASE WHEN mr.status = 'Resolved' AND ml.duration_minutes IS NOT NULL THEN ml.duration_minutes ELSE NULL END) AS avg_duration_mins
            FROM users u
            LEFT JOIN maintenance_requests mr ON mr.technician_id = u.id 
                AND mr.date_reported >= DATE_FORMAT(NOW(), '%Y-%m-01 00:00:00')
            LEFT JOIN maintenance_logs ml ON ml.request_id = mr.id
            WHERE u.role = 'technician'
            GROUP BY u.id, u.name
            ORDER BY completed_count DESC, assigned_count DESC
        """
        self.cur.execute(sql)
        rows = self.cur.fetchall()
        self.assertIsInstance(rows, list)

    def test_problematic_devices_aggregation_query(self):
        """Checks problematic devices aggregation and failure frequency calculation."""
        sql = """
            SELECT 
                e.id AS equipment_id,
                e.name AS equipment_name,
                e.category,
                e.location,
                e.status AS current_status,
                COUNT(mr.id) AS failure_count,
                SUM(CASE WHEN mr.status = 'Resolved' THEN 1 ELSE 0 END) AS resolved_count,
                SUM(CASE WHEN mr.status != 'Resolved' THEN 1 ELSE 0 END) AS active_count,
                MAX(mr.date_reported) AS last_failure_date
            FROM equipment e
            JOIN maintenance_requests mr ON mr.equipment_id = e.id
            WHERE (e.is_deleted IS NULL OR e.is_deleted = 0)
            GROUP BY e.id, e.name, e.category, e.location, e.status
            HAVING failure_count >= 2
            ORDER BY failure_count DESC, last_failure_date DESC
        """
        self.cur.execute(sql)
        rows = self.cur.fetchall()
        self.assertIsInstance(rows, list)

    def test_maintenance_logs_soft_delete(self):
        """Verifies that soft-deleted maintenance logs remain in the database with is_deleted=1."""
        # 1. Fetch an existing equipment and request, or create minimal test entry
        self.cur.execute("SELECT id FROM equipment LIMIT 1")
        eq = self.cur.fetchone()
        self.cur.execute("SELECT id FROM maintenance_requests LIMIT 1")
        req = self.cur.fetchone()

        if eq and req:
            eq_id = eq["id"] if isinstance(eq, dict) else eq[0]
            req_id = req["id"] if isinstance(req, dict) else req[0]

            self.cur.execute(
                "INSERT INTO maintenance_logs (equipment_id, request_id, action_taken, date_completed, is_deleted) "
                "VALUES (%s, %s, 'Soft-delete test action', NOW(), 0)",
                (eq_id, req_id)
            )
            self.db.commit()
            log_id = self.cur.lastrowid

            # Verify initially is_deleted=0
            self.cur.execute("SELECT id, is_deleted, deleted_at FROM maintenance_logs WHERE id=%s", (log_id,))
            row = self.cur.fetchone()
            self.assertEqual(row["is_deleted"] if isinstance(row, dict) else row[1], 0)

            # Soft-delete the log record
            self.cur.execute(
                "UPDATE maintenance_logs SET is_deleted=1, deleted_at=NOW() WHERE id=%s",
                (log_id,)
            )
            self.db.commit()

            # Record MUST still exist in table
            self.cur.execute("SELECT id, is_deleted, deleted_at FROM maintenance_logs WHERE id=%s", (log_id,))
            del_row = self.cur.fetchone()
            self.assertIsNotNone(del_row, "Soft deleted log must still physically exist in the database table")
            self.assertEqual(del_row["is_deleted"] if isinstance(del_row, dict) else del_row[1], 1)
            self.assertIsNotNone(del_row["deleted_at"] if isinstance(del_row, dict) else del_row[2])

            # Active logbook query MUST NOT return it
            self.cur.execute(
                "SELECT id FROM maintenance_logs WHERE id=%s AND (is_deleted IS NULL OR is_deleted=0)",
                (log_id,)
            )
            self.assertIsNone(self.cur.fetchone(), "Active logbook queries must filter out soft-deleted logs")

            # Clean up test row
            self.cur.execute("DELETE FROM maintenance_logs WHERE id=%s", (log_id,))
            self.db.commit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
