from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

import requests

logger = logging.getLogger(__name__)


CONVERSATION_SLOTS: List[Dict[str, Any]] = [
    {
        "name": "urgency",
        "description": "Urgency: how quickly this issue/request should be resolved",
        "budget": 1,
    },
    {
        "name": "location",
        "description": "Location related to the issue/request (preferably building, floor, room)",
        "budget": 2,
    },
    {
        "name": "issue",
        "description": "Core issue/request details; ensure user has clearly stated the problem",
        "budget": 2,
    },
]

FACILITY_CLF_PROMPT = '''
Service request taxonomy:
{taxonomy}

User request:
{title}
{description}

Choose the most suitable request_type "id" from the taxonomy above.
If nothing matches, return "out_of_taxonomy".

Return strict JSON:
{{"id": "carpentry_interiors.bathroom_accessories.dispenser_loose"}}
or
{{"id": "out_of_taxonomy"}}
'''.strip()

LOCATION_PARSE_PROMPT = '''
{conversation_history}
---

From the conversation above, determine the request location if possible.
Return structured fields (if missing, use "unknown"):
- building
- floor
- room

Also provide free_text with only the location phrase from the dialogue.
If location is not mentioned, return "unknown".

Return strict JSON, e.g.
{{"building": "723 Swanston Street", "floor": "2", "room": "MSPC team office", "free_text": "MSPC team office on level 2, 723 Swanston Street"}}
or
{{"building": "unknown", "floor": "unknown", "room": "8", "free_text": "room 8"}}
or
{{"building": "unknown", "floor": "unknown", "room": "women toilet", "free_text": "women toilet"}}
or
{{"building": "unknown", "floor": "unknown", "room": "unknown", "free_text": "unknown"}}
'''.strip()

ISSUE_SUMMARY_PROMPT = '''
{conversation_history}
---
From the conversation above, produce:
- title: shortest clear issue label
- details: as complete issue/request summary as possible

Return strict JSON:
{{"title": "Very short issue label", "details": "Detailed issue/request summary from conversation"}}
'''.strip()

URGENCY_CLF_PROMPT = '''
{conversation_history}
---
Classify urgency from the full conversation.
Use:
- low: no urgency / can wait
- normal: standard priority
- high: needs to be resolved as soon as possible
- unknown: cannot determine from conversation

Return strict JSON, e.g.
{{"result": "low"}}
'''.strip()

SAFETY_OR_ACCESS_CLF_PROMPT = '''
{conversation_history}
---
Determine whether the issue affects safety or access.

Return strict JSON:
{{"result": true}}
or
{{"result": false}}
'''.strip()

ASSISTENT_PROMPT = '''
{conversation_history}
---
Above is a support conversation history for facility requests.
Your goal is to clarify {slot_name} - {slot_description}.

Write one assistant message to the user.
Return only JSON:
{{"response": "Assistant message text"}}
'''.strip()

SUPERVISOR_PROMPT = '''
{conversation_history}
---
Above is the support conversation history.
Check whether {slot_name} - {slot_description} was mentioned in the conversation.

If user provided direct/indirect info about the slot -> mentioned = True.
If assistant asked about the slot, but user could not answer / ignored / partially answered -> also mentioned = True.

Return strict JSON:
{{"mentioned": true}}
'''.strip()


@dataclass
class AgentResult:
    request: Dict[str, Any]


class DialogAgent:
    def __init__(self) -> None:
        self.model_name = os.getenv("OPENAI_MODEL", "gpt-5.1-mini")
        self.api_key = os.getenv("OPENAI_API_KEY")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")

    def run_turn(
        self,
        request: Dict[str, Any],
        history: List[Dict[str, Any]],
        user_text: str,
        taxonomy: List[Dict[str, Any]],
    ) -> AgentResult:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required")

        req = copy.deepcopy(request)
        dialog_state = req.get("dialog_state") if isinstance(req.get("dialog_state"), dict) else {}
        dialog_state.setdefault("phase", "collect")
        dialog_state.setdefault("target_slots", [dict(slot) for slot in CONVERSATION_SLOTS])
        dialog_state.setdefault("slot_mentioned", {})
        dialog_state.setdefault("slot_last_supervisor", {})
        req["dialog_state"] = dialog_state

        conversation_history = self._history_to_text(history)

        # Skip already mentioned / exhausted slots
        target_slots = dialog_state.get("target_slots") if isinstance(dialog_state.get("target_slots"), list) else []
        drop: List[int] = []
        for i, slot in enumerate(target_slots):
            response = self._openrouter_call(
                prompt=SUPERVISOR_PROMPT.format(
                    conversation_history=conversation_history,
                    slot_name=slot["name"],
                    slot_description=slot["description"],
                ),
                schema=self._supervisor_response_schema(),
            )
            mentioned = bool(response.get("mentioned"))
            dialog_state["slot_last_supervisor"][slot["name"]] = mentioned
            if mentioned:
                dialog_state["slot_mentioned"][slot["name"]] = True
            if mentioned or int(slot.get("budget", 0)) <= 0:
                drop.append(i)

        target_slots = [slot for i, slot in enumerate(target_slots) if i not in drop]
        dialog_state["target_slots"] = target_slots

        if target_slots:
            slot = target_slots[0]
            response = self._openrouter_call(
                prompt=ASSISTENT_PROMPT.format(
                    conversation_history=conversation_history,
                    slot_name=slot["name"],
                    slot_description=slot["description"],
                ),
                schema=self._assistant_response_schema(),
            )
            text = str(response.get("response") or "Could you share more details?").strip() or "Could you share more details?"

            target_slots[0]["budget"] = max(int(target_slots[0].get("budget", 0)) - 1, 0)
            dialog_state["phase"] = "targeted_clarify"
            req["dialog_state"] = dialog_state
            req["clarifying_questions"] = [text]
            req["status"] = "needs_clarification"
            req["missing_required_fields"] = [slot.get("name") for slot in target_slots if int(slot.get("budget", 0)) > 0]
            return AgentResult(request=req)

        # Parse after all slots were discussed
        issue = self._openrouter_call(
            prompt=ISSUE_SUMMARY_PROMPT.format(conversation_history=conversation_history),
            schema=self._issue_response_schema(),
        )
        title = str(issue.get("title") or req.get("title") or "Facility request")
        description = str(issue.get("details") or req.get("description") or "")

        taxonomy_inject = json.dumps(taxonomy, ensure_ascii=False)
        facility = self._openrouter_call(
            prompt=FACILITY_CLF_PROMPT.format(
                taxonomy=taxonomy_inject,
                title=title,
                description=description,
            ),
            schema=self._facility_response_schema(taxonomy),
        )
        request_type = str(facility.get("id") or "out_of_taxonomy")

        if request_type == "out_of_taxonomy":
            facilities_area, impacted_service = "unknown", "unknown"
            request_type = "unknown"
        else:
            facilities_area, impacted_service = self._get_request_roots(request_type, taxonomy)

        location = self._openrouter_call(
            prompt=LOCATION_PARSE_PROMPT.format(conversation_history=conversation_history),
            schema=self._location_response_schema(),
        )

        urgency = self._openrouter_call(
            prompt=URGENCY_CLF_PROMPT.format(conversation_history=conversation_history),
            schema=self._urgency_response_schema(),
        )
        urgency_value = str(urgency.get("result") or "unknown").lower()
        if urgency_value not in {"low", "normal", "high", "unknown"}:
            urgency_value = "unknown"

        safety_or_access = self._openrouter_call(
            prompt=SAFETY_OR_ACCESS_CLF_PROMPT.format(conversation_history=conversation_history),
            schema=self._safety_or_access_response_schema(),
        )

        req["title"] = title
        req["description"] = description
        req["urgency"] = urgency_value
        req["safety_or_access_impact"] = bool(safety_or_access.get("result"))

        location_old = req.get("location") if isinstance(req.get("location"), dict) else {}
        req["location"] = {
            **location_old,
            "building": location.get("building"),
            "floor": location.get("floor"),
            "room": location.get("room"),
            "free_text": location.get("free_text"),
        }

        taxonomy_old = req.get("taxonomy") if isinstance(req.get("taxonomy"), dict) else {}
        req["taxonomy"] = {
            **taxonomy_old,
            "facilities_area": facilities_area,
            "impacted_service": impacted_service,
            "request_type": request_type,
        }

        dialog_state["phase"] = "ready_for_submit"
        dialog_state["problem"] = {"text": description, "confirmed": True}
        req["dialog_state"] = dialog_state
        req["status"] = "ready"
        req["missing_required_fields"] = []
        req["clarifying_questions"] = [
            "I drafted your request from our conversation. If everything looks good, use the Submit button to send it."
        ]
        return AgentResult(request=req)

    def _openrouter_call(self, prompt: str, schema: Dict[str, Any], temperature: float = 0.3, max_tokens: int = 1000) -> Dict[str, Any]:
        messages = [{"role": "user", "content": prompt}]
        response = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model_name,
                "messages": messages,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": schema,
                },
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
                "reasoning": {"enabled": False},
            },
            timeout=60,
        )
        if not response.ok:
            logger.error("OpenRouter error response: %s", response.text)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)

    def _history_to_text(self, history: List[Dict[str, Any]]) -> str:
        if not history:
            return ""
        lines: List[str] = []
        for item in history:
            sender = item.get("sender")
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            role = "ASSISTANT" if sender == "bot" else "USER"
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    def _all_facility_ids(self, taxonomy: List[Dict[str, Any]]) -> List[str]:
        ids: List[str] = []
        for area in taxonomy:
            if not isinstance(area, dict):
                continue
            for service in area.get("impacted_services", []):
                if not isinstance(service, dict):
                    continue
                for request_type in service.get("request_types", []):
                    if isinstance(request_type, dict) and isinstance(request_type.get("id"), str):
                        ids.append(request_type["id"])
        return ids

    def _get_request_roots(self, request_type_id: str, taxonomy: List[Dict[str, Any]]) -> Tuple[str, str]:
        for area in taxonomy:
            if not isinstance(area, dict):
                continue
            area_id = area.get("id")
            for service in area.get("impacted_services", []):
                if not isinstance(service, dict):
                    continue
                service_id = service.get("id")
                for request_type in service.get("request_types", []):
                    if isinstance(request_type, dict) and request_type.get("id") == request_type_id:
                        return str(area_id or "unknown"), str(service_id or "unknown")
        return "unknown", "unknown"

    def _facility_response_schema(self, taxonomy: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {
            "name": "facility",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "enum": self._all_facility_ids(taxonomy) + ["out_of_taxonomy"],
                        "description": "ID of the best matching request type from taxonomy or out_of_taxonomy",
                    }
                },
                "required": ["id"],
                "additionalProperties": False,
            },
        }

    def _location_response_schema(self) -> Dict[str, Any]:
        return {
            "name": "location",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "building": {"type": "string"},
                    "floor": {"type": "string"},
                    "room": {"type": "string"},
                    "free_text": {"type": "string"},
                },
                "required": ["building", "floor", "room", "free_text"],
                "additionalProperties": False,
            },
        }

    def _issue_response_schema(self) -> Dict[str, Any]:
        return {
            "name": "issue",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Very short issue label"},
                    "details": {
                        "type": "string",
                        "description": "Detailed issue/request summary from conversation",
                    },
                },
                "required": ["title", "details"],
                "additionalProperties": False,
            },
        }

    def _urgency_response_schema(self) -> Dict[str, Any]:
        return {
            "name": "urgency",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "string",
                        "enum": ["low", "normal", "high", "unknown"],
                        "description": "Urgency class",
                    }
                },
                "required": ["result"],
                "additionalProperties": False,
            },
        }

    def _safety_or_access_response_schema(self) -> Dict[str, Any]:
        return {
            "name": "safety_or_access",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "result": {
                        "type": "boolean",
                        "description": "Whether the issue affects safety or access",
                    }
                },
                "required": ["result"],
                "additionalProperties": False,
            },
        }

    def _assistant_response_schema(self) -> Dict[str, Any]:
        return {
            "name": "assistant_response",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "response": {"type": "string"},
                },
                "required": ["response"],
                "additionalProperties": False,
            },
        }

    def _supervisor_response_schema(self) -> Dict[str, Any]:
        return {
            "name": "supervisor",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "mentioned": {"type": "boolean"},
                },
                "required": ["mentioned"],
                "additionalProperties": False,
            },
        }


dialog_agent = DialogAgent()
