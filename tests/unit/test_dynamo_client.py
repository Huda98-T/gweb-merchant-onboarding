"""Adapter-level tests for conditional writes (spec §2.4), against moto."""

from __future__ import annotations

import pytest

from adapters.db import dynamo_client
from common.errors import ConflictError, NotFoundError


def test_put_item_if_absent_creates_new_item(dynamodb_table):
    dynamo_client.put_item_if_absent({"PK": "APP#1", "SK": "META", "version": 1})
    assert dynamo_client.get_item("APP#1", "META") == {"PK": "APP#1", "SK": "META", "version": 1}


def test_put_item_if_absent_rejects_duplicate_key(dynamodb_table):
    dynamo_client.put_item_if_absent({"PK": "APP#1", "SK": "META", "version": 1})
    with pytest.raises(ConflictError):
        dynamo_client.put_item_if_absent({"PK": "APP#1", "SK": "META", "version": 1})


def test_get_item_or_404_raises_when_missing(dynamodb_table):
    with pytest.raises(NotFoundError):
        dynamo_client.get_item_or_404("APP#missing", "META", not_found_message="not found")


def test_query_by_pk_returns_all_items_under_partition(dynamodb_table):
    dynamo_client.put_item_if_absent({"PK": "APP#1", "SK": "META", "version": 1})
    dynamodb_table.put_item(Item={"PK": "APP#1", "SK": "PERSON#a", "firstName": "Ada"})
    dynamodb_table.put_item(Item={"PK": "APP#2", "SK": "META", "version": 1})

    items = dynamo_client.query_by_pk("APP#1")
    assert {item["SK"] for item in items} == {"META", "PERSON#a"}


def test_put_item_with_meta_version_bump_succeeds_and_bumps_version(dynamodb_table):
    dynamo_client.put_item_if_absent({"PK": "APP#1", "SK": "META", "version": 1})

    new_version = dynamo_client.put_item_with_meta_version_bump(
        item={"PK": "APP#1", "SK": "BUSINESS", "legalName": "Acme"},
        meta_pk="APP#1",
        expected_version=1,
        meta_updates={"updatedAt": "now"},
    )

    assert new_version == 2
    meta = dynamo_client.get_item("APP#1", "META")
    assert meta["version"] == 2
    assert meta["updatedAt"] == "now"
    business = dynamo_client.get_item("APP#1", "BUSINESS")
    assert business["legalName"] == "Acme"


def test_put_item_with_meta_version_bump_rejects_stale_version(dynamodb_table):
    dynamo_client.put_item_if_absent({"PK": "APP#1", "SK": "META", "version": 1})
    # Simulate a concurrent writer that already bumped the version.
    dynamodb_table.update_item(
        Key={"PK": "APP#1", "SK": "META"},
        UpdateExpression="SET version = :v",
        ExpressionAttributeValues={":v": 2},
    )

    with pytest.raises(ConflictError):
        dynamo_client.put_item_with_meta_version_bump(
            item={"PK": "APP#1", "SK": "BUSINESS", "legalName": "Acme"},
            meta_pk="APP#1",
            expected_version=1,  # stale
            meta_updates={"updatedAt": "now"},
        )

    # The BUSINESS item must not have been written — the transaction is atomic.
    assert dynamo_client.get_item("APP#1", "BUSINESS") is None
