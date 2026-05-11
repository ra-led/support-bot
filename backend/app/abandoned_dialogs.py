from __future__ import annotations

import datetime as dt
import logging
from typing import Dict

from .dialog_agent import dialog_agent
from .storage import storage

logger = logging.getLogger(__name__)

ABANDONED_AFTER_MINUTES = 20
ABANDONED_ACTIVE_STATUSES = ["needs_clarification", "ready"]


def process_abandoned_dialogs() -> Dict[str, int]:
    cutoff = (dt.datetime.utcnow() - dt.timedelta(minutes=ABANDONED_AFTER_MINUTES)).isoformat()
    stale_requests = storage.list_stale_requests(
        statuses=ABANDONED_ACTIVE_STATUSES,
        cutoff_created_at=cutoff,
    )
    processed = 0
    failed = 0

    for request in stale_requests:
        request_id = str(request.get("request_id") or "")
        try:
            dialog_state = request.get("dialog_state") if isinstance(request.get("dialog_state"), dict) else {}
            if request.get("status") == "ready":
                storage.update_request(
                    request_id,
                    {
                        **request,
                        "status": "submitted",
                        "clarifying_questions": [],
                        "dialog_state": {
                            **dialog_state,
                            "abandoned": True,
                            "phase": "abandoned_submitted",
                        },
                    },
                )
            else:
                history = storage.list_messages(request_id)
                agent_result = dialog_agent.finalize_from_history(
                    request=request,
                    history=history,
                    taxonomy=storage.get_taxonomy(),
                    status="submitted",
                    clarifying_questions=[],
                    abandoned=True,
                )
                storage.update_request(request_id, agent_result.request)
            processed += 1
        except Exception:
            failed += 1
            logger.exception("Failed to process abandoned dialog request_id=%s", request_id)

    return {"processed": processed, "failed": failed}
