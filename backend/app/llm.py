import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI

SYSTEM_PROMPT = """
You are an assistant that extracts facility repair requests from user text.
Return STRICT JSON only. Do not include markdown.
Schema:
{
  "requests": [
    {
      "title": "string",
      "description": "string",
      "urgency": "low|normal|high|urgent|unknown",
      "location": {
        "site": "string|null",
        "building": "string|null",
        "floor": "string|null",
        "room": "string|null",
        "free_text": "string|null"
      },
      "taxonomy": {
        "facilities_area": "string|null",
        "impacted_service": "string|null",
        "request_type": "string|null"
      },
      "safety_or_access_impact": "boolean|null",
      "assets": [
        {"type": "string", "identifier": "string|null", "notes": "string|null"}
      ],
      "missing_required_fields": ["string"],
      "clarifying_questions": ["string"],
      "confidence": {
        "overall": 0.0,
        "urgency": 0.0,
        "location": 0.0,
        "taxonomy": 0.0
      }
    }
  ]
}
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
        urgency = "urgent" if re.search(r"urgent|asap|now", message, re.I) else "normal"
        location_match = re.search(r"\b([A-Z]\d{1,3}|\d{3})\b", message)
        location = location_match.group(1) if location_match else None
        request = {
            "title": message[:80].strip() or "Facility request",
            "description": message.strip(),
            "urgency": urgency,
            "location": {
                "site": None,
                "building": None,
                "floor": None,
                "room": location,
                "free_text": None,
            },
            "taxonomy": {
                "facilities_area": None,
                "impacted_service": None,
                "request_type": None,
            },
            "safety_or_access_impact": None,
            "assets": [],
            "missing_required_fields": [
                field
                for field in ["facilities_area", "impacted_service"]
                if field
            ],
            "clarifying_questions": [
                "Which facilities area does this relate to?",
                "What service is impacted (e.g., lighting, plumbing, doors)?",
            ],
            "confidence": {
                "overall": 0.3,
                "urgency": 0.6,
                "location": 0.4,
                "taxonomy": 0.1,
            },
        }
        return {"requests": [request]}


llm_client = LLMClient()
