"""DynamoDB adapter — table access, conditional writes, idempotency.

Wraps boto3 so services never call boto3 directly (spec §11: storage is a
replaceable adapter). Two access styles are used:

- The high-level `Table` resource for plain GetItem/PutItem/Query, where
  boto3's native Python-type marshalling keeps call sites simple.
- The low-level client + `TypeSerializer` for `TransactWriteItems`, which
  has no resource-level equivalent — used to atomically write a
  PERSON#/BUSINESS item together with the META version bump that guards
  against silent overwrites (spec §2.4).
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import boto3
from boto3.dynamodb.types import TypeSerializer
from botocore.exceptions import ClientError

from common.errors import ConflictError, NotFoundError


@lru_cache(maxsize=1)
def _table():
    table_name = os.environ["TABLE_NAME"]
    return boto3.resource("dynamodb").Table(table_name)


@lru_cache(maxsize=1)
def _raw_client():
    # A plain low-level client — NOT `_table().meta.client`. The resource's
    # client has boto3's automatic Python<->AttributeValue marshalling
    # injected onto it, which double-converts the already-serialized items
    # TransactWriteItems needs here (there's no resource-level transact API).
    return boto3.client("dynamodb")


def get_item(pk: str, sk: str) -> dict[str, Any] | None:
    response = _table().get_item(Key={"PK": pk, "SK": sk})
    return response.get("Item")


def get_item_or_404(pk: str, sk: str, *, not_found_message: str) -> dict[str, Any]:
    item = get_item(pk, sk)
    if item is None:
        raise NotFoundError(not_found_message)
    return item


def query_by_pk(pk: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "PK = :pk",
        "ExpressionAttributeValues": {":pk": pk},
    }
    while True:
        response = _table().query(**kwargs)
        items.extend(response.get("Items", []))
        last_key = response.get("LastEvaluatedKey")
        if not last_key:
            return items
        kwargs["ExclusiveStartKey"] = last_key


def put_item(item: dict[str, Any]) -> None:
    """Unconditional PutItem — full overwrite. Used for single-slot,
    upsert-style items (e.g. MCC#PROPOSED/MCC#CONFIRMED) that have no
    optimistic-concurrency version and are safe to freely replace."""
    _table().put_item(Item=item)


def put_item_if_absent(item: dict[str, Any]) -> None:
    """PutItem guarded against overwriting an existing item with the same key."""
    try:
        _table().put_item(Item=item, ConditionExpression="attribute_not_exists(PK)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ConflictError("Item already exists") from exc
        raise


_serializer = TypeSerializer()


def _serialize(item: dict[str, Any]) -> dict[str, Any]:
    return {k: _serializer.serialize(v) for k, v in item.items()}


def _build_set_expression(values: dict[str, Any], *, prefix: str) -> tuple[str, dict, dict]:
    """Build a `SET ...` clause with placeholder names/values for `values`.

    Every attribute name is aliased (`#{prefix}{i}`), so callers never need
    to worry about DynamoDB reserved words (e.g. `status`) appearing in
    `values`' keys.
    """
    set_clauses = []
    expr_names: dict[str, str] = {}
    expr_values: dict[str, Any] = {}
    for i, (key, value) in enumerate(values.items()):
        name_placeholder = f"#{prefix}{i}"
        value_placeholder = f":{prefix}{i}"
        expr_names[name_placeholder] = key
        expr_values[value_placeholder] = value
        set_clauses.append(f"{name_placeholder} = {value_placeholder}")
    return "SET " + ", ".join(set_clauses), expr_names, expr_values


def update_item(
    pk: str,
    sk: str,
    updates: dict[str, Any],
    *,
    condition_expression: str | None = None,
    condition_names: dict[str, str] | None = None,
    condition_values: dict[str, Any] | None = None,
) -> None:
    """Conditionally UpdateItem a single item — e.g. a DOC# status transition.

    `condition_expression` may reference reserved words via its own
    `condition_names` placeholders (the `updates` side is always aliased
    automatically). Raises ConflictError on a failed condition check.
    """
    update_expression, expr_names, expr_values = _build_set_expression(updates, prefix="u")
    expr_names.update(condition_names or {})
    expr_values.update(condition_values or {})

    kwargs: dict[str, Any] = {
        "Key": {"PK": pk, "SK": sk},
        "UpdateExpression": update_expression,
        "ExpressionAttributeNames": expr_names,
        "ExpressionAttributeValues": expr_values,
    }
    if condition_expression:
        kwargs["ConditionExpression"] = condition_expression

    try:
        _table().update_item(**kwargs)
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ConflictError("Item was modified concurrently — reload and retry") from exc
        raise


def put_item_with_meta_version_bump(
    *,
    item: dict[str, Any],
    meta_pk: str,
    expected_version: int,
    meta_updates: dict[str, Any],
) -> int:
    """Atomically PutItem `item` and bump `META`'s version by 1.

    `META` is only updated if its `version` still equals `expected_version`
    (optimistic concurrency, spec §2.4) — a concurrent write that changed it
    in between causes the whole transaction to fail with a ConflictError.
    Returns the new version on success.
    """
    table_name = os.environ["TABLE_NAME"]
    new_version = expected_version + 1

    meta_update_values: dict[str, Any] = {**meta_updates, "version": new_version}
    update_expression, expr_names, expr_values = _build_set_expression(
        meta_update_values, prefix="f"
    )
    expr_values[":expected_version"] = expected_version

    try:
        _raw_client().transact_write_items(
            TransactItems=[
                {"Put": {"TableName": table_name, "Item": _serialize(item)}},
                {
                    "Update": {
                        "TableName": table_name,
                        "Key": _serialize({"PK": meta_pk, "SK": "META"}),
                        "UpdateExpression": update_expression,
                        "ConditionExpression": "version = :expected_version",
                        "ExpressionAttributeNames": expr_names,
                        "ExpressionAttributeValues": {
                            k: _serializer.serialize(v) for k, v in expr_values.items()
                        },
                    }
                },
            ]
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "TransactionCanceledException":
            raise ConflictError("Application was modified concurrently — reload and retry") from exc
        raise
    return new_version
