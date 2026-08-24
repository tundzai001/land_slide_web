import unittest
from types import SimpleNamespace

from app.routers.incidents import _canonical_filter_hash, _decode_cursor, _sign_cursor
from app.services.incident_cases import (
    _event_payload,
    can_view_case,
    incident_reference,
    normalize_severity,
    priority_for_severity,
    serialize_case,
)


class IncidentDomainContractTests(unittest.TestCase):
    def test_severity_priority_and_reference_are_deterministic(self):
        self.assertEqual(normalize_severity("critical"), "CRITICAL")
        self.assertEqual(priority_for_severity("warning"), "HIGH")
        self.assertEqual(priority_for_severity("bad-value"), "UNTRIAGED")
        self.assertEqual(incident_reference("SENSOR_ALERT", 42, 1704067200), "INC-20240101-A42")

    def test_event_payload_is_allowlisted_and_case_serialization_hides_username(self):
        payload = _event_payload({"status": "resolved", "phone": "+84", "message": "secret", "project_id": 7})
        self.assertEqual(payload, {"status": "resolved", "project_id": 7})
        case = SimpleNamespace(
            id=1, reference="INC-20240101-A1", source_kind="SENSOR_ALERT", source_id=1,
            project_id=7, station_id=9, scope_state="SCOPED", project_name_snapshot="P",
            project_code_snapshot="P1", station_name_snapshot="S", station_code_snapshot="S1",
            title="Alert", summary="No PII", source_severity="WARNING", signal_state="ACTIVE",
            priority="HIGH", status="new", assigned_to_user_id=2, assigned_to_username="secret-user",
            opened_at=1, last_signal_at=2, acknowledged_at=None, resolved_at=None, updated_at=2,
            version=1, revision=1, last_event_sequence=1,
        )
        public = serialize_case(case)
        self.assertNotIn("assigned_to_username", public)
        self.assertEqual(serialize_case(case, include_private=True)["assigned_to_username"], "secret-user")

    def test_scope_gate_and_signed_cursor_reject_tampering(self):
        case = SimpleNamespace(project_id=7)
        self.assertTrue(can_view_case(SimpleNamespace(role="admin", assigned_projects=[]), case))
        self.assertTrue(can_view_case(SimpleNamespace(role="operator", assigned_projects=[7]), case))
        self.assertFalse(can_view_case(SimpleNamespace(role="viewer", assigned_projects=[8]), case))
        filter_hash = _canonical_filter_hash({"status": "new"})
        cursor = _sign_cursor({"v": 1, "scope_hash": "scope", "filter_hash": filter_hash, "sort": "-updated_at", "value": 10, "id": 2})
        self.assertEqual(_decode_cursor(cursor, scope_hash="scope", filter_hash=filter_hash, sort="-updated_at")["id"], 2)
        with self.assertRaises(Exception):
            _decode_cursor(cursor[:-1] + ("A" if cursor[-1] != "A" else "B"), scope_hash="scope", filter_hash=filter_hash, sort="-updated_at")


if __name__ == "__main__":
    unittest.main()
