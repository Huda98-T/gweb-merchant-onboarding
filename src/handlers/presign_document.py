"""POST /applications/{id}/documents/presign — spec §3 (Phase 2)."""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param, parse_json_body
from common.responses import build_response
from models.documents import PresignDocumentRequest
from services import document_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    request = PresignDocumentRequest.model_validate(parse_json_body(event))
    response = document_service.presign_document(application_id, request)
    return build_response(200, response.model_dump(by_alias=True))
