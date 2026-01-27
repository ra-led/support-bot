import datetime as dt
import uuid
from dataclasses import dataclass, field
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


@dataclass
class Storage:
    messages: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    requests: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    taxonomy: List[Dict[str, Any]] = field(default_factory=lambda: DEFAULT_TAXONOMY)
    analytics_schema: Dict[str, List[Dict[str, Any]]] = field(
        default_factory=lambda: {"default": DEFAULT_ANALYTICS_SCHEMA}
    )

    def save_message(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        message_id = payload["message_id"]
        if message_id in self.messages:
            return self.messages[message_id]

        saved = {
            **payload,
            "created_at": dt.datetime.utcnow().isoformat(),
        }
        self.messages[message_id] = saved
        return saved

    def create_request(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        request_id = str(uuid.uuid4())
        now = dt.datetime.utcnow().isoformat()
        record = {
            **payload,
            "request_id": request_id,
            "created_at": now,
            "updated_at": now,
        }
        self.requests[request_id] = record
        return record

    def update_request(self, request_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        existing = self.requests[request_id]
        merged = {
            **existing,
            **updates,
            "updated_at": dt.datetime.utcnow().isoformat(),
        }
        self.requests[request_id] = merged
        return merged

    def get_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        return self.requests.get(request_id)

    def list_requests(self) -> List[Dict[str, Any]]:
        return list(self.requests.values())

    def get_taxonomy(self) -> List[Dict[str, Any]]:
        return self.taxonomy

    def get_analytics_schema(self, tenant_id: str) -> List[Dict[str, Any]]:
        return self.analytics_schema.get(tenant_id, DEFAULT_ANALYTICS_SCHEMA)

    def save_analytics_schema(self, tenant_id: str, schema: List[Dict[str, Any]]) -> None:
        self.analytics_schema[tenant_id] = schema


storage = Storage()
