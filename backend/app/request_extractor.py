from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, List, Optional

from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field


class LocationSchema(BaseModel):
    site: Optional[str] = None
    building: Optional[str] = None
    floor: Optional[str] = None
    room: Optional[str] = None
    free_text: Optional[str] = None


class TaxonomySchema(BaseModel):
    facilities_area: Optional[str] = None
    impacted_service: Optional[str] = None
    request_type: Optional[str] = None


class SlotDeltaSchema(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    urgency: Optional[str] = None
    location: Optional[LocationSchema] = None
    taxonomy: Optional[TaxonomySchema] = None
    safety_or_access_impact: Optional[bool] = None
    assets: Optional[List[Dict[str, Optional[str]]]] = None


class RequestItemSchema(BaseModel):
    title: str
    description: str
    urgency: str = "unknown"
    location: LocationSchema = Field(default_factory=LocationSchema)
    taxonomy: TaxonomySchema = Field(default_factory=TaxonomySchema)
    safety_or_access_impact: Optional[bool] = None
    assets: List[Dict[str, Optional[str]]] = Field(default_factory=list)


SLOT_EXTRACTION_PROMPT = """
Extract slot values from the LATEST user message only.
Rules:
- Return only values explicitly present in the latest message.
- If a slot is not present, return null for that field.
- Do not infer missing location/taxonomy from older context.
- If user explicitly says they don't know, use string "unknown" for that slot.
- Use taxonomy IDs only.
Taxonomy:
{taxonomy_json}
""".strip()


MERGE_PROMPT = """
Merge extracted slot updates into the current request.
Rules:
- Preserve existing values unless extracted slot explicitly updates them.
- If extracted slot value is "unknown", set the merged value to "unknown".
- Keep output consistent and concise.
- Use taxonomy IDs only.
Taxonomy:
{taxonomy_json}
""".strip()


@lru_cache(maxsize=1)
def _get_llm() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError("OPENAI_API_KEY and OPENAI_BASE_URL are required")

    model_name = os.getenv("OPENAI_MODEL", "gpt-5.1-mini")
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0,
    )


def extract_slot_delta(message: str, taxonomy: List[Dict[str, Any]]) -> Dict[str, Any]:
    llm = _get_llm()
    prompt = SLOT_EXTRACTION_PROMPT.format(taxonomy_json=json.dumps(taxonomy, ensure_ascii=False))

    structured_llm = llm.with_structured_output(SlotDeltaSchema, method="function_calling")
    output = structured_llm.invoke(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": message},
        ]
    )

    if isinstance(output, SlotDeltaSchema):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return {}


def merge_request_with_delta(
    current_request: Dict[str, Any],
    slot_delta: Dict[str, Any],
    taxonomy: List[Dict[str, Any]],
) -> Dict[str, Any]:
    llm = _get_llm()
    prompt = MERGE_PROMPT.format(taxonomy_json=json.dumps(taxonomy, ensure_ascii=False))

    structured_llm = llm.with_structured_output(RequestItemSchema, method="function_calling")
    output = structured_llm.invoke(
        [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "current_request": {
                            "title": current_request.get("title"),
                            "description": current_request.get("description"),
                            "urgency": current_request.get("urgency"),
                            "location": current_request.get("location"),
                            "taxonomy": current_request.get("taxonomy"),
                            "safety_or_access_impact": current_request.get("safety_or_access_impact"),
                            "assets": current_request.get("assets", []),
                        },
                        "slot_delta": slot_delta,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
    )

    if isinstance(output, RequestItemSchema):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return {
        "title": current_request.get("title") or "",
        "description": current_request.get("description") or "",
        "urgency": current_request.get("urgency") or "unknown",
        "location": current_request.get("location") or {},
        "taxonomy": current_request.get("taxonomy") or {},
        "safety_or_access_impact": current_request.get("safety_or_access_impact"),
        "assets": current_request.get("assets", []),
    }
