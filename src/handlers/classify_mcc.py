"""POST /applications/{id}/classify — spec §3. Deterministic classification
only (decision #2) — see classification_service.py."""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param, parse_json_body
from common.responses import build_response
from models.mcc import ClassifyRequest
from services import mcc_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    request = ClassifyRequest.model_validate(parse_json_body(event))
    response = mcc_service.classify_application(application_id, request)
    return build_response(200, response.model_dump(by_alias=True))
