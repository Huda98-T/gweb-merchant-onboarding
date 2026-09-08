"""POST /applications — spec §3. No auth/idempotency (create is exempt)."""

from __future__ import annotations

from typing import Any

from common.errors import handle_errors
from common.responses import build_response
from services import application_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    response = application_service.create_application()
    return build_response(201, response.model_dump(by_alias=True))
