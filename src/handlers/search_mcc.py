"""GET /mcc?query= — spec §3. Not application-scoped: no auth (global
reference data), no {id} path parameter."""

from __future__ import annotations

from typing import Any

from common.errors import handle_errors
from common.events import get_query_param
from common.responses import build_response
from models.mcc import SearchMccResponse
from services import mcc_catalog_service


@handle_errors
def handler(event: dict, context: Any) -> dict:
    query = get_query_param(event, "query")
    results = mcc_catalog_service.search(query)
    return build_response(200, SearchMccResponse(results=results).model_dump(by_alias=True))
