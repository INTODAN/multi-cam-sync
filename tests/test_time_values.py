from decimal import Decimal

import pytest

from multi_cam_sync.domain.errors import TimeValueError
from multi_cam_sync.time_values import (
    clean_take_name,
    normalize_take_name,
    parse_decimal_seconds,
    parse_decimal_timestamp,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("00:00:00", Decimal("0")),
        ("00:00:19.375", Decimal("19.375")),
        ("01:02:03.004", Decimal("3723.004")),
        ("123:45:06.123456789", Decimal("445506.123456789")),
        (" 00:00:00.000000001 ", Decimal("0.000000001")),
    ],
)
def test_parse_decimal_timestamp_is_exact(value: str, expected: Decimal) -> None:
    result = parse_decimal_timestamp(value)

    assert result == expected
    assert isinstance(result, Decimal)


@pytest.mark.parametrize(
    "value",
    ["", "1:02:03", "00:60:00", "00:00:60", "00:00:-1", "00:00:01.", "seconds"],
)
def test_parse_decimal_timestamp_rejects_invalid_ranges_and_shapes(value: str) -> None:
    with pytest.raises(TimeValueError, match="timestamp"):
        parse_decimal_timestamp(value)


@pytest.mark.parametrize("value", [True, False, float("inf"), float("nan"), "Infinity", object()])
def test_parse_decimal_seconds_requires_finite_numeric_input(value: object) -> None:
    with pytest.raises(TimeValueError, match=r"finite|numeric"):
        parse_decimal_seconds(value, field_name="offset")


def test_parse_decimal_seconds_does_not_retain_float_values() -> None:
    assert parse_decimal_seconds(1.25, field_name="offset") == Decimal("1.25")
    assert isinstance(parse_decimal_seconds(1, field_name="offset"), Decimal)


def test_take_name_has_distinct_display_and_comparison_forms() -> None:
    assert clean_take_name("  Take\t  6 B  ") == "Take 6 B"
    assert normalize_take_name(" Take\t  6 B ") == "Take 6 B"
    assert normalize_take_name("take 6 b") == "take 6 b"


@pytest.mark.parametrize("value", ["", " \t "])
def test_blank_take_name_is_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="blank"):
        normalize_take_name(value)
