"""POST /applications/{id}/evaluate — spec §3. 202+PROCESSING if the
remaining Lambda budget is too low to safely attempt the AI call, else
200+COMPLETE (or 504 if the call itself hangs past budget)."""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param, parse_json_body
from common.responses import build_response
from models.evaluation import EvaluateRequest, EvaluationStatus
from services import evaluation_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    request = EvaluateRequest.model_validate(parse_json_body(event))
    response = evaluation_service.evaluate_application(application_id, request, context)
    status_code = 202 if response.status == EvaluationStatus.PROCESSING else 200
    return build_response(status_code, response.model_dump(by_alias=True, exclude_none=True))
