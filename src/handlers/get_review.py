"""GET /applications/{id}/review — justified extension (decision pattern
from Phase 3's mcc/confirm): lets the applicant see readiness/blocking
issues before calling POST /submit, read-only."""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param
from common.responses import build_response
from services import review_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    response = review_service.build_review(application_id)
    return build_response(200, response.model_dump(by_alias=True, exclude_none=True))
