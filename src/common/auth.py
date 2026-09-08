"""Ownership check — see spec §3 and the "no real auth" assumption (§1.2 / §5.2).

Not real authentication: every route but `POST /applications` requires the
`X-Application-Token` header to equal the `{id}` path parameter. Anyone who
has the applicationId can access it; that's a documented, accepted gap for
this prototype, not a security boundary.
"""

from __future__ import annotations

from common.errors import UnauthorizedError

TOKEN_HEADER = "x-application-token"


def get_header(event: dict, name: str) -> str | None:
    headers = event.get("headers") or {}
    # HTTP API v2 lowercases header names, but accept any casing defensively.
    for key, value in headers.items():
        if key.lower() == name:
            return value
    return None


def require_application_token(event: dict, application_id: str) -> None:
    token = get_header(event, TOKEN_HEADER)
    if not token or token != application_id:
        raise UnauthorizedError("Missing or invalid X-Application-Token")
