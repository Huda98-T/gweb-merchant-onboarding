"""POST /applications/{id}/mcc/confirm — decision #1: a separate
confirmation endpoint (not in the original spec §3 table), justified
because the assessment requires applicant confirmation/correction of the
system's MCC proposal. Kept as its own DynamoDB item (MCC#CONFIRMED,
distinct from MCC#PROPOSED) so the audit trail shows both."""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param, parse_json_body
from common.responses import build_response
from models.mcc import ConfirmMccRequest
from services import mcc_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    request = ConfirmMccRequest.model_validate(parse_json_body(event))
    response = mcc_service.confirm_mcc(application_id, request)
    return build_response(200, response.model_dump(by_alias=True))
