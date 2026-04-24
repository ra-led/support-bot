from typing import Any, Dict, List, Optional

def clean_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"unknown", "n/a", "na", "none", "null"}:
            return None
        return cleaned
    return str(value)
def apply_answers_to_request(request: Dict[str, Any], answers: Dict[str, Any]) -> Dict[str, Any]:
    if not answers:
        return request

    updated = dict(request)
    location = dict(updated.get("location") or {})
    taxonomy = dict(updated.get("taxonomy") or {})

    for raw_key, value in answers.items():
        key = str(raw_key)
        cleaned = clean_value(value)
        if cleaned is None:
            continue
        if key.startswith("location."):
            location[key.split(".", 1)[1]] = cleaned
            continue
        if key.startswith("taxonomy."):
            taxonomy[key.split(".", 1)[1]] = cleaned
            continue
        updated[key] = cleaned

    updated["location"] = location
    updated["taxonomy"] = taxonomy
    return updated


def join_text(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, list):
        return "; ".join(str(value) for value in values)
    return str(values)


def format_assets(assets: Any) -> str:
    if not isinstance(assets, list):
        return ""
    chunks: List[str] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        parts = []
        if asset.get("type"):
            parts.append(str(asset["type"]))
        if asset.get("identifier"):
            parts.append(f"id={asset['identifier']}")
        if asset.get("notes"):
            parts.append(f"notes={asset['notes']}")
        if parts:
            chunks.append(", ".join(parts))
    return "; ".join(chunks)


def flatten_request_for_export(request: Dict[str, Any]) -> Dict[str, Any]:
    location = request.get("location") if isinstance(request.get("location"), dict) else {}
    taxonomy = request.get("taxonomy") if isinstance(request.get("taxonomy"), dict) else {}
    confidence = request.get("confidence") if isinstance(request.get("confidence"), dict) else {}
    return {
        "request_id": request.get("request_id"),
        "created_at": request.get("created_at"),
        "updated_at": request.get("updated_at"),
        "tenant_id": request.get("tenant_id"),
        "branch_id": request.get("branch_id"),
        "source_message_id": request.get("source_message_id"),
        "reporter_email": request.get("reporter_email"),
        "title": request.get("title"),
        "description": request.get("description"),
        "urgency": request.get("urgency"),
        "status": request.get("status"),
        "safety_or_access_impact": request.get("safety_or_access_impact"),
        "location_site": location.get("site"),
        "location_building": location.get("building"),
        "location_floor": location.get("floor"),
        "location_room": location.get("room"),
        "location_free_text": location.get("free_text"),
        "taxonomy_facilities_area": taxonomy.get("facilities_area"),
        "taxonomy_impacted_service": taxonomy.get("impacted_service"),
        "taxonomy_request_type": taxonomy.get("request_type"),
        "missing_required_fields": join_text(request.get("missing_required_fields")),
        "clarifying_questions": join_text(request.get("clarifying_questions")),
        "assets": format_assets(request.get("assets")),
        "confidence_overall": confidence.get("overall"),
        "confidence_urgency": confidence.get("urgency"),
        "confidence_location": confidence.get("location"),
        "confidence_taxonomy": confidence.get("taxonomy"),
    }
