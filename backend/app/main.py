from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .llm import llm_client
from .storage import storage


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
        record = storage.create_request(
            {
                "tenant_id": payload.tenant_id,
                "branch_id": payload.branch_id,
                "source_message_id": payload.message_id,
                "reporter_email": payload.reporter_email,
                "title": item.get("title"),
                "description": item.get("description"),
                "urgency": item.get("urgency"),
                "location": item.get("location"),
                "taxonomy": item.get("taxonomy"),
                "safety_or_access_impact": item.get("safety_or_access_impact"),
                "assets": item.get("assets", []),
                "missing_required_fields": item.get("missing_required_fields", []),
                "clarifying_questions": item.get("clarifying_questions", []),
                "confidence": item.get("confidence", {}),
                "status": "needs_clarification"
                if item.get("missing_required_fields")
                else "ready",
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
            enriched = extraction["requests"][0]
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
                    "status": "needs_clarification"
                    if enriched.get("missing_required_fields")
                    else "ready",
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


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
