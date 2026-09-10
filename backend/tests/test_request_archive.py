import io
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

# Importing storage creates its singleton; tests must never open the application's database.
with patch.dict(os.environ, {"DATA_DB_PATH": ":memory:"}):
    from app import api_router, auth
    from app.storage import Storage


def tearDownModule():
    api_router.storage.conn.close()


def request_payload(index=0):
    return {
        "tenant_id": "default",
        "branch_id": "main",
        "reporter_email": "test@example.com",
        "title": f"Request {index}",
        "description": f"Original description {index}",
        "urgency": "high",
        "location": {"building": "North", "room": "101"},
        "taxonomy": {"request_type": "electrical.lighting.not_working"},
        "safety_or_access_impact": False,
        "assets": [{"id": "asset-1"}],
        "missing_required_fields": ["floor"],
        "clarifying_questions": ["Which floor?"],
        "confidence": {"location": 0.7},
        "dialog_state": {"thread_id": "existing-thread", "problem": {"text": "Light is not working"}},
        "status": "needs_clarification",
    }


class RequestArchiveTests(unittest.TestCase):
    def setUp(self):
        self.store = Storage(":memory:")
        self.addCleanup(self.store.conn.close)
        self.storage_patch = patch.object(api_router, "storage", self.store)
        self.storage_patch.start()
        self.addCleanup(self.storage_patch.stop)
        self.password_patch = patch.object(auth, "ADMIN_PASSWORD", "test-admin")
        self.password_patch.start()
        self.addCleanup(self.password_patch.stop)
        app = FastAPI()
        app.include_router(api_router.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.headers = {"X-Admin-Password": "test-admin"}

    def archive(self, request_id, archived=True):
        return self.client.put(
            f"/v1/admin/requests/{request_id}/archive",
            json={"archived": archived}, headers=self.headers,
        )

    def test_archive_restore_preserves_every_field_and_history(self):
        request_id = self.store.create_request(request_payload())["request_id"]
        self.store.add_message(request_id, "user", "Original message")
        self.store.add_llm_trace(request_id, "test-model", "schema", "prompt", "response")
        original = self.store.get_request(request_id)
        messages = self.store.list_messages(request_id)
        traces = self.store.list_llm_traces(request_id)

        response = self.archive(request_id)
        self.assertEqual(response.status_code, 200)
        archived = response.json()
        self.assertTrue(archived["archived_at"])
        self.assertEqual({**archived, "archived_at": None}, original)
        self.assertEqual(self.archive(request_id).json(), archived)
        self.assertEqual(self.store.list_messages(request_id), messages)
        self.assertEqual(self.store.list_llm_traces(request_id), traces)
        self.assertEqual(self.archive(request_id, False).json(), original)
        self.assertEqual(self.archive(request_id, False).json(), original)
        self.assertEqual(self.store.list_messages(request_id), messages)
        self.assertEqual(self.store.list_llm_traces(request_id), traces)

    def test_both_tabs_have_twenty_per_page_and_stable_order(self):
        ids = [self.store.create_request(request_payload(i))["request_id"] for i in range(45)]
        self.store.conn.execute("UPDATE requests SET created_at = '2026-05-01T00:00:00'")
        self.store.conn.commit()
        for request_id in ids[:22]:
            self.store.set_request_archived(request_id, True)

        for archived, expected_ids, lengths in [(False, ids[22:], [20, 3]), (True, ids[:22], [20, 2])]:
            found = []
            for page, length in enumerate(lengths, start=1):
                response = self.client.get("/v1/admin/requests", params={"page": page, "archived": archived}, headers=self.headers)
                self.assertEqual(response.status_code, 200)
                data = response.json()
                self.assertEqual(data["page_size"], 20)
                self.assertEqual(data["total"], len(expected_ids))
                self.assertEqual(len(data["requests"]), length)
                self.assertEqual(set(data["dialog_ids"]), set(ids))
                self.assertEqual(set(data["active_dialog_ids"]), set(ids[22:]))
                self.assertEqual(data["stats"]["active_requests"], 23)
                self.assertEqual(data["stats"]["archived_requests"], 22)
                found.extend(item["request_id"] for item in data["requests"])
            self.assertEqual(found, sorted(expected_ids, reverse=True))

    def test_empty_and_out_of_range_pages_are_clamped(self):
        self.assertEqual(self.store.list_admin_requests(page=10)["page"], 1)
        for i in range(21):
            self.store.create_request(request_payload(i))
        last = self.store.list_admin_requests(page=999)
        self.assertEqual(last["page"], 2)
        self.archive(last["requests"][0]["request_id"])
        page = self.store.list_admin_requests(page=2)
        self.assertEqual(page["page"], 1)
        self.assertEqual(len(page["requests"]), 20)
        archived_id = self.store.list_admin_requests(archived=True)["requests"][0]["request_id"]
        self.archive(archived_id, False)
        empty = self.store.list_admin_requests(archived=True)
        self.assertEqual((empty["total"], empty["page"], empty["requests"]), (0, 1, []))

    def test_admin_auth_and_input_validation(self):
        request_id = self.store.create_request(request_payload())["request_id"]
        path = f"/v1/admin/requests/{request_id}/archive"
        for headers in [{}, {"X-Admin-Password": "wrong"}]:
            self.assertEqual(self.client.get("/v1/admin/requests", headers=headers).status_code, 401)
            self.assertEqual(self.client.put(path, json={"archived": True}, headers=headers).status_code, 401)
        for payload in [{}, {"archived": None}, {"archived": "false"}]:
            self.assertEqual(self.client.put(path, json=payload, headers=self.headers).status_code, 422)
        for page in [0, -1, "abc"]:
            self.assertEqual(self.client.get("/v1/admin/requests", params={"page": page}, headers=self.headers).status_code, 422)
        self.assertEqual(self.archive("missing").status_code, 404)
        self.assertIsNone(self.store.get_request(request_id)["archived_at"])

    def test_archived_requests_are_not_reused_or_auto_processed(self):
        request_id = self.store.create_request(request_payload())["request_id"]
        self.archive(request_id)
        self.assertFalse(api_router._is_request_active(self.store.get_request(request_id)))
        self.assertEqual(self.store.list_stale_requests(["needs_clarification"], "9999"), [])
        payload = api_router.IntakeRequest(
            message_id="next-message", thread_id="existing-thread", tenant_id="default",
            branch_id="main", reporter_email="test@example.com", message_text="Another issue",
        )
        new_request = api_router._find_or_create_active_request(payload)
        self.assertNotEqual(new_request["request_id"], request_id)
        self.archive(request_id, False)
        self.assertTrue(api_router._is_request_active(self.store.get_request(request_id)))
        self.assertIn(request_id, [item["request_id"] for item in self.store.list_stale_requests(["needs_clarification"], "9999")])

    def test_archived_requests_allow_admin_edits_but_not_chat_writes(self):
        request_id = self.store.create_request(request_payload())["request_id"]
        original = self.archive(request_id).json()
        for endpoint, payload in [("clarify", {"additional_text": "New text"}), ("submit", {})]:
            response = self.client.post(f"/v1/requests/{request_id}/{endpoint}", json=payload)
            self.assertEqual(response.status_code, 409)
        self.assertEqual(self.store.list_messages(request_id), [])
        self.assertEqual(self.store.get_request(request_id), original)
        response = self.client.put(f"/v1/admin/requests/{request_id}", json={"title": "Corrected title"}, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["archived_at"], original["archived_at"])
        self.assertEqual(self.store.get_request(request_id)["title"], "Corrected title")

    def test_stats_export_and_reporter_history_still_include_archive(self):
        for i in range(2):
            request_id = self.store.create_request(request_payload(i))["request_id"]
        self.store.add_message(request_id, "user", "Preserved message")
        self.archive(request_id)
        stats = self.client.get("/v1/admin/stats", headers=self.headers).json()
        self.assertEqual(stats, {"total_requests": 2, "active_requests": 1, "archived_requests": 1, "by_status": {"needs_clarification": 2}})
        response = self.client.get("/v1/requests", params={"reporter_email": "test@example.com"})
        self.assertEqual(len(response.json()["requests"]), 2)
        messages = self.client.get(f"/v1/requests/{request_id}/messages", headers=self.headers).json()
        self.assertEqual(messages["messages"][0]["content"], "Preserved message")
        export = self.client.get("/v1/admin/export/issues.xlsx", headers=self.headers)
        self.assertEqual(export.status_code, 200)
        workbook = load_workbook(io.BytesIO(export.content))
        values = list(workbook.active.values)
        self.assertIn("Request 0", str(values))
        self.assertIn("Request 1", str(values))
        workbook.close()


class ArchiveMigrationTests(unittest.TestCase):
    def test_existing_database_survives_migration_and_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / "legacy.db")
            conn = sqlite3.connect(path)
            conn.executescript("""
                CREATE TABLE requests (
                    request_id TEXT PRIMARY KEY, tenant_id TEXT, branch_id TEXT,
                    source_message_id TEXT, reporter_email TEXT, title TEXT, description TEXT,
                    urgency TEXT, location_json TEXT, taxonomy_json TEXT, safety_or_access_impact TEXT,
                    assets_json TEXT, missing_required_fields_json TEXT, clarifying_questions_json TEXT,
                    confidence_json TEXT, dialog_state_json TEXT, status TEXT, created_at TEXT, updated_at TEXT
                );
                INSERT INTO requests VALUES (
                    'legacy-id', 'default', 'main', 'source-id', 'test@example.com', 'Existing issue',
                    'Original description', 'high', '{"room":"101"}', '{"request_type":"old.type"}',
                    'false', '["asset"]', '["floor"]', '["Which floor?"]', '{"location":0.7}',
                    '{"thread_id":"old-thread"}', 'ready', '2026-01-01T00:00:00', '2026-01-02T00:00:00'
                );
                CREATE TABLE conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, sender TEXT, content TEXT, created_at TEXT
                );
                INSERT INTO conversation_messages VALUES (1, 'legacy-id', 'user', 'Keep this message', '2026-01-01T00:00:00');
                CREATE TABLE llm_traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT, model TEXT, schema_name TEXT,
                    prompt TEXT, response_text TEXT, created_at TEXT
                );
                INSERT INTO llm_traces VALUES (1, 'legacy-id', 'model', 'schema', 'prompt', 'response', '2026-01-01');
                CREATE TABLE intake_messages (message_id TEXT PRIMARY KEY, payload_json TEXT, extraction_json TEXT, created_at TEXT);
                INSERT INTO intake_messages VALUES ('source-id', '{"message":"keep"}', '[{"request_id":"legacy-id"}]', '2026-01-01');
                CREATE TABLE taxonomy_versions (version INTEGER PRIMARY KEY, facilities_areas_json TEXT NOT NULL, created_at TEXT NOT NULL);
                INSERT INTO taxonomy_versions VALUES (7, '[]', '2026-01-01');
            """)
            tables = ["requests", "conversation_messages", "llm_traces", "intake_messages", "taxonomy_versions"]
            before = {table: conn.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
            conn.close()

            for restart in range(3):
                store = Storage(path)
                try:
                    for table in tables:
                        rows = store.conn.execute(f"SELECT * FROM {table}").fetchall()
                        values = [tuple(row)[:-1] if table == "requests" else tuple(row) for row in rows]
                        self.assertEqual(values, before[table])
                    record = store.get_request("legacy-id")
                    if restart == 0:
                        self.assertIsNone(record["archived_at"])
                        self.assertEqual(store.list_admin_requests()["total"], 1)
                        store.set_request_archived("legacy-id", True)
                    elif restart == 1:
                        self.assertTrue(record["archived_at"])
                        self.assertEqual(store.list_admin_requests(archived=True)["total"], 1)
                        store.set_request_archived("legacy-id", False)
                    else:
                        self.assertIsNone(record["archived_at"])
                        self.assertEqual(store.list_admin_requests()["total"], 1)
                    self.assertEqual(store.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                finally:
                    store.conn.close()


if __name__ == "__main__":
    unittest.main()
