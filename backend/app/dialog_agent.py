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

        if self._delta_has_values(extraction):
            merged = merge_request_with_delta(request, extraction, state["taxonomy"])
            self._apply_merged_fields(request, merged)

        request["urgency"] = self._sanitize_urgency(request.get("urgency"), user_text)

        candidate_problem = (request.get("description") or request.get("title") or "").strip()
        if (
            not self._is_meaningful_problem_text(candidate_problem)
            and self._should_take_user_text_as_problem(dialog_state, request, user_text)
        ):
            candidate_problem = user_text
            request["description"] = user_text

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

        has_urgency = self._has_explicit_urgency_marker(user_text)
        slots["urgency"] = {
            "value": request.get("urgency") or "unknown",
            "status": self._slot_status(has_urgency, slots.get("urgency", {}).get("status")),
        }

        self._mark_unknown_from_text(dialog_state, request, user_text)
        dialog_state["rolling_summary"] = self._update_summary(dialog_state.get("rolling_summary") or "", user_text)
        request["dialog_state"] = dialog_state
        return {"request": request}

    def _plan(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]

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

    def _apply_merged_fields(self, request: Dict[str, Any], merged: Dict[str, Any]) -> None:
        for key in ("title", "description", "urgency", "safety_or_access_impact"):
            cleaned = self._clean_value(merged.get(key)) if key != "safety_or_access_impact" else merged.get(key)
            if cleaned is not None:
                request[key] = cleaned

        request["location"] = self._merge_nested(request.get("location"), merged.get("location"))
        request["taxonomy"] = self._merge_nested(request.get("taxonomy"), merged.get("taxonomy"))

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
            return "Насколько срочно это нужно решить? (low/normal/high/urgent). Если не знаете — напишите 'не знаю'."
        return "Уточните, пожалуйста, детали."

    def _slot_status(self, is_filled: bool, previous_status: Optional[str]) -> str:
        if previous_status == "unknown":
            return "unknown"
        return "filled" if is_filled else "empty"

    def _mark_unknown_from_text(self, dialog_state: Dict[str, Any], request: Dict[str, Any], user_text: str) -> None:
        lowered = (user_text or "").lower()
        if not lowered:
            return
        markers = ("не знаю", "не могу уточнить", "нет данных", "don't know", "can't provide", "not sure")
        if not any(marker in lowered for marker in markers):
            return

        for slot in dialog_state.get("last_asked_slots", []):
            slot_info = (dialog_state.get("slots") or {}).get(slot, {})
            if slot_info.get("status") == "filled":
                continue
            dialog_state["slots"][slot] = {**slot_info, "status": "unknown", "value": "unknown"}
            if slot == "problem":
                dialog_state["problem"]["text"] = "unknown"
                dialog_state["problem"]["confirmed"] = True
            elif slot == "location":
                location = request.get("location") if isinstance(request.get("location"), dict) else {}
                location["free_text"] = "unknown"
                request["location"] = location
            elif slot == "facilities_area":
                taxonomy = request.get("taxonomy") if isinstance(request.get("taxonomy"), dict) else {}
                taxonomy["facilities_area"] = "unknown"
                request["taxonomy"] = taxonomy
            elif slot == "impacted_service":
                taxonomy = request.get("taxonomy") if isinstance(request.get("taxonomy"), dict) else {}
                taxonomy["impacted_service"] = "unknown"
                request["taxonomy"] = taxonomy
            elif slot == "urgency":
                request["urgency"] = "unknown"

    def _has_specific_location_detail(self, location: Dict[str, Any]) -> bool:
        building = (self._clean_value(location.get("building")) or "").lower()
        if building and not self._is_generic_location_text(building):
            return True
        floor = (self._clean_value(location.get("floor")) or "").lower()
        if floor and not self._is_generic_location_text(floor):
            return True
        room = (self._clean_value(location.get("room")) or "").lower()
        if room and not self._is_generic_location_text(room):
            return True
        free_text = (self._clean_value(location.get("free_text")) or "").lower()
        return bool(free_text and not self._is_generic_location_text(free_text) and self._is_specific_location_phrase(free_text))

    def _is_generic_location_text(self, value: str) -> bool:
        generic_markers = ("all rooms", "all room", "all areas", "every room", "все комнаты", "во всех комнатах", "везде")
        normalized = " ".join((value or "").split())
        return normalized in generic_markers

    def _is_specific_location_phrase(self, text: str) -> bool:
        cues = (
            "room", "cabinet", "floor", "level", "building", "block", "branch", "site", "wing", "corridor",
            "reception", "lobby", "entrance", "toilet", "bathroom", "kitchen", "warehouse", "office",
            "кабинет", "этаж", "здание", "корпус", "офис", "склад", "ресепшн", "вход", "туалет", "кухня", "коридор",
        )
        return any(cue in text for cue in cues)

    def _sanitize_urgency(self, urgency: Any, user_text: str) -> str:
        normalized = (self._clean_value(urgency) or "unknown").lower()
        if normalized in {"low", "normal", "high", "urgent"}:
            return normalized

        lowered = (user_text or "").lower()
        normal_markers = ("normal", "standard", "usual", "обычно", "обычный", "стандартно", "нормально")
        low_markers = ("not urgent", "can wait", "whenever possible", "не срочно", "может подождать")
        urgent_markers = ("asap", "immediately", "right now", "emergency", "hazard", "срочно", "авария", "немедленно")
        high_markers = ("high priority", "priority", "important", "важно", "приоритет")

        if any(m in lowered for m in high_markers):
            return "high"
        if any(m in lowered for m in normal_markers):
            return "normal"
        if any(m in lowered for m in low_markers):
            return "low"
        if "urgent" in lowered and "not urgent" not in lowered:
            return "urgent"
        if any(m in lowered for m in urgent_markers):
            return "urgent"
        return "unknown"

    def _has_explicit_urgency_marker(self, user_text: str) -> bool:
        return self._sanitize_urgency(None, user_text) in {"low", "normal", "high", "urgent"}

    def _should_take_user_text_as_problem(self, dialog_state: Dict[str, Any], request: Dict[str, Any], user_text: str) -> bool:
        if not self._is_meaningful_problem_text(user_text):
            return False
        lowered = user_text.lower()
        unknown_markers = ("не знаю", "не могу уточнить", "нет данных", "don't know", "can't provide", "not sure")
        if any(marker in lowered for marker in unknown_markers):
            return False

        last_asked = dialog_state.get("last_asked_slots", [])
        if isinstance(last_asked, list) and "problem" in last_asked:
            return True

        problem_text = ((dialog_state.get("problem") or {}).get("text") or "").strip()
        if self._is_meaningful_problem_text(problem_text):
            return False
        if self._has_specific_location_detail(request.get("location") or {}):
            return False
        if self._has_explicit_urgency_marker(user_text):
            return False
        return True

    def _is_meaningful_problem_text(self, text: str) -> bool:
        normalized = " ".join((text or "").lower().split())
        if len(normalized) < 8:
            return False
        generic = {
            "facility request", "facility request draft", "new facility request", "general issue",
            "issue", "problem", "request", "hello", "hi", "hey", "привет", "здравствуйте",
        }
        if normalized in generic:
            return False
        if normalized.startswith("facility request"):
            return False
        return True

    def _is_filled_slot_value(self, value: Any) -> bool:
        cleaned = self._clean_value(value)
        if cleaned:
            return True
        return isinstance(value, str) and bool(value.strip())

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
