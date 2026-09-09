"""POST /applications/{id}/submit — spec §3. 200 on success (or if already
SUBMITTED — idempotent), 400 with missingItems if blocked."""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param, parse_json_body
from common.responses import build_response
from models.items import ApplicationStatus
from models.review import SubmitRequest
from services import submit_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    request = SubmitRequest.model_validate(parse_json_body(event))
    response = submit_service.submit_application(application_id, request)
    status_code = 200 if response.status == ApplicationStatus.SUBMITTED else 400
    return build_response(status_code, response.model_dump(by_alias=True, exclude_none=True))
