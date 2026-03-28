import json
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .storage import storage

TAXONOMY_JSON = json.dumps(storage.get_taxonomy(), ensure_ascii=False)

SYSTEM_PROMPT = f"""
You are an assistant that extracts facility repair requests from user text.
Return STRICT JSON only. Do not include markdown.
Use the taxonomy IDs below for facilities_area, impacted_service, and request_type.
If multiple issues are described, split them into multiple requests.
Only use "unknown" or null when the user explicitly says they don't know.
Schema:
{{
  "requests": [
    {{
      "title": "string",
      "description": "string",
      "urgency": "low|normal|high|urgent|unknown",
      "location": {{
        "site": "string|null",
        "building": "string|null",
        "floor": "string|null",
        "room": "string|null",
        "free_text": "string|null"
      }},
      "taxonomy": {{
        "facilities_area": "string|null",
        "impacted_service": "string|null",
        "request_type": "string|null"
      }},
      "safety_or_access_impact": "boolean|null",
      "assets": [
        {{"type": "string", "identifier": "string|null", "notes": "string|null"}}
      ],
      "missing_required_fields": ["string"],
      "clarifying_questions": ["string"],
      "confidence": {{
        "overall": 0.0,
        "urgency": 0.0,
        "location": 0.0,
        "taxonomy": 0.0
      }}
    }}
  ]
}}
Taxonomy:
{TAXONOMY_JSON}
""".strip()


class LLMClient:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.proxyapi.ru/openai/v1")
        self.enabled = bool(api_key)
        if self.enabled:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = None

    def extract_requests(self, message: str) -> Dict[str, Any]:
        if not self.enabled:
            return self._fallback_extract(message)

        response = self.client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-5.1-mini"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
        )
        content = response.choices[0].message.content
        return self._safe_parse(content)

    def _safe_parse(self, content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return self._fallback_extract(content)

    def _fallback_extract(self, message: str) -> Dict[str, Any]:
        issues = self._split_issues(message)
        location = self._extract_location(message)
        requests = []
        for issue in issues:
            taxonomy = self._infer_taxonomy(issue)
            urgency = self._infer_urgency(issue, message)
            safety = self._infer_safety_access(issue)
            requests.append(
                {
                    "title": issue[:80].strip() or "Facility request",
                    "description": issue.strip(),
                    "urgency": urgency,
                    "location": location,
                    "taxonomy": taxonomy,
                    "safety_or_access_impact": safety,
                    "assets": self._extract_assets(issue),
                    "missing_required_fields": [],
                    "clarifying_questions": [],
                    "confidence": {
                        "overall": 0.35,
                        "urgency": 0.6,
                        "location": 0.5,
                        "taxonomy": 0.25,
                    },
                }
            )
        return {"requests": requests}

    def _split_issues(self, message: str) -> List[str]:
        if re.search(r"\btoilet\b", message, re.I) and re.search(
            r"\b(dispenser|paper dispenser|soap dispenser)\b", message, re.I
        ):
            toilet_issue = "Blocked toilet" if re.search(r"\bblock", message, re.I) else "Toilet issue"
            dispenser_issue = "Dispenser loose / reattach"
            return [toilet_issue, dispenser_issue]
        parts = [part.strip() for part in re.split(r"\.\s+|\n", message) if part.strip()]
        return parts or [message]

    def _extract_location(self, message: str) -> Dict[str, Optional[str]]:
        floor = None
        room = None
        free_text_parts: List[str] = []
        level_match = re.search(r"\bL(\d{1,2})\b", message, re.I)
        if level_match:
            floor = f"L{level_match.group(1)}"
        else:
            level_match = re.search(r"\bLevel\s+(\d{1,2})\b", message, re.I)
            if level_match:
                floor = f"Level {level_match.group(1)}"

        room_match = re.search(r"\b(G\d{1,3}|Room\s*\d{1,4})\b", message, re.I)
        if room_match:
            room = room_match.group(1)

        if re.search(r"\bfront door\b|\bmain entrance\b", message, re.I):
            free_text_parts.append("front door / main entrance")
        if re.search(r"\bfemale toilet\b|\bwomen'?s toilet\b", message, re.I):
            free_text_parts.append("female toilet")
        if re.search(r"\bclinic\b", message, re.I):
            free_text_parts.append("clinic")

        free_text = ", ".join(free_text_parts) if free_text_parts else None
        return {
            "site": None,
            "building": None,
            "floor": floor,
            "room": room,
            "free_text": free_text,
        }

    def _infer_taxonomy(self, text: str) -> Dict[str, Optional[str]]:
        if re.search(r"people trapped|locked in|locked out|lock[-\s]?in", text, re.I):
            return {
                "facilities_area": "safety_emergency",
                "impacted_service": "safety_emergency.immediate_hazard",
                "request_type": "safety_emergency.immediate_hazard.people_trapped",
            }
        if re.search(r"access card|staff id|badge", text, re.I):
            return {
                "facilities_area": "access_security",
                "impacted_service": "access_security.access_cards",
                "request_type": "access_security.access_cards.no_access",
            }
        if re.search(r"front door|door.*jammed|door jammed", text, re.I):
            return {
                "facilities_area": "access_security",
                "impacted_service": "access_security.doors",
                "request_type": "access_security.doors.jammed",
            }
        if re.search(r"toilet", text, re.I):
            request_type = (
                "plumbing.toilets.blocked" if re.search(r"block", text, re.I) else "plumbing.toilets.other"
            )
            return {
                "facilities_area": "plumbing",
                "impacted_service": "plumbing.toilets",
                "request_type": request_type,
            }
        if re.search(r"dispenser|paper towel|soap", text, re.I):
            return {
                "facilities_area": "carpentry_interiors",
                "impacted_service": "carpentry_interiors.bathroom_accessories",
                "request_type": "carpentry_interiors.bathroom_accessories.dispenser_loose",
            }
        return {
            "facilities_area": None,
            "impacted_service": None,
            "request_type": None,
        }

    def _infer_urgency(self, text: str, message: str) -> str:
        if re.search(r"people trapped|locked in|locked out", text, re.I):
            return "urgent"
        if re.search(r"urgent|asap|now", message, re.I):
            return "urgent"
        if re.search(r"can(?:not|'t) get in|blocked access|door jammed", text, re.I):
            return "high"
        return "normal"

    def _infer_safety_access(self, text: str) -> Optional[bool]:
        if re.search(r"people trapped|locked in|locked out", text, re.I):
            return True
        if re.search(r"can(?:not|'t) get in|access card|restricted areas", text, re.I):
            return True
        return None

    def _extract_assets(self, text: str) -> List[Dict[str, Optional[str]]]:
        assets: List[Dict[str, Optional[str]]] = []
        id_match = re.search(r"\b(?:ID|staff ID)\s*(\d{4,10})\b", text, re.I)
        if id_match:
            assets.append(
                {"type": "staff_id_card", "identifier": id_match.group(1), "notes": None}
            )
        return assets


llm_client = LLMClient()
