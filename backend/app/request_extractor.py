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


class ConfidenceSchema(BaseModel):
    overall: float = 0.0
    urgency: float = 0.0
    location: float = 0.0
    taxonomy: float = 0.0


class RequestItemSchema(BaseModel):
    title: str
    description: str
    urgency: str = "unknown"
    location: LocationSchema = Field(default_factory=LocationSchema)
    taxonomy: TaxonomySchema = Field(default_factory=TaxonomySchema)
    safety_or_access_impact: Optional[bool] = None
    assets: List[Dict[str, Optional[str]]] = Field(default_factory=list)
    missing_required_fields: List[str] = Field(default_factory=list)
    clarifying_questions: List[str] = Field(default_factory=list)
    confidence: ConfidenceSchema = Field(default_factory=ConfidenceSchema)


class RequestsSchema(BaseModel):
    requests: List[RequestItemSchema] = Field(default_factory=list)


SYSTEM_PROMPT_TEMPLATE = """
You are an assistant that extracts facility repair requests from user text.
Return strictly using the provided schema.
Use the taxonomy IDs below for facilities_area, impacted_service, and request_type.
If multiple issues are described, split them into multiple requests.
Only use "unknown" or null when the user explicitly says they don't know.
Taxonomy:
{taxonomy_json}
""".strip()


@lru_cache(maxsize=1)
def _get_llm() -> ChatOpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL")
    if not api_key or not base_url:
        raise RuntimeError(
            "OPENAI_API_KEY and OPENAI_BASE_URL are required for LangGraph request extraction"
        )

    model_name = os.getenv("OPENAI_MODEL", "gpt-5.1-mini")
    return ChatOpenAI(
        api_key=api_key,
        base_url=base_url,
        model=model_name,
        temperature=0,
    )


def extract_requests(message: str, taxonomy: List[Dict[str, Any]]) -> Dict[str, Any]:
    llm = _get_llm()
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        taxonomy_json=json.dumps(taxonomy, ensure_ascii=False)
    )

    structured_llm = llm.with_structured_output(RequestsSchema, method="json_schema")
    output = structured_llm.invoke(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ]
    )

    if isinstance(output, RequestsSchema):
        return output.model_dump()
    if isinstance(output, dict):
        return output
    return {"requests": []}
