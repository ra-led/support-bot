import datetime as dt
import json
import sqlite3
import uuid
from typing import Any, Dict, List, Optional


DEFAULT_TAXONOMY = [
    {
        "id": "A1",
        "label": "Plumbing",
        "impacted_services": [
            {
                "id": "S1",
                "label": "Blockages",
                "request_types": [
                    {"id": "R1", "label": "Toilet"},
                    {"id": "R2", "label": "Sink"},
                ],
            },
            {
                "id": "S2",
                "label": "Leaks",
                "request_types": [
                    {"id": "R3", "label": "Pipe"},
                    {"id": "R4", "label": "Faucet"},
                ],
            },
        ],
    },
    {
        "id": "A2",
        "label": "Electrical",
        "impacted_services": [
            {
                "id": "S3",
                "label": "Lighting",
                "request_types": [
                    {"id": "R5", "label": "Not working"},
                    {"id": "R6", "label": "Cannot switch"},
                ],
            }
        ],
    },
    {
        "id": "A3",
        "label": "Building Access",
        "impacted_services": [
            {
                "id": "S4",
                "label": "Doors",
                "request_types": [
                    {"id": "R7", "label": "Roller door"},
                    {"id": "R8", "label": "Access card"},
                ],
            }
        ],
    },
]

DEFAULT_ANALYTICS_SCHEMA = [
    {"key": "safety_impact", "label": "Safety/Access impact", "type": "boolean"},
    {
        "key": "urgency_class",
        "label": "Urgency class",
        "type": "enum",
        "values": ["low", "normal", "high", "urgent"],
    },
]


class Storage:
    def __init__(self, db_path: str = "data.db") -> None:
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self.taxonomy = DEFAULT_TAXONOMY
        self.analytics_schema: Dict[str, List[Dict[str, Any]]] = {
            "default": DEFAULT_ANALYTICS_SCHEMA
        }

    def _init_db(self) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS intake_messages (
                message_id TEXT PRIMARY KEY,
                payload_json TEXT,
                extraction_json TEXT,
                created_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS requests (
                request_id TEXT PRIMARY KEY,
                tenant_id TEXT,
                branch_id TEXT,
                source_message_id TEXT,
                reporter_email TEXT,
                title TEXT,
                description TEXT,
                urgency TEXT,
                location_json TEXT,
                taxonomy_json TEXT,
                safety_or_access_impact TEXT,
                assets_json TEXT,
                missing_required_fields_json TEXT,
                clarifying_questions_json TEXT,
                confidence_json TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT,
                sender TEXT,
                content TEXT,
                created_at TEXT
            )
            """
        )
        self.conn.commit()

    def _json_dump(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _json_load(self, value: Optional[str]) -> Any:
        if value is None:
            return None
        return json.loads(value)

    def save_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message_id = payload["message_id"]
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT payload_json, extraction_json FROM intake_messages WHERE message_id = ?",
            (message_id,),
        )
        row = cursor.fetchone()
        if row:
            saved_payload = self._json_load(row["payload_json"]) or {}
            extraction = self._json_load(row["extraction_json"])
            result = {**saved_payload}
            if extraction is not None:
                result["extraction"] = extraction
            return result

        created_at = dt.datetime.utcnow().isoformat()
        cursor.execute(
            "INSERT INTO intake_messages (message_id, payload_json, extraction_json, created_at) VALUES (?, ?, ?, ?)",
            (message_id, self._json_dump(payload), None, created_at),
        )
        self.conn.commit()
        return payload

    def update_message_extraction(self, message_id: str, extraction: List[Dict[str, Any]]) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "UPDATE intake_messages SET extraction_json = ? WHERE message_id = ?",
            (self._json_dump(extraction), message_id),
        )
        self.conn.commit()

    def create_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request_id = str(uuid.uuid4())
        now = dt.datetime.utcnow().isoformat()
        record = {
            **payload,
            "request_id": request_id,
            "created_at": now,
            "updated_at": now,
        }
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO requests (
                request_id, tenant_id, branch_id, source_message_id, reporter_email,
                title, description, urgency, location_json, taxonomy_json,
                safety_or_access_impact, assets_json, missing_required_fields_json,
                clarifying_questions_json, confidence_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["request_id"],
                record.get("tenant_id"),
                record.get("branch_id"),
                record.get("source_message_id"),
                record.get("reporter_email"),
                record.get("title"),
                record.get("description"),
                record.get("urgency"),
                self._json_dump(record.get("location")),
                self._json_dump(record.get("taxonomy")),
                self._json_dump(record.get("safety_or_access_impact")),
                self._json_dump(record.get("assets", [])),
                self._json_dump(record.get("missing_required_fields", [])),
                self._json_dump(record.get("clarifying_questions", [])),
                self._json_dump(record.get("confidence", {})),
                record.get("status"),
                record["created_at"],
                record["updated_at"],
            ),
        )
        self.conn.commit()
        return record

    def update_request(self, request_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.get_request(request_id)
        if not existing:
            raise KeyError("Request not found")
        merged = {
            **existing,
            **updates,
            "updated_at": dt.datetime.utcnow().isoformat(),
        }
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE requests SET
                tenant_id = ?,
                branch_id = ?,
                source_message_id = ?,
                reporter_email = ?,
                title = ?,
                description = ?,
                urgency = ?,
                location_json = ?,
                taxonomy_json = ?,
                safety_or_access_impact = ?,
                assets_json = ?,
                missing_required_fields_json = ?,
                clarifying_questions_json = ?,
                confidence_json = ?,
                status = ?,
                updated_at = ?
            WHERE request_id = ?
            """,
            (
                merged.get("tenant_id"),
                merged.get("branch_id"),
                merged.get("source_message_id"),
                merged.get("reporter_email"),
                merged.get("title"),
                merged.get("description"),
                merged.get("urgency"),
                self._json_dump(merged.get("location")),
                self._json_dump(merged.get("taxonomy")),
                self._json_dump(merged.get("safety_or_access_impact")),
                self._json_dump(merged.get("assets", [])),
                self._json_dump(merged.get("missing_required_fields", [])),
                self._json_dump(merged.get("clarifying_questions", [])),
                self._json_dump(merged.get("confidence", {})),
                merged.get("status"),
                merged.get("updated_at"),
                request_id,
            ),
        )
        self.conn.commit()
        return merged

    def _row_to_request(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "request_id": row["request_id"],
            "tenant_id": row["tenant_id"],
            "branch_id": row["branch_id"],
            "source_message_id": row["source_message_id"],
            "reporter_email": row["reporter_email"],
            "title": row["title"],
            "description": row["description"],
            "urgency": row["urgency"],
            "location": self._json_load(row["location_json"]),
            "taxonomy": self._json_load(row["taxonomy_json"]),
            "safety_or_access_impact": self._json_load(row["safety_or_access_impact"]),
            "assets": self._json_load(row["assets_json"]) or [],
            "missing_required_fields": self._json_load(row["missing_required_fields_json"]) or [],
            "clarifying_questions": self._json_load(row["clarifying_questions_json"]) or [],
            "confidence": self._json_load(row["confidence_json"]) or {},
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM requests WHERE request_id = ?", (request_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_request(row)

    def list_requests(self, reporter_email: Optional[str] = None) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        if reporter_email:
            cursor.execute(
                "SELECT * FROM requests WHERE reporter_email = ? ORDER BY created_at DESC",
                (reporter_email,),
            )
        else:
            cursor.execute("SELECT * FROM requests ORDER BY created_at DESC")
        rows = cursor.fetchall()
        return [self._row_to_request(row) for row in rows]

    def add_message(self, request_id: str, sender: str, content: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT INTO conversation_messages (request_id, sender, content, created_at) VALUES (?, ?, ?, ?)",
            (request_id, sender, content, dt.datetime.utcnow().isoformat()),
        )
        self.conn.commit()

    def list_messages(self, request_id: str) -> List[Dict[str, Any]]:
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT sender, content, created_at FROM conversation_messages WHERE request_id = ? ORDER BY id ASC",
            (request_id,),
        )
        rows = cursor.fetchall()
        return [
            {
                "sender": row["sender"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def get_taxonomy(self) -> List[Dict[str, Any]]:
        return self.taxonomy

    def get_analytics_schema(self, tenant_id: str) -> List[Dict[str, Any]]:
        return self.analytics_schema.get(tenant_id, DEFAULT_ANALYTICS_SCHEMA)

    def save_analytics_schema(self, tenant_id: str, schema: List[Dict[str, Any]]) -> None:
        self.analytics_schema[tenant_id] = schema


storage = Storage()
