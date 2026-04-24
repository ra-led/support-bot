import datetime as dt
import copy
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_TAXONOMY = [
    {
        "id": "electrical",
        "label": "Electrical",
        "impacted_services": [
            {
                "id": "electrical.lighting",
                "label": "Lighting",
                "request_types": [
                    {"id": "electrical.lighting.not_working", "label": "Light not working"},
                    {
                        "id": "electrical.lighting.cannot_on_off_dim",
                        "label": "Cannot turn on/off or dim",
                    },
                    {"id": "electrical.lighting.sensor_fault", "label": "Sensor fault"},
                    {
                        "id": "electrical.lighting.replace_fitting",
                        "label": "Replace fitting / globe",
                    },
                    {
                        "id": "electrical.lighting.flickering_intermittent",
                        "label": "Flickering / intermittent",
                    },
                ],
            },
            {
                "id": "electrical.power",
                "label": "Power / Outlets",
                "request_types": [
                    {"id": "electrical.power.outlet_not_working", "label": "Outlet not working"},
                    {"id": "electrical.power.power_outage", "label": "Power outage"},
                    {
                        "id": "electrical.power.tripping_breaker",
                        "label": "Breaker tripping / overload",
                    },
                    {"id": "electrical.power.other", "label": "Other power issue"},
                ],
            },
            {
                "id": "electrical.automatic_doors",
                "label": "Automatic / Roller Doors (Electrical)",
                "request_types": [
                    {
                        "id": "electrical.automatic_doors.roller_jammed",
                        "label": "Roller door jammed / not opening",
                    },
                    {
                        "id": "electrical.automatic_doors.sensor_fault",
                        "label": "Door sensor fault",
                    },
                    {
                        "id": "electrical.automatic_doors.control_fault",
                        "label": "Control / motor fault",
                    },
                ],
            },
        ],
    },
    {
        "id": "plumbing",
        "label": "Plumbing",
        "impacted_services": [
            {
                "id": "plumbing.toilets",
                "label": "Toilets",
                "request_types": [
                    {"id": "plumbing.toilets.blocked", "label": "Blocked"},
                    {"id": "plumbing.toilets.leak", "label": "Leak"},
                    {"id": "plumbing.toilets.flush_fault", "label": "Flush fault"},
                    {"id": "plumbing.toilets.running_water", "label": "Running water"},
                    {"id": "plumbing.toilets.other", "label": "Other toilet issue"},
                ],
            },
            {
                "id": "plumbing.sinks_taps",
                "label": "Sinks / Taps",
                "request_types": [
                    {"id": "plumbing.sinks_taps.leak", "label": "Leak"},
                    {"id": "plumbing.sinks_taps.drain_blocked", "label": "Drain blocked"},
                    {
                        "id": "plumbing.sinks_taps.no_water",
                        "label": "No water / low pressure",
                    },
                    {"id": "plumbing.sinks_taps.other", "label": "Other sink/tap issue"},
                ],
            },
            {
                "id": "plumbing.general_water",
                "label": "General Water",
                "request_types": [
                    {
                        "id": "plumbing.general_water.burst_pipe",
                        "label": "Burst pipe / major leak",
                    },
                    {
                        "id": "plumbing.general_water.water_smell",
                        "label": "Water smell / quality concern",
                    },
                    {"id": "plumbing.general_water.other", "label": "Other water issue"},
                ],
            },
        ],
    },
    {
        "id": "hvac",
        "label": "Heating & Cooling (HVAC)",
        "impacted_services": [
            {
                "id": "hvac.air_conditioning",
                "label": "Air Conditioning",
                "request_types": [
                    {"id": "hvac.air_conditioning.not_working", "label": "Not working"},
                    {"id": "hvac.air_conditioning.too_hot", "label": "Too hot"},
                    {"id": "hvac.air_conditioning.too_cold", "label": "Too cold"},
                    {
                        "id": "hvac.air_conditioning.noisy",
                        "label": "Noisy / unusual sound",
                    },
                    {"id": "hvac.air_conditioning.other", "label": "Other AC issue"},
                ],
            },
            {
                "id": "hvac.ventilation",
                "label": "Ventilation / Air Quality",
                "request_types": [
                    {"id": "hvac.ventilation.stuffy", "label": "Stuffy / poor ventilation"},
                    {"id": "hvac.ventilation.odor", "label": "Odor"},
                    {"id": "hvac.ventilation.other", "label": "Other ventilation issue"},
                ],
            },
        ],
    },
    {
        "id": "access_security",
        "label": "Access & Security",
        "impacted_services": [
            {
                "id": "access_security.access_cards",
                "label": "Access Cards / Permissions",
                "request_types": [
                    {
                        "id": "access_security.access_cards.no_access",
                        "label": "Card not granting access",
                    },
                    {
                        "id": "access_security.access_cards.new_user_setup",
                        "label": "New user setup / permissions",
                    },
                    {
                        "id": "access_security.access_cards.card_fault",
                        "label": "Card fault / replacement",
                    },
                    {"id": "access_security.access_cards.other", "label": "Other access card issue"},
                ],
            },
            {
                "id": "access_security.keys_locks",
                "label": "Keys / Locks",
                "request_types": [
                    {"id": "access_security.keys_locks.need_key", "label": "Need key / duplicate key"},
                    {
                        "id": "access_security.keys_locks.lock_loose",
                        "label": "Lock loose / screws tighten",
                    },
                    {
                        "id": "access_security.keys_locks.lock_not_working",
                        "label": "Lock not working",
                    },
                    {"id": "access_security.keys_locks.other", "label": "Other key/lock issue"},
                ],
            },
            {
                "id": "access_security.doors",
                "label": "Doors (Access)",
                "request_types": [
                    {
                        "id": "access_security.doors.jammed",
                        "label": "Door jammed / cannot open/close",
                    },
                    {
                        "id": "access_security.doors.lockout_lockin",
                        "label": "People locked in/out",
                    },
                    {"id": "access_security.doors.other", "label": "Other door access issue"},
                ],
            },
        ],
    },
    {
        "id": "carpentry_interiors",
        "label": "Carpentry & Interiors (Fixtures/Furniture)",
        "impacted_services": [
            {
                "id": "carpentry_interiors.furniture_storage",
                "label": "Furniture / Storage",
                "request_types": [
                    {"id": "carpentry_interiors.furniture_storage.move", "label": "Move / relocate"},
                    {
                        "id": "carpentry_interiors.furniture_storage.remove",
                        "label": "Remove / dispose",
                    },
                    {
                        "id": "carpentry_interiors.furniture_storage.install",
                        "label": "Install / assemble",
                    },
                    {
                        "id": "carpentry_interiors.furniture_storage.other",
                        "label": "Other furniture/storage task",
                    },
                ],
            },
            {
                "id": "carpentry_interiors.wall_fixtures",
                "label": "Wall Fixtures / Mounting",
                "request_types": [
                    {
                        "id": "carpentry_interiors.wall_fixtures.picture_hanging",
                        "label": "Picture hanging / straighten",
                    },
                    {
                        "id": "carpentry_interiors.wall_fixtures.install_hooks",
                        "label": "Install hooks / anchors",
                    },
                    {
                        "id": "carpentry_interiors.wall_fixtures.repair_mounting",
                        "label": "Repair mounting / reattach",
                    },
                    {
                        "id": "carpentry_interiors.wall_fixtures.other",
                        "label": "Other wall fixture task",
                    },
                ],
            },
            {
                "id": "carpentry_interiors.bathroom_accessories",
                "label": "Bathroom Accessories",
                "request_types": [
                    {
                        "id": "carpentry_interiors.bathroom_accessories.dispenser_loose",
                        "label": "Dispenser loose / reattach",
                    },
                    {
                        "id": "carpentry_interiors.bathroom_accessories.other",
                        "label": "Other bathroom accessory issue",
                    },
                ],
            },
        ],
    },
    {
        "id": "cleaning_waste",
        "label": "Cleaning & Waste",
        "impacted_services": [
            {
                "id": "cleaning_waste.cleaning",
                "label": "Cleaning",
                "request_types": [
                    {"id": "cleaning_waste.cleaning.spill", "label": "Spill / cleanup needed"},
                    {"id": "cleaning_waste.cleaning.hygiene", "label": "Hygiene issue"},
                    {"id": "cleaning_waste.cleaning.other", "label": "Other cleaning request"},
                ],
            },
            {
                "id": "cleaning_waste.waste",
                "label": "Waste / Disposal",
                "request_types": [
                    {
                        "id": "cleaning_waste.waste.remove_items",
                        "label": "Remove items to waste",
                    },
                    {
                        "id": "cleaning_waste.waste.other",
                        "label": "Other waste/disposal request",
                    },
                ],
            },
        ],
    },
    {
        "id": "safety_emergency",
        "label": "Safety / Emergency",
        "impacted_services": [
            {
                "id": "safety_emergency.immediate_hazard",
                "label": "Immediate Hazard",
                "request_types": [
                    {
                        "id": "safety_emergency.immediate_hazard.people_trapped",
                        "label": "People trapped / lock-in",
                    },
                    {
                        "id": "safety_emergency.immediate_hazard.unsafe_area",
                        "label": "Unsafe area / hazard",
                    },
                    {
                        "id": "safety_emergency.immediate_hazard.other",
                        "label": "Other emergency",
                    },
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

TAXONOMY_FILE_PATH = Path(__file__).with_name("taxonomy.json")


class Storage:
    def __init__(self, db_path: str = "data.db") -> None:
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
        self.taxonomy = self._load_taxonomy_from_file()
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
                dialog_state_json TEXT,
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
        self._ensure_column("requests", "dialog_state_json", "TEXT")

    def _ensure_column(self, table_name: str, column_name: str, column_sql: str) -> None:
        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        existing_columns = {column["name"] for column in columns}
        if column_name in existing_columns:
            return
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")
        self.conn.commit()

    def _json_dump(self, value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    def _json_load(self, value: Optional[str]) -> Any:
        if value is None:
            return None
        return json.loads(value)

    def _validate_taxonomy(self, taxonomy: Any) -> List[Dict[str, Any]]:
        try:
            serialized = json.dumps(taxonomy, ensure_ascii=False)
            parsed = json.loads(serialized)
        except (TypeError, ValueError) as error:
            raise ValueError(f"Taxonomy must be valid JSON: {error}") from error

        if not isinstance(parsed, list):
            raise ValueError("Taxonomy JSON must be an array of facility areas.")
        return parsed

    def _load_taxonomy_from_file(self) -> List[Dict[str, Any]]:
        if not TAXONOMY_FILE_PATH.exists():
            default_taxonomy = self._validate_taxonomy(DEFAULT_TAXONOMY)
            TAXONOMY_FILE_PATH.write_text(
                json.dumps(default_taxonomy, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return default_taxonomy

        raw = TAXONOMY_FILE_PATH.read_text(encoding="utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Taxonomy file {TAXONOMY_FILE_PATH} contains invalid JSON: {error}"
            ) from error
        return self._validate_taxonomy(parsed)

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
                clarifying_questions_json, confidence_json, dialog_state_json, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                self._json_dump(record.get("dialog_state", {})),
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
                dialog_state_json = ?,
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
                self._json_dump(merged.get("dialog_state", {})),
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
            "dialog_state": self._json_load(row["dialog_state_json"]) or {},
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
        return copy.deepcopy(self.taxonomy)

    def save_taxonomy(self, taxonomy: Any) -> None:
        normalized = self._validate_taxonomy(taxonomy)
        tmp_path = TAXONOMY_FILE_PATH.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(TAXONOMY_FILE_PATH)
        self.taxonomy = normalized

    def get_analytics_schema(self, tenant_id: str) -> List[Dict[str, Any]]:
        return self.analytics_schema.get(tenant_id, DEFAULT_ANALYTICS_SCHEMA)

    def save_analytics_schema(self, tenant_id: str, schema: List[Dict[str, Any]]) -> None:
        self.analytics_schema[tenant_id] = schema


storage = Storage()
