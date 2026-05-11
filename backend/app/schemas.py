from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UserContext(BaseModel):
    name: Optional[str] = None
    role: Optional[str] = None


class IntakeRequest(BaseModel):
    message_id: str
    thread_id: Optional[str] = None
    tenant_id: str
    branch_id: str
    reporter_email: Optional[str] = None
    channel: str = "chatbot"
    message_text: str
    user_context: Optional[UserContext] = None
    received_at: Optional[str] = None


class ClarifyRequest(BaseModel):
    additional_text: Optional[str] = None
    answers: Dict[str, Any] = Field(default_factory=dict)


class AnalyticsSchemaUpdate(BaseModel):
    tenant_id: str
    fields: List[Dict[str, Any]]


class TaxonomyUpdate(BaseModel):
    facilities_areas: List[Dict[str, Any]]


class AdminRequestUpdate(BaseModel):
    reporter_email: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    urgency: Optional[str] = None
    status: Optional[str] = None
    location: Optional[Dict[str, Any]] = None
    taxonomy: Optional[Dict[str, Any]] = None
