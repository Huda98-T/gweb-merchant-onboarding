from __future__ import annotations

import pytest

from common.auth import require_application_token
from common.errors import UnauthorizedError


def test_require_application_token_accepts_matching_token():
    event = {"headers": {"x-application-token": "app-123"}}
    require_application_token(event, "app-123")  # should not raise


def test_require_application_token_accepts_mixed_case_header_name():
    event = {"headers": {"X-Application-Token": "app-123"}}
    require_application_token(event, "app-123")


def test_require_application_token_rejects_mismatched_token():
    event = {"headers": {"x-application-token": "app-999"}}
    with pytest.raises(UnauthorizedError):
        require_application_token(event, "app-123")


def test_require_application_token_rejects_missing_header():
    with pytest.raises(UnauthorizedError):
        require_application_token({"headers": {}}, "app-123")
