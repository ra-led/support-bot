import io
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from pydantic import BaseModel, Field

from .llm import llm_client
from .storage import storage

REQUIRED_TAXONOMY_FIELDS = ("facilities_area", "impacted_service")
LOCATION_DETAIL_FIELDS = ("building", "floor", "room", "free_text")
MAX_AUDIO_BYTES = 25 * 1024 * 1024
EXPORT_COLUMNS = [
    "request_id",
    "created_at",
    "updated_at",
    "tenant_id",
    "branch_id",
    "source_message_id",
    "reporter_email",
    "title",
    "description",
    "urgency",
    "status",
    "safety_or_access_impact",
    "location_site",
    "location_building",
    "location_floor",
    "location_room",
    "location_free_text",
    "taxonomy_facilities_area",
    "taxonomy_impacted_service",
    "taxonomy_request_type",
    "missing_required_fields",
    "clarifying_questions",
    "assets",
    "confidence_overall",
    "confidence_urgency",
    "confidence_location",
    "confidence_taxonomy",
]


def _clean_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned or cleaned.lower() in {"unknown", "n/a", "na", "none", "null"}:
            return None
        return cleaned
    return str(value)


def _normalize_request_item(item: Dict[str, Any], branch_id: str) -> Dict[str, Any]:
    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    taxonomy = item.get("taxonomy") if isinstance(item.get("taxonomy"), dict) else {}

    location = {
        "site": _clean_value(location.get("site")) or branch_id,
        "building": _clean_value(location.get("building")),
        "floor": _clean_value(location.get("floor")),
        "room": _clean_value(location.get("room")),
        "free_text": _clean_value(location.get("free_text")),
    }

    taxonomy = {
        "facilities_area": _clean_value(taxonomy.get("facilities_area")),
        "impacted_service": _clean_value(taxonomy.get("impacted_service")),
        "request_type": _clean_value(taxonomy.get("request_type")),
    }

    missing_required_fields: List[str] = []
    for field in REQUIRED_TAXONOMY_FIELDS:
        if not taxonomy.get(field):
            missing_required_fields.append(field)

    has_location_detail = any(location.get(field) for field in LOCATION_DETAIL_FIELDS)
    if not has_location_detail:
        missing_required_fields.append("location")

    clarifying_questions: List[str] = []
    if "location" in missing_required_fields:
        clarifying_questions.append(
            "Which site/branch and exact location (building/floor/room) is this in?"
        )
    if "facilities_area" in missing_required_fields:
        clarifying_questions.append(
            "Which facilities area does this relate to? (e.g., Plumbing, Access & Security)"
        )
    if "impacted_service" in missing_required_fields:
        clarifying_questions.append(
            "What service is impacted (e.g., toilets, doors, access cards)?"
        )

    return {
        **item,
        "location": location,
        "taxonomy": taxonomy,
        "missing_required_fields": missing_required_fields,
        "clarifying_questions": clarifying_questions,
        "status": "needs_clarification" if missing_required_fields else "ready",
    }


def _join_text(values: Any) -> str:
    if not values:
        return ""
    if isinstance(values, list):
        return "; ".join(str(value) for value in values)
    return str(values)


def _format_assets(assets: Any) -> str:
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


def _flatten_request_for_export(request: Dict[str, Any]) -> Dict[str, Any]:
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
        "missing_required_fields": _join_text(request.get("missing_required_fields")),
        "clarifying_questions": _join_text(request.get("clarifying_questions")),
        "assets": _format_assets(request.get("assets")),
        "confidence_overall": confidence.get("overall"),
        "confidence_urgency": confidence.get("urgency"),
        "confidence_location": confidence.get("location"),
        "confidence_taxonomy": confidence.get("taxonomy"),
    }


def _build_issues_export_file(rows: List[Dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "issues"
    sheet.append(EXPORT_COLUMNS)
    for row in rows:
        sheet.append([row.get(column, "") for column in EXPORT_COLUMNS])

    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output.getvalue()


class UserContext(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None


class IntakeRequest(BaseModel):
    message_id: str
    thread_id: Optional[str] = None
    tenant_id: str
    branch_id: str
    reporter_email: Optional[str] = None
    channel: str = "chatbot"
    message_text: str
    user_context: Optional[UserContext] = None
    received_at: Optional[str] = None


class ClarifyRequest(BaseModel):
    additional_text: Optional[str] = None
    answers: Dict[str, Any] = Field(default_factory=dict)


class AnalyticsSchemaUpdate(BaseModel):
    tenant_id: str
    fields: List[Dict[str, Any]]


app = FastAPI(title="Support Bot", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.post("/v1/intake/text")
async def intake_text(payload: IntakeRequest) -> Dict[str, Any]:
    saved_message = storage.save_message(payload.dict())
    if "extraction" in saved_message:
        return {"requests": saved_message["extraction"], "message_saved": True}

    extraction = llm_client.extract_requests(payload.message_text)
    requests_output = []
    for item in extraction.get("requests", []):
        normalized = _normalize_request_item(item, payload.branch_id)
        record = storage.create_request(
            {
                "tenant_id": payload.tenant_id,
                "branch_id": payload.branch_id,
                "source_message_id": payload.message_id,
                "reporter_email": payload.reporter_email,
                "title": normalized.get("title"),
                "description": normalized.get("description"),
                "urgency": normalized.get("urgency"),
                "location": normalized.get("location"),
                "taxonomy": normalized.get("taxonomy"),
                "safety_or_access_impact": normalized.get("safety_or_access_impact"),
                "assets": normalized.get("assets", []),
                "missing_required_fields": normalized.get("missing_required_fields", []),
                "clarifying_questions": normalized.get("clarifying_questions", []),
                "confidence": normalized.get("confidence", {}),
                "status": normalized.get("status"),
            }
        )
        storage.add_message(record["request_id"], "user", payload.message_text)
        summary = f"Drafted: {record.get('title')} · urgency {record.get('urgency') or 'unknown'}."
        storage.add_message(record["request_id"], "bot", summary)
        if record.get("clarifying_questions"):
            storage.add_message(
                record["request_id"], "bot", record["clarifying_questions"][0]
            )
        else:
            storage.add_message(record["request_id"], "bot", "All required slots are filled.")
        requests_output.append(record)

    storage.update_message_extraction(payload.message_id, requests_output)
    return {"requests": requests_output, "message_saved": True}


@app.post("/v1/audio/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    prompt: Optional[str] = Form(default=None),
) -> Dict[str, str]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Audio filename is required")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Audio file is empty")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=400, detail="Audio file exceeds 25MB limit")

    try:
        text = llm_client.transcribe_audio(
            audio_file=content,
            filename=file.filename,
            prompt=prompt,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=502, detail=f"Transcription failed: {error}") from error

    return {"text": text}


@app.post("/v1/requests/{request_id}/clarify")
async def clarify_request(request_id: str, payload: ClarifyRequest) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    updates = {"missing_required_fields": [], "clarifying_questions": []}
    updated_request = storage.update_request(request_id, {**request, **updates})

    if payload.additional_text:
        storage.add_message(request_id, "user", payload.additional_text)
        extraction = llm_client.extract_requests(
            f"Existing request: {request.get('description')}\nUser update: {payload.additional_text}"
        )
        if extraction.get("requests"):
            enriched = _normalize_request_item(extraction["requests"][0], request.get("branch_id"))
            updated_request = storage.update_request(
                request_id,
                {
                    "title": enriched.get("title", request.get("title")),
                    "description": enriched.get("description", request.get("description")),
                    "urgency": enriched.get("urgency", request.get("urgency")),
                    "location": enriched.get("location", request.get("location")),
                    "taxonomy": enriched.get("taxonomy", request.get("taxonomy")),
                    "safety_or_access_impact": enriched.get(
                        "safety_or_access_impact", request.get("safety_or_access_impact")
                    ),
                    "assets": enriched.get("assets", request.get("assets")),
                    "missing_required_fields": enriched.get("missing_required_fields", []),
                    "clarifying_questions": enriched.get("clarifying_questions", []),
                    "confidence": enriched.get("confidence", request.get("confidence")),
                    "status": enriched.get("status", "ready"),
                },
            )
            summary = f"Updated request: {updated_request.get('title')} ({updated_request.get('status')})."
            storage.add_message(request_id, "bot", summary)
            if updated_request.get("clarifying_questions"):
                storage.add_message(
                    request_id, "bot", updated_request["clarifying_questions"][0]
                )
            else:
                storage.add_message(
                    request_id, "bot", "All required slots are filled."
                )

    if payload.answers:
        updated_request = storage.update_request(
            request_id,
            {
                "answers": payload.answers,
                "status": "ready",
            },
        )

    return updated_request


@app.post("/v1/requests/{request_id}/submit")
async def submit_request(request_id: str) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    updated = storage.update_request(request_id, {"status": "submitted"})
    storage.add_message(request_id, "bot", "Submitted ✅ Your request is on the way.")
    return updated


@app.get("/v1/requests/{request_id}")
async def get_request(request_id: str) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


@app.get("/v1/requests")
async def list_requests(reporter_email: Optional[str] = None) -> Dict[str, Any]:
    return {"requests": storage.list_requests(reporter_email=reporter_email)}


@app.get("/v1/requests/{request_id}/messages")
async def get_request_messages(request_id: str) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return {"request_id": request_id, "messages": storage.list_messages(request_id)}


@app.get("/v1/taxonomy")
async def get_taxonomy() -> Dict[str, Any]:
    return {"facilities_areas": storage.get_taxonomy()}


@app.get("/v1/analytics/schema")
async def get_analytics_schema(tenant_id: str) -> Dict[str, Any]:
    return {"tenant_id": tenant_id, "fields": storage.get_analytics_schema(tenant_id)}


@app.post("/v1/analytics/schema")
async def update_analytics_schema(payload: AnalyticsSchemaUpdate) -> Dict[str, Any]:
    storage.save_analytics_schema(payload.tenant_id, payload.fields)
    return {"tenant_id": payload.tenant_id, "fields": payload.fields}


@app.get("/v1/admin/stats")
async def admin_stats() -> Dict[str, Any]:
    requests = storage.list_requests()
    by_status: Dict[str, int] = {}
    for request in requests:
        status = request.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    return {
        "total_requests": len(requests),
        "by_status": by_status,
    }


@app.get("/v1/admin/export/issues.xlsx")
async def export_issues_xlsx() -> StreamingResponse:
    requests = storage.list_requests()
    rows = [_flatten_request_for_export(request) for request in requests]
    payload = _build_issues_export_file(rows)
    filename = f"issues-history-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.xlsx"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
