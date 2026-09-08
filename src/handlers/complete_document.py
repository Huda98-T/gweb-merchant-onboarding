"""POST /applications/{id}/documents/{documentId}/complete — spec §3 (Phase 2).

Verifies the uploaded object server-side (size, checksum, signature) and
finishes at ACCEPTED or REJECTED — both returned as 200 (see plan §3:
REJECTED is a successful verification outcome, not a request error).
"""

from __future__ import annotations

from typing import Any

from common.auth import require_application_token
from common.errors import handle_errors
from common.events import get_path_param, parse_json_body
from common.responses import build_response
from models.documents import CompleteDocumentRequest
from services import document_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    application_id = get_path_param(event, "id")
    require_application_token(event, application_id)
    document_id = get_path_param(event, "documentId")
    request = CompleteDocumentRequest.model_validate(parse_json_body(event))
    response = document_service.complete_document(application_id, document_id, request, context)
    return build_response(200, response.model_dump(by_alias=True, exclude_none=True))
