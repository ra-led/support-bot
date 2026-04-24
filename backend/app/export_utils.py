import io
from typing import Any, Dict, List

from openpyxl import Workbook

from .request_utils import flatten_request_for_export

EXPORT_COLUMNS = [
    "request_id",
    "created_at",
    "updated_at",
    "tenant_id",
    "branch_id",
    "source_message_id",
    "reporter_email",
    "title",
    "description",
    "urgency",
    "status",
    "safety_or_access_impact",
    "location_site",
    "location_building",
    "location_floor",
    "location_room",
    "location_free_text",
    "taxonomy_facilities_area",
    "taxonomy_impacted_service",
    "taxonomy_request_type",
    "missing_required_fields",
    "clarifying_questions",
    "assets",
    "confidence_overall",
    "confidence_urgency",
    "confidence_location",
    "confidence_taxonomy",
]


def build_issues_export_file(requests: List[Dict[str, Any]]) -> bytes:
    rows = [flatten_request_for_export(request) for request in requests]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "issues"
    sheet.append(EXPORT_COLUMNS)
    for row in rows:
        sheet.append([row.get(column, "") for column in EXPORT_COLUMNS])

    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return output.getvalue()
