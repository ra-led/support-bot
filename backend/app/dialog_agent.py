from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

from langgraph.graph import END, START, MessagesState, StateGraph

from .request_extractor import extract_slot_delta, merge_request_with_delta


DialogPhase = Literal["collect", "confirm_problem", "targeted_clarify", "submitted"]


class GraphState(MessagesState):
    request: Dict[str, Any]
    user_text: str
    taxonomy: List[Dict[str, Any]]
    extraction: Dict[str, Any]
    working: Dict[str, Any]
    next_step: str


@dataclass
class AgentResult:
    request: Dict[str, Any]


class DialogAgent:
    def __init__(self) -> None:
        graph = StateGraph(GraphState)
        graph.add_node("bootstrap", self._bootstrap)
        graph.add_node("extract_delta", self._extract_delta)
        graph.add_node("merge_delta", self._merge_delta)
        graph.add_node("plan", self._plan)
        graph.add_node("ask", self._ask)
        graph.add_node("submit", self._submit)

        graph.add_edge(START, "bootstrap")
        graph.add_edge("bootstrap", "extract_delta")
        graph.add_edge("extract_delta", "merge_delta")
        graph.add_edge("merge_delta", "plan")
        graph.add_conditional_edges("plan", self._route_after_plan, {"ask": "ask", "submit": "submit"})
        graph.add_edge("ask", END)
        graph.add_edge("submit", END)

        self.graph = graph.compile()

    def run_turn(
        self,
        request: Dict[str, Any],
        history: List[Dict[str, Any]],
        user_text: str,
        taxonomy: List[Dict[str, Any]],
    ) -> AgentResult:
        initial_state: GraphState = {
            "request": copy.deepcopy(request),
            "messages": self._history_to_messages(history),
            "user_text": user_text,
            "taxonomy": taxonomy,
            "extraction": {},
            "working": {},
            "next_step": "ask",
        }
        result = self.graph.invoke(initial_state)
        return AgentResult(request=result["request"])

    def _bootstrap(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request.get("dialog_state") if isinstance(request.get("dialog_state"), dict) else {}

        dialog_state.setdefault("phase", "collect")
        dialog_state.setdefault("problem", {"text": "", "confirmed": False})
        dialog_state.setdefault("slots", {})
        dialog_state.setdefault("slot_attempts", {})
        dialog_state.setdefault("slot_mentioned", {})
        dialog_state.setdefault("last_asked_slots", [])
        dialog_state.setdefault("clarify_attempts", 0)
        dialog_state.setdefault("ask_budget", 3)
        dialog_state.setdefault("rolling_summary", "")

        request["dialog_state"] = dialog_state
        return {"request": request}

    def _extract_delta(self, state: GraphState) -> GraphState:
        extraction = extract_slot_delta(state["user_text"], state["taxonomy"])
        return {"extraction": extraction if isinstance(extraction, dict) else {}}

    def _merge_delta(self, state: GraphState) -> GraphState:
        request = state["request"]
        extraction = state.get("extraction") or {}
        dialog_state = request["dialog_state"]
        user_text = (state.get("user_text") or "").strip()
        previous_request = copy.deepcopy(request)

        if self._delta_has_values(extraction):
            merged = merge_request_with_delta(request, extraction, state["taxonomy"])
            self._apply_merged_fields(request, merged, extraction)

        request["urgency"] = self._normalize_urgency(request.get("urgency"))

        candidate_problem = (request.get("description") or request.get("title") or "").strip()

        if self._is_meaningful_problem_text(candidate_problem):
            dialog_state["problem"]["text"] = candidate_problem
            dialog_state["problem"]["confirmed"] = True
        else:
            if (dialog_state.get("slots") or {}).get("problem", {}).get("status") == "unknown":
                dialog_state["problem"]["confirmed"] = True
                if not dialog_state["problem"].get("text"):
                    dialog_state["problem"]["text"] = "unknown"
            else:
                dialog_state["problem"]["confirmed"] = False

        taxonomy_obj = request.get("taxonomy") or {}
        facilities_area = self._clean_value(taxonomy_obj.get("facilities_area"))
        impacted_service = self._clean_value(taxonomy_obj.get("impacted_service"))

        known_facilities = self._taxonomy_facility_ids(state["taxonomy"])
        known_services = self._taxonomy_service_ids(state["taxonomy"])

        if facilities_area and facilities_area not in known_facilities:
            facilities_area = "unknown"
        if impacted_service and impacted_service not in known_services:
            impacted_service = "unknown"
        if not facilities_area and dialog_state["problem"].get("confirmed"):
            facilities_area = "unknown"
        if not impacted_service and dialog_state["problem"].get("confirmed"):
            impacted_service = "unknown"

        request["taxonomy"] = {
            **taxonomy_obj,
            "facilities_area": facilities_area,
            "impacted_service": impacted_service,
            "request_type": self._clean_value(taxonomy_obj.get("request_type")),
        }

        slots = dialog_state["slots"]
        slots["problem"] = {
            "value": dialog_state["problem"].get("text") or "",
            "status": self._slot_status(
                self._is_meaningful_problem_text(dialog_state["problem"].get("text") or ""),
                slots.get("problem", {}).get("status"),
            ),
        }

        location = request.get("location") or {}
        slots["location"] = {
            "value": json.dumps(location, ensure_ascii=False),
            "status": self._slot_status(self._has_specific_location_detail(location), slots.get("location", {}).get("status")),
        }

        slots["facilities_area"] = {
            "value": facilities_area or "",
            "status": self._slot_status(bool(facilities_area), slots.get("facilities_area", {}).get("status")),
        }
        slots["impacted_service"] = {
            "value": impacted_service or "",
            "status": self._slot_status(bool(impacted_service), slots.get("impacted_service", {}).get("status")),
        }

        slots["urgency"] = {
            "value": request.get("urgency") or "unknown",
            "status": self._slot_status((request.get("urgency") or "") in {"low", "normal", "high", "urgent"}, slots.get("urgency", {}).get("status")),
        }

        self._update_slot_mentions(dialog_state, extraction, user_text)
        self._guard_unknown_updates(previous_request, request, dialog_state)
        dialog_state["rolling_summary"] = self._update_summary(dialog_state.get("rolling_summary") or "", user_text)
        request["dialog_state"] = dialog_state
        return {"request": request}

    def _plan(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]

        self._auto_mark_stuck_slots_unknown(request)
        missing = self._collect_missing_slots(request)
        if not missing:
            return {"request": request, "next_step": "submit", "working": {}}

        next_slot = missing[0]
        dialog_state["phase"] = "confirm_problem" if next_slot == "problem" else "targeted_clarify"
        request["dialog_state"] = dialog_state
        return {
            "request": request,
            "next_step": "ask",
            "working": {
                "ask_slots": [next_slot],
                "message": self._slot_question(next_slot),
            },
        }

    def _route_after_plan(self, state: GraphState) -> str:
        return state.get("next_step", "ask")

    def _ask(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]
        ask_slots = state.get("working", {}).get("ask_slots", [])
        message = state.get("working", {}).get("message") or "Уточните, пожалуйста, детали."

        for slot in ask_slots:
            dialog_state["slot_attempts"][slot] = dialog_state["slot_attempts"].get(slot, 0) + 1
        dialog_state["clarify_attempts"] = int(dialog_state.get("clarify_attempts", 0)) + 1
        dialog_state["last_asked_slots"] = ask_slots

        request["clarifying_questions"] = [message]
        request["missing_required_fields"] = self._collect_missing_slots(request)
        request["status"] = "needs_clarification"
        request["dialog_state"] = dialog_state
        return {"request": request}

    def _submit(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]
        dialog_state["phase"] = "submitted"
        request["dialog_state"] = dialog_state
        request["missing_required_fields"] = []
        request["clarifying_questions"] = []
        request["status"] = "submitted"
        return {"request": request}

    def _apply_merged_fields(self, request: Dict[str, Any], merged: Dict[str, Any], slot_delta: Dict[str, Any]) -> None:
        for key in ("title", "description", "urgency", "safety_or_access_impact"):
            cleaned = self._clean_value(merged.get(key)) if key != "safety_or_access_impact" else merged.get(key)
            if cleaned is not None:
                request[key] = cleaned

        request["location"] = self._merge_nested(request.get("location"), merged.get("location"))
        request["taxonomy"] = self._merge_taxonomy_from_delta(
            request.get("taxonomy"),
            merged.get("taxonomy"),
            slot_delta.get("taxonomy") if isinstance(slot_delta, dict) else None,
        )

        if isinstance(merged.get("assets"), list):
            request["assets"] = merged["assets"]

    def _delta_has_values(self, delta: Dict[str, Any]) -> bool:
        if not isinstance(delta, dict):
            return False
        for value in delta.values():
            if value is None:
                continue
            if isinstance(value, dict) and any(v is not None and str(v).strip() for v in value.values()):
                return True
            if isinstance(value, list) and value:
                return True
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, bool):
                return True
        return False

    def _collect_missing_slots(self, request: Dict[str, Any]) -> List[str]:
        dialog_state = request.get("dialog_state") or {}
        slots = dialog_state.get("slots") if isinstance(dialog_state.get("slots"), dict) else {}

        missing: List[str] = []
        required = ["problem", "location", "facilities_area", "impacted_service", "urgency"]
        for slot in required:
            if (slots.get(slot) or {}).get("status") == "unknown":
                continue
            if slot == "problem":
                if not self._is_meaningful_problem_text((dialog_state.get("problem") or {}).get("text") or ""):
                    missing.append(slot)
            elif slot == "location":
                if not self._has_specific_location_detail(request.get("location") or {}):
                    missing.append(slot)
            elif slot == "facilities_area":
                if not self._is_filled_slot_value((request.get("taxonomy") or {}).get("facilities_area")):
                    missing.append(slot)
            elif slot == "impacted_service":
                if not self._is_filled_slot_value((request.get("taxonomy") or {}).get("impacted_service")):
                    missing.append(slot)
            elif slot == "urgency":
                if (request.get("urgency") or "unknown") not in {"low", "normal", "high", "urgent"}:
                    missing.append(slot)
        return missing

    def _slot_question(self, slot: str) -> str:
        if slot == "problem":
            return "Опишите, пожалуйста, что именно сломано/что нужно исправить."
        if slot == "location":
            return "Уточните локацию: building/этаж/комната или другой конкретный ориентир."
        if slot == "facilities_area":
            return "Уточните тип проблемы (например: электрика, сантехника, доступ)."
        if slot == "impacted_service":
            return "Уточните, что именно затронуто (например: дверь, туалет, кондиционер)."
        if slot == "urgency":
            return "Насколько срочно это нужно решить?"
        return "Уточните, пожалуйста, детали."

    def _slot_status(self, is_filled: bool, previous_status: Optional[str]) -> str:
        if previous_status == "unknown":
            return "unknown"
        return "filled" if is_filled else "empty"

    def _has_specific_location_detail(self, location: Dict[str, Any]) -> bool:
        for key in ("building", "floor", "room", "free_text"):
            value = self._clean_value((location or {}).get(key))
            if value and value.lower() not in {"unknown", "unknow"}:
                return True
        return False

    def _update_slot_mentions(self, dialog_state: Dict[str, Any], extraction: Dict[str, Any], user_text: str) -> None:
        mentions = dialog_state.get("slot_mentioned")
        if not isinstance(mentions, dict):
            mentions = {}
            dialog_state["slot_mentioned"] = mentions

        for slot in dialog_state.get("last_asked_slots", []):
            if (user_text or "").strip():
                mentions[slot] = True

        if self._clean_value((extraction.get("description") if isinstance(extraction, dict) else None)) or self._clean_value(
            extraction.get("title") if isinstance(extraction, dict) else None
        ):
            mentions["problem"] = True
        if isinstance(extraction.get("location") if isinstance(extraction, dict) else None, dict):
            location = extraction.get("location") or {}
            if any(self._clean_value(v) for v in location.values()):
                mentions["location"] = True
        if isinstance(extraction.get("taxonomy") if isinstance(extraction, dict) else None, dict):
            taxonomy = extraction.get("taxonomy") or {}
            if self._clean_value(taxonomy.get("facilities_area")):
                mentions["facilities_area"] = True
            if self._clean_value(taxonomy.get("impacted_service")):
                mentions["impacted_service"] = True
        if self._clean_value(extraction.get("urgency") if isinstance(extraction, dict) else None):
            mentions["urgency"] = True

    def _guard_unknown_updates(self, previous_request: Dict[str, Any], request: Dict[str, Any], dialog_state: Dict[str, Any]) -> None:
        mentions = dialog_state.get("slot_mentioned") if isinstance(dialog_state.get("slot_mentioned"), dict) else {}
        asked = set(dialog_state.get("last_asked_slots") or [])
        problem_confirmed = bool((dialog_state.get("problem") or {}).get("confirmed"))

        if (request.get("urgency") or "").strip().lower() in {"unknown", "unknow"} and not (mentions.get("urgency") or "urgency" in asked):
            request["urgency"] = previous_request.get("urgency")

        current_location = request.get("location") if isinstance(request.get("location"), dict) else {}
        previous_location = previous_request.get("location") if isinstance(previous_request.get("location"), dict) else {}
        if (self._clean_value(current_location.get("free_text")) or "").lower() in {"unknown", "unknow"} and not (
            mentions.get("location") or "location" in asked
        ):
            request["location"] = previous_location

        current_taxonomy = request.get("taxonomy") if isinstance(request.get("taxonomy"), dict) else {}
        previous_taxonomy = previous_request.get("taxonomy") if isinstance(previous_request.get("taxonomy"), dict) else {}
        for slot, key in (("facilities_area", "facilities_area"), ("impacted_service", "impacted_service")):
            value = (self._clean_value(current_taxonomy.get(key)) or "").lower()
            # Keep inferred unknown taxonomy when a concrete problem is already confirmed.
            if value in {"unknown", "unknow"} and not (mentions.get(slot) or slot in asked or problem_confirmed):
                current_taxonomy[key] = previous_taxonomy.get(key)
        request["taxonomy"] = current_taxonomy

    def _auto_mark_stuck_slots_unknown(self, request: Dict[str, Any]) -> None:
        dialog_state = request.get("dialog_state") if isinstance(request.get("dialog_state"), dict) else {}
        slot_attempts = dialog_state.get("slot_attempts") if isinstance(dialog_state.get("slot_attempts"), dict) else {}
        slot_mentioned = dialog_state.get("slot_mentioned") if isinstance(dialog_state.get("slot_mentioned"), dict) else {}

        for slot in ("problem", "location", "facilities_area", "impacted_service", "urgency"):
            # Ask each missing slot at most once. If user's response cannot fill it,
            # mark as unknown and continue the dialog instead of looping.
            if int(slot_attempts.get(slot, 0)) < 1:
                continue
            if not slot_mentioned.get(slot):
                continue
            slot_info = (dialog_state.get("slots") or {}).get(slot, {})
            if slot_info.get("status") == "filled":
                continue

            dialog_state["slots"][slot] = {**slot_info, "status": "unknown", "value": "unknown"}
            if slot == "problem":
                dialog_state["problem"] = {"text": "unknown", "confirmed": True}
            elif slot == "location":
                location = request.get("location") if isinstance(request.get("location"), dict) else {}
                location["free_text"] = "unknown"
                request["location"] = location
            elif slot in {"facilities_area", "impacted_service"}:
                taxonomy = request.get("taxonomy") if isinstance(request.get("taxonomy"), dict) else {}
                taxonomy[slot] = "unknown"
                request["taxonomy"] = taxonomy
            elif slot == "urgency":
                request["urgency"] = "unknown"

    def _is_meaningful_problem_text(self, text: str) -> bool:
        value = self._clean_value(text)
        if not value:
            return False
        return value.lower() not in {"unknown", "unknow"}

    def _is_filled_slot_value(self, value: Any) -> bool:
        cleaned = self._clean_value(value)
        if not cleaned:
            return False
        return cleaned.lower() not in {"unknown", "unknow"}

    def _normalize_urgency(self, urgency: Any) -> str:
        cleaned = (self._clean_value(urgency) or "unknown").lower()
        if cleaned in {"low", "normal", "high", "urgent"}:
            return cleaned
        return "unknown"

    def _history_to_messages(self, history: List[Dict[str, Any]]) -> List[Any]:
        messages: List[Any] = []
        for item in history:
            sender = item.get("sender")
            content = (item.get("content") or "").strip()
            if not content:
                continue
            messages.append(("assistant" if sender == "bot" else "user", content))
        return messages

    def _merge_nested(self, old: Any, new: Any) -> Dict[str, Any]:
        result = copy.deepcopy(old) if isinstance(old, dict) else {}
        if not isinstance(new, dict):
            return result
        for key, value in new.items():
            cleaned = self._clean_value(value)
            if cleaned is not None:
                result[key] = cleaned
        return result

    def _merge_taxonomy_from_delta(self, old: Any, merged_taxonomy: Any, delta_taxonomy: Any) -> Dict[str, Any]:
        result = copy.deepcopy(old) if isinstance(old, dict) else {}
        if not isinstance(merged_taxonomy, dict):
            return result
        if not isinstance(delta_taxonomy, dict):
            return result

        for key in ("facilities_area", "impacted_service", "request_type"):
            delta_value = self._clean_value(delta_taxonomy.get(key))
            if delta_value is None:
                continue
            merged_value = self._clean_value(merged_taxonomy.get(key))
            if merged_value is not None:
                result[key] = merged_value
        return result

    def _clean_value(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            if cleaned.lower() in {"n/a", "na", "none", "null"}:
                return None
            return cleaned
        return str(value)

    def _taxonomy_facility_ids(self, taxonomy: List[Dict[str, Any]]) -> set[str]:
        ids: set[str] = set()
        for area in taxonomy:
            if isinstance(area, dict) and isinstance(area.get("id"), str):
                ids.add(area["id"])
        return ids

    def _taxonomy_service_ids(self, taxonomy: List[Dict[str, Any]]) -> set[str]:
        ids: set[str] = set()
        for area in taxonomy:
            services = area.get("impacted_services") if isinstance(area, dict) else None
            if not isinstance(services, list):
                continue
            for service in services:
                if isinstance(service, dict) and isinstance(service.get("id"), str):
                    ids.add(service["id"])
        return ids

    def _update_summary(self, summary: str, user_text: str) -> str:
        text = (user_text or "").strip()
        if not text:
            return summary
        if not summary:
            return text[:240]
        return f"{summary} | {text}"[-600:]


dialog_agent = DialogAgent()
