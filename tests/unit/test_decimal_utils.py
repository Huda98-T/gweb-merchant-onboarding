from __future__ import annotations

from decimal import Decimal

from common.decimal_utils import from_decimal, to_decimal


def test_to_decimal_converts_nested_floats():
    result = to_decimal({"a": 1.5, "b": [1, 2.25, {"c": 3.0}]})
    assert result == {"a": Decimal("1.5"), "b": [1, Decimal("2.25"), {"c": Decimal("3.0")}]}


def test_to_decimal_leaves_non_floats_untouched():
    assert to_decimal({"a": "text", "b": True, "c": None, "d": 5}) == {
        "a": "text",
        "b": True,
        "c": None,
        "d": 5,
    }


def test_from_decimal_converts_whole_numbers_to_int():
    assert from_decimal(Decimal("3.0")) == 3
    assert isinstance(from_decimal(Decimal("3.0")), int)


def test_from_decimal_converts_fractional_to_float():
    assert from_decimal(Decimal("3.5")) == 3.5
    assert isinstance(from_decimal(Decimal("3.5")), float)


def test_round_trip_preserves_value():
    original = {"pct": 33.3, "count": 4, "nested": {"x": 1.0}}
    assert from_decimal(to_decimal(original)) == {"pct": 33.3, "count": 4, "nested": {"x": 1}}
