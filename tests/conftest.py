"""Shared pytest fixtures: a moto-mocked DynamoDB table matching template.yaml."""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

TABLE_NAME = "gweb-onboarding-test"


@pytest.fixture(autouse=True)
def aws_credentials(monkeypatch):
    """moto still wants *some* credentials present in the environment."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def dynamodb_table(aws_credentials, monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    with mock_aws():
        # Reset the adapter's cached Table resource so it picks up the mock.
        from adapters.db import dynamo_client

        dynamo_client._table.cache_clear()
        dynamo_client._raw_client.cache_clear()

        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
        dynamo_client._table.cache_clear()
        dynamo_client._raw_client.cache_clear()


class FakeLambdaContext:
    """Minimal stand-in for the real Lambda context object."""

    def get_remaining_time_in_millis(self) -> int:
        return 45_000
