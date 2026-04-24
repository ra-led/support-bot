from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, TypedDict

from langgraph.graph import END, START, MessagesState, StateGraph

from .request_extractor import extract_requests


DialogPhase = Literal["collect", "confirm_problem", "targeted_clarify", "ready"]


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
    """State-machine agent for intake clarification with anti-stall behavior."""

    def __init__(self) -> None:
        graph = StateGraph(GraphState)
        graph.add_node("bootstrap", self._bootstrap)
        graph.add_node("extract_delta", self._extract_delta)
        graph.add_node("merge_delta", self._merge_delta)
        graph.add_node("plan", self._plan)
        graph.add_node("ask", self._ask)
        graph.add_node("ready", self._ready)

        graph.add_edge(START, "bootstrap")
        graph.add_edge("bootstrap", "extract_delta")
        graph.add_edge("extract_delta", "merge_delta")
        graph.add_edge("merge_delta", "plan")
        graph.add_conditional_edges(
            "plan",
            self._route_after_plan,
            {
                "ask": "ask",
                "ready": "ready",
            },
        )
        graph.add_edge("ask", END)
        graph.add_edge("ready", END)

        self.graph = graph.compile()

    def run_turn(
        self,
        request: Dict[str, Any],
        history: List[Dict[str, Any]],
        user_text: str,
        taxonomy: List[Dict[str, Any]],
    ) -> AgentResult:
        messages = self._history_to_messages(history)
        initial_state: GraphState = {
            "request": copy.deepcopy(request),
            "messages": messages,
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
        dialog_state = request.get("dialog_state")
        if not isinstance(dialog_state, dict):
            dialog_state = {}

        dialog_state.setdefault("phase", "collect")
        dialog_state.setdefault("problem", {"text": "", "confirmed": False})
        dialog_state.setdefault("facility", "unknown")
        dialog_state.setdefault("slots", {})
        dialog_state.setdefault("slot_attempts", {})
        dialog_state.setdefault("last_asked_slots", [])
        dialog_state.setdefault("clarify_attempts", 0)
        dialog_state.setdefault("ask_budget", 2)
        dialog_state.setdefault("rolling_summary", "")
        request["dialog_state"] = dialog_state

        return {"request": request}

    def _extract_delta(self, state: GraphState) -> GraphState:
        history_text = self._build_history_text(state["messages"])
        existing = state["request"]
        current_description = (existing.get("description") or "").strip()

        prompt = (
            "Extract/update a single facility request draft from this context. "
            "Keep known values if user did not replace them.\n"
            f"Current description: {current_description}\n"
            f"Conversation:\n{history_text}\n"
            f"Latest user message:\n{state['user_text']}"
        )

        extraction = extract_requests(prompt, taxonomy=state["taxonomy"])
        first = {}
        if isinstance(extraction, dict):
            requests = extraction.get("requests")
            if isinstance(requests, list) and requests:
                first = requests[0] if isinstance(requests[0], dict) else {}

        return {"extraction": first}

    def _merge_delta(self, state: GraphState) -> GraphState:
        request = state["request"]
        extraction = state.get("extraction") or {}
        dialog_state = request["dialog_state"]

        self._merge_simple_field(request, extraction, "title")
        self._merge_simple_field(request, extraction, "description")
        self._merge_simple_field(request, extraction, "urgency")

        request["location"] = self._merge_nested(
            request.get("location"),
            extraction.get("location"),
        )
        request["taxonomy"] = self._merge_nested(
            request.get("taxonomy"),
            extraction.get("taxonomy"),
        )

        candidate_problem = (request.get("description") or request.get("title") or "").strip()
        if self._is_meaningful_problem_text(candidate_problem):
            dialog_state["problem"]["text"] = candidate_problem

        if self._is_meaningful_problem_text(dialog_state["problem"].get("text") or ""):
            dialog_state["problem"]["confirmed"] = True
            if dialog_state.get("phase") == "collect":
                dialog_state["phase"] = "confirm_problem"
        else:
            dialog_state["problem"]["confirmed"] = False

        taxonomy = request.get("taxonomy") or {}
        facilities_area = self._clean_value(taxonomy.get("facilities_area"))
        impacted_service = self._clean_value(taxonomy.get("impacted_service"))

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
            **taxonomy,
            "facilities_area": facilities_area,
            "impacted_service": impacted_service,
            "request_type": self._clean_value(taxonomy.get("request_type")),
        }

        dialog_state["facility"] = facilities_area or "unknown"

        location = request.get("location") or {}
        has_location_detail = any(
            self._clean_value(location.get(field)) for field in ("building", "floor", "room", "free_text")
        )

        slots = dialog_state["slots"]
        slots["problem"] = {
            "value": dialog_state["problem"].get("text") or "",
            "status": "filled" if dialog_state["problem"].get("text") else "empty",
        }
        slots["location"] = {
            "value": json.dumps(location, ensure_ascii=False),
            "status": "filled" if has_location_detail else slots.get("location", {}).get("status", "empty"),
        }
        slots["facilities_area"] = {
            "value": facilities_area or "",
            "status": "filled" if facilities_area else slots.get("facilities_area", {}).get("status", "empty"),
        }
        slots["impacted_service"] = {
            "value": impacted_service or "",
            "status": "filled" if impacted_service else slots.get("impacted_service", {}).get("status", "empty"),
        }

        self._mark_cant_provide_from_text(dialog_state, state["user_text"])

        dialog_state["rolling_summary"] = self._update_summary(
            dialog_state.get("rolling_summary") or "",
            state["user_text"],
        )

        request["dialog_state"] = dialog_state
        return {"request": request}

    def _plan(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]
        ask_budget = int(dialog_state.get("ask_budget", 2))

        missing = self._collect_missing_critical_slots(request)
        slot_attempts: Dict[str, int] = dialog_state.get("slot_attempts", {})

        filtered_missing: List[str] = []
        for slot in missing:
            slot_status = dialog_state["slots"].get(slot, {}).get("status")
            if slot_status in {"cant_provide", "unknown", "na"}:
                continue
            if slot_attempts.get(slot, 0) >= 2:
                dialog_state["slots"][slot] = {
                    **dialog_state["slots"].get(slot, {}),
                    "status": "cant_provide",
                }
                continue
            filtered_missing.append(slot)

        if not dialog_state["problem"].get("confirmed"):
            dialog_state["phase"] = "confirm_problem"
            request["dialog_state"] = dialog_state
            message = (
                "Хочу убедиться, что правильно понял проблему. "
                "Опишите, пожалуйста, что именно сломано/что нужно исправить."
            )
            if dialog_state.get("clarify_attempts", 0) >= ask_budget:
                message = (
                    "Пока не вижу описания самой проблемы. "
                    "Без этого не смогу оформить заявку. "
                    "Напишите одной фразой, что именно не работает."
                )
            return {
                "request": request,
                "next_step": "ask",
                "working": {
                    "ask_slots": ["problem"],
                    "message": message,
                },
            }

        if filtered_missing and dialog_state.get("clarify_attempts", 0) < ask_budget:
            ask_slots = filtered_missing[:2]
            dialog_state["phase"] = "targeted_clarify"
            next_step = "ask"
            working = {"ask_slots": ask_slots}
        else:
            dialog_state["phase"] = "ready"
            next_step = "ready"
            working = {}

        request["dialog_state"] = dialog_state
        return {"request": request, "next_step": next_step, "working": working}

    def _route_after_plan(self, state: GraphState) -> str:
        return state.get("next_step", "ready")

    def _ask(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]
        ask_slots = state.get("working", {}).get("ask_slots", [])

        message = state.get("working", {}).get("message")
        if not message:
            parts: List[str] = []
            if "location" in ask_slots:
                parts.append("уточните локацию (здание/этаж/комната или ориентир)")
            if "facilities_area" in ask_slots:
                parts.append("уточните тип проблемы (например: электрика, сантехника, доступ)")
            if "impacted_service" in ask_slots:
                parts.append("уточните, что именно затронуто (например: дверь, туалет, кондиционер)")
            if "problem" in ask_slots:
                parts.append("опишите саму проблему")

            if parts:
                message = "Чтобы не ошибиться, " + "; ".join(parts) + ". Если не знаете, так и напишите: 'не знаю'."
            else:
                message = "Уточните, пожалуйста, детали проблемы."

        for slot in ask_slots:
            dialog_state["slot_attempts"][slot] = dialog_state["slot_attempts"].get(slot, 0) + 1
        dialog_state["clarify_attempts"] = int(dialog_state.get("clarify_attempts", 0)) + 1
        dialog_state["last_asked_slots"] = ask_slots

        request["clarifying_questions"] = [message]
        request["missing_required_fields"] = self._collect_missing_critical_slots(request)
        request["status"] = "needs_clarification"
        request["dialog_state"] = dialog_state

        return {"request": request}

    def _ready(self, state: GraphState) -> GraphState:
        request = state["request"]
        dialog_state = request["dialog_state"]

        missing = self._collect_missing_critical_slots(request)
        unresolved = []
        for slot in missing:
            slot_status = dialog_state["slots"].get(slot, {}).get("status")
            if slot_status not in {"cant_provide", "unknown", "na"}:
                unresolved.append(slot)

        if unresolved:
            request["status"] = "needs_clarification"
            request["missing_required_fields"] = unresolved
            request["clarifying_questions"] = [
                "Нужны еще уточнения, чтобы корректно отправить заявку."
            ]
            return {"request": request}

        request["missing_required_fields"] = []
        request["clarifying_questions"] = []
        request["status"] = "ready"
        request["dialog_state"] = dialog_state
        return {"request": request}

    def _collect_missing_critical_slots(self, request: Dict[str, Any]) -> List[str]:
        missing: List[str] = []

        dialog_state = request.get("dialog_state") or {}
        problem_text = ((dialog_state.get("problem") or {}).get("text") or "").strip()
        if not self._is_meaningful_problem_text(problem_text):
            missing.append("problem")

        location = request.get("location") or {}
        has_location_detail = self._has_specific_location_detail(location)
        if not has_location_detail:
            missing.append("location")

        taxonomy = request.get("taxonomy") or {}
        facilities_area = self._clean_value(taxonomy.get("facilities_area"))
        impacted_service = self._clean_value(taxonomy.get("impacted_service"))

        if not self._is_filled_slot_value(taxonomy.get("facilities_area"), facilities_area):
            missing.append("facilities_area")
        if not self._is_filled_slot_value(taxonomy.get("impacted_service"), impacted_service):
            missing.append("impacted_service")

        return missing

    def _is_filled_slot_value(self, raw_value: Any, cleaned_value: Optional[str]) -> bool:
        if cleaned_value:
            return True
        if not isinstance(raw_value, str):
            return False
        return bool(raw_value.strip())

    def _build_history_text(self, messages: List[Any]) -> str:
        chunks: List[str] = []
        for item in messages[-12:]:
            sender = getattr(item, "type", "user")
            content = str(getattr(item, "content", "")).strip()
            if not content:
                continue
            chunks.append(f"{sender}: {content}")
        return "\n".join(chunks)

    def _history_to_messages(self, history: List[Dict[str, Any]]) -> List[Any]:
        messages: List[Any] = []
        for item in history:
            sender = item.get("sender")
            content = (item.get("content") or "").strip()
            if not content:
                continue
            if sender == "bot":
                messages.append(("assistant", content))
            else:
                messages.append(("user", content))
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

    def _merge_simple_field(self, target: Dict[str, Any], source: Dict[str, Any], key: str) -> None:
        cleaned = self._clean_value(source.get(key))
        if cleaned is not None:
            target[key] = cleaned

    def _clean_value(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return None
            if cleaned.lower() in {"unknown", "n/a", "na", "none", "null"}:
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

    def _mark_cant_provide_from_text(self, dialog_state: Dict[str, Any], user_text: str) -> None:
        if not user_text:
            return
        lowered = user_text.lower()
        markers = (
            "не знаю",
            "не могу уточнить",
            "нет данных",
            "don't know",
            "can't provide",
            "not sure",
        )
        if not any(marker in lowered for marker in markers):
            return

        for slot in dialog_state.get("last_asked_slots", []):
            slot_info = dialog_state["slots"].get(slot, {})
            if slot_info.get("status") != "filled":
                dialog_state["slots"][slot] = {**slot_info, "status": "cant_provide"}

    def _update_summary(self, summary: str, user_text: str) -> str:
        user_text = user_text.strip()
        if not user_text:
            return summary
        if not summary:
            return user_text[:240]
        combined = f"{summary} | {user_text}"
        return combined[-600:]

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
        return bool(free_text and not self._is_generic_location_text(free_text))

    def _is_generic_location_text(self, value: str) -> bool:
        generic_markers = (
            "all rooms",
            "all room",
            "all areas",
            "every room",
            "все комнаты",
            "во всех комнатах",
            "везде",
        )
        normalized = " ".join((value or "").split())
        return normalized in generic_markers

    def _is_meaningful_problem_text(self, text: str) -> bool:
        normalized = " ".join((text or "").lower().split())
        if len(normalized) < 8:
            return False

        generic = {
            "facility request",
            "facility request draft",
            "new facility request",
            "general issue",
            "issue",
            "problem",
            "request",
            "hello",
            "hi",
            "hey",
            "привет",
            "здравствуйте",
        }
        if normalized in generic:
            return False
        if normalized.startswith("facility request"):
            return False
        return True


dialog_agent = DialogAgent()
