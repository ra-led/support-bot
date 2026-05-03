import io
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from .auth import assert_admin_password
from .dialog_agent import dialog_agent
from .export_utils import build_issues_export_file
from .request_utils import apply_answers_to_request
from .schemas import AnalyticsSchemaUpdate, ClarifyRequest, IntakeRequest, TaxonomyUpdate
from .storage import storage
from .transcription import transcribe_audio as transcribe_audio_with_llm

logger = logging.getLogger(__name__)

MAX_AUDIO_BYTES = 25 * 1024 * 1024
router = APIRouter()
ACTIVE_REQUEST_STATUSES = {"needs_clarification"}


def _is_request_active(request: Dict[str, Any]) -> bool:
    return request.get("status") in ACTIVE_REQUEST_STATUSES


def _matches_thread(request: Dict[str, Any], thread_id: Optional[str]) -> bool:
    if not thread_id:
        return False
    dialog_state = request.get("dialog_state") if isinstance(request.get("dialog_state"), dict) else {}
    return dialog_state.get("thread_id") == thread_id


def _find_or_create_active_request(payload: IntakeRequest) -> Dict[str, Any]:
    requests = storage.list_requests(reporter_email=payload.reporter_email)
    active_requests = [request for request in requests if _is_request_active(request)]

    if payload.thread_id:
        for request in active_requests:
            if _matches_thread(request, payload.thread_id):
                return request

    for request in active_requests:
        if request.get("tenant_id") == payload.tenant_id and request.get("branch_id") == payload.branch_id:
            return request

    return storage.create_request(
        {
            "tenant_id": payload.tenant_id,
            "branch_id": payload.branch_id,
            "source_message_id": payload.message_id,
            "reporter_email": payload.reporter_email,
            "title": "New facility request",
            "description": "",
            "urgency": "unknown",
            "location": {
                "site": payload.branch_id,
                "building": None,
                "floor": None,
                "room": None,
                "free_text": None,
            },
            "taxonomy": {
                "facilities_area": None,
                "impacted_service": None,
                "request_type": None,
            },
            "safety_or_access_impact": None,
            "assets": [],
            "missing_required_fields": [],
            "clarifying_questions": [],
            "confidence": {},
            "dialog_state": {"thread_id": payload.thread_id} if payload.thread_id else {},
            "status": "needs_clarification",
        }
    )


def _is_valid_for_submit(request: Dict[str, Any]) -> bool:
    status_ok = request.get("status") in {"ready", "submitted"}
    dialog_state = request.get("dialog_state") if isinstance(request.get("dialog_state"), dict) else {}
    problem = dialog_state.get("problem") if isinstance(dialog_state.get("problem"), dict) else {}
    problem_text = (problem.get("text") or "").strip()
    return bool(status_ok and len(problem_text) >= 8)


@router.post("/v1/intake/text")
async def intake_text(payload: IntakeRequest) -> Dict[str, Any]:
    saved_message = storage.save_message(payload.dict())
    if "extraction" in saved_message:
        return {"requests": saved_message["extraction"], "message_saved": True}

    request = _find_or_create_active_request(payload)
    if payload.thread_id and not _matches_thread(request, payload.thread_id):
        dialog_state = request.get("dialog_state") if isinstance(request.get("dialog_state"), dict) else {}
        request = storage.update_request(
            request["request_id"],
            {
                **request,
                "dialog_state": {**dialog_state, "thread_id": payload.thread_id},
            },
        )

    request = storage.update_request(
        request["request_id"],
        {
            **request,
            "source_message_id": payload.message_id,
            "tenant_id": payload.tenant_id,
            "branch_id": payload.branch_id,
            "reporter_email": payload.reporter_email,
        },
    )

    taxonomy = storage.get_taxonomy()
    storage.add_message(request["request_id"], "user", payload.message_text)
    history = storage.list_messages(request["request_id"])
    try:
        agent_result = dialog_agent.run_turn(
            request=request,
            history=history,
            user_text=payload.message_text,
            taxonomy=taxonomy,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error

    record = storage.update_request(request["request_id"], agent_result.request)
    if record.get("clarifying_questions"):
        storage.add_message(record["request_id"], "bot", record["clarifying_questions"][0])
    elif record.get("status") == "submitted":
        storage.add_message(record["request_id"], "bot", "Submitted ✅ Your request is on the way.")
    else:
        storage.add_message(record["request_id"], "bot", "All required slots are filled.")
    requests_output = [record]

    storage.update_message_extraction(payload.message_id, requests_output)
    return {"requests": requests_output, "message_saved": True}


@router.post("/v1/audio/transcribe")
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

    logger.info(
        "[audio][back] request received filename=%s content_type=%s size=%s header_hex=%s prompt=%s",
        file.filename,
        file.content_type,
        len(content),
        content[:16].hex(),
        prompt,
    )

    try:
        text = transcribe_audio_with_llm(
            audio_file=content,
            filename=file.filename,
            prompt=prompt,
        )
        logger.info("[audio][back] transcribe success filename=%s text_len=%s", file.filename, len(text))
    except RuntimeError as error:
        logger.warning("[audio][back] transcribe runtime error filename=%s error=%s", file.filename, error)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        logger.exception("[audio][back] transcribe provider error filename=%s", file.filename)
        raise HTTPException(status_code=502, detail=f"Transcription failed: {error}") from error

    return {"text": text}


@router.post("/v1/requests/{request_id}/clarify")
async def clarify_request(request_id: str, payload: ClarifyRequest) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    working_request = request
    if payload.answers:
        working_request = apply_answers_to_request(working_request, payload.answers)

    if payload.additional_text:
        storage.add_message(request_id, "user", payload.additional_text)

    user_turn_text = payload.additional_text or ""
    if payload.answers:
        answers_text = "; ".join(f"{k}: {v}" for k, v in payload.answers.items())
        user_turn_text = f"{user_turn_text}\n{answers_text}".strip()
        if not payload.additional_text:
            storage.add_message(request_id, "user", answers_text)

    history = storage.list_messages(request_id)
    try:
        agent_result = dialog_agent.run_turn(
            request=working_request,
            history=history,
            user_text=user_turn_text,
            taxonomy=storage.get_taxonomy(),
        )
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    updated_request = storage.update_request(request_id, agent_result.request)

    if updated_request.get("clarifying_questions"):
        storage.add_message(request_id, "bot", updated_request["clarifying_questions"][0])
    elif updated_request.get("status") == "submitted":
        storage.add_message(request_id, "bot", "Submitted ✅ Your request is on the way.")
    else:
        storage.add_message(request_id, "bot", "All required slots are filled.")

    return updated_request


@router.post("/v1/requests/{request_id}/submit")
async def submit_request(request_id: str) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if not _is_valid_for_submit(request):
        raise HTTPException(
            status_code=409,
            detail="Request is incomplete. Please describe the problem and required details first.",
        )
    updated = storage.update_request(request_id, {"status": "submitted"})
    storage.add_message(request_id, "bot", "Submitted ✅ Your request is on the way.")
    return updated


@router.get("/v1/requests/{request_id}")
async def get_request(request_id: str) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    return request


@router.get("/v1/requests")
async def list_requests(
    reporter_email: Optional[str] = None,
    x_admin_password: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    if reporter_email is None:
        assert_admin_password(x_admin_password)
    return {"requests": storage.list_requests(reporter_email=reporter_email)}


@router.get("/v1/requests/{request_id}/messages")
async def get_request_messages(
    request_id: str,
    reporter_email: Optional[str] = None,
    x_admin_password: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    request = storage.get_request(request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")
    if reporter_email:
        if request.get("reporter_email") != reporter_email:
            raise HTTPException(status_code=403, detail="Forbidden")
    else:
        assert_admin_password(x_admin_password)
    return {"request_id": request_id, "messages": storage.list_messages(request_id)}


@router.get("/v1/taxonomy")
async def get_taxonomy() -> Dict[str, Any]:
    return {"facilities_areas": storage.get_taxonomy()}


@router.get("/v1/admin/taxonomy")
async def admin_get_taxonomy(
    x_admin_password: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    assert_admin_password(x_admin_password)
    return {"facilities_areas": storage.get_taxonomy()}


@router.put("/v1/admin/taxonomy")
async def admin_update_taxonomy(
    payload: TaxonomyUpdate,
    x_admin_password: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    assert_admin_password(x_admin_password)
    try:
        storage.save_taxonomy(payload.facilities_areas)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"facilities_areas": storage.get_taxonomy()}


@router.get("/v1/analytics/schema")
async def get_analytics_schema(tenant_id: str) -> Dict[str, Any]:
    return {"tenant_id": tenant_id, "fields": storage.get_analytics_schema(tenant_id)}


@router.post("/v1/analytics/schema")
async def update_analytics_schema(payload: AnalyticsSchemaUpdate) -> Dict[str, Any]:
    storage.save_analytics_schema(payload.tenant_id, payload.fields)
    return {"tenant_id": payload.tenant_id, "fields": payload.fields}


@router.get("/v1/admin/stats")
async def admin_stats(x_admin_password: Optional[str] = Header(default=None)) -> Dict[str, Any]:
    assert_admin_password(x_admin_password)
    requests = storage.list_requests()
    by_status: Dict[str, int] = {}
    for request in requests:
        status = request.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

    return {"total_requests": len(requests), "by_status": by_status}


@router.get("/v1/admin/traces/{dialog_id}")
async def admin_get_dialog_traces(
    dialog_id: str,
    x_admin_password: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    assert_admin_password(x_admin_password)
    request = storage.get_request(dialog_id)
    if not request:
        raise HTTPException(status_code=404, detail="Dialog not found")
    traces = storage.list_llm_traces(dialog_id)
    return {"dialog_id": dialog_id, "request": request, "traces": traces}


@router.get("/v1/admin/export/issues.xlsx")
async def export_issues_xlsx(
    x_admin_password: Optional[str] = Header(default=None),
) -> StreamingResponse:
    assert_admin_password(x_admin_password)
    requests = storage.list_requests()
    payload = build_issues_export_file(requests)
    filename = f"issues-history-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}.xlsx"
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}
