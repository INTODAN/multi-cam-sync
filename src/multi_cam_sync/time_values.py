"""Exact parsing and normalization helpers for the domain layer."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from multi_cam_sync.domain.errors import TimeValueError

_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<hours>\d{2,}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d)(?:\.(?P<fraction>\d+))?$"
)
_FRAME_TIMECODE_PATTERN = re.compile(
    r"^(?P<hours>\d{2,}):(?P<minutes>[0-5]\d):(?P<seconds>[0-5]\d):(?P<frames>\d{2,})$"
)


def parse_decimal_timestamp(value: str) -> Decimal:
    """Parse ``HH:MM:SS[.fraction]`` into exact nonnegative seconds."""
    if not isinstance(value, str):
        raise TimeValueError(f"timestamp must be text, got {type(value).__name__}")
    stripped = value.strip()
    match = _TIMESTAMP_PATTERN.fullmatch(stripped)
    if match is None:
        raise TimeValueError(
            f"invalid timestamp {value!r}; expected HH:MM:SS with minutes and seconds from 00 to 59"
        )

    hours = Decimal(match.group("hours"))
    minutes = Decimal(match.group("minutes"))
    seconds = Decimal(match.group("seconds"))
    fraction_digits = match.group("fraction")
    fraction = Decimal(f"0.{fraction_digits}") if fraction_digits else Decimal(0)
    return hours * Decimal(3600) + minutes * Decimal(60) + seconds + fraction


def parse_frame_timestamp(value: str, frame_rate: Fraction) -> Decimal:
    """Parse non-drop ``HH:MM:SS:FF`` into seconds at an exact frame rate."""
    if not isinstance(value, str):
        raise TimeValueError(f"frame timecode must be text, got {type(value).__name__}")
    if frame_rate <= 0:
        raise TimeValueError("frame timecode rate must be positive")
    stripped = value.strip()
    match = _FRAME_TIMECODE_PATTERN.fullmatch(stripped)
    if match is None:
        raise TimeValueError(f"invalid frame timecode {value!r}; expected non-drop HH:MM:SS:FF")

    nominal_rate = (2 * frame_rate.numerator + frame_rate.denominator) // (
        2 * frame_rate.denominator
    )
    frame = int(match.group("frames"))
    if frame >= nominal_rate:
        raise TimeValueError(
            f"invalid frame timecode {value!r}; frame must be from 00 to "
            f"{nominal_rate - 1:02d} at {frame_rate} fps"
        )
    elapsed_seconds = (
        int(match.group("hours")) * 3600
        + int(match.group("minutes")) * 60
        + int(match.group("seconds"))
    )
    total_frames = elapsed_seconds * nominal_rate + frame
    return Decimal(total_frames * frame_rate.denominator) / Decimal(frame_rate.numerator)


def parse_decimal_seconds(value: object, *, field_name: str) -> Decimal:
    """Convert numeric seconds or a timestamp to a finite exact ``Decimal``."""
    if isinstance(value, bool):
        raise TimeValueError(f"{field_name} must be a finite number, not a boolean")
    if isinstance(value, str) and ":" in value:
        try:
            return parse_decimal_timestamp(value)
        except TimeValueError as error:
            raise TimeValueError(f"{field_name}: {error}") from error
    if not isinstance(value, (str, int, float, Decimal)):
        raise TimeValueError(f"{field_name} must be numeric seconds or an HH:MM:SS timestamp")

    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as error:
        raise TimeValueError(f"{field_name} must be a finite decimal number") from error
    if not result.is_finite():
        raise TimeValueError(f"{field_name} must be finite")
    return result


def clean_take_name(value: str) -> str:
    """Return the display spelling with surrounding/internal whitespace normalized."""
    if not isinstance(value, str):
        raise ValueError("take name must be text")
    display = " ".join(value.split())
    if not display:
        raise ValueError("take name must not be blank")
    return display


def normalize_take_name(value: str) -> str:
    """Return the whitespace-normalized, case-preserving take comparison key."""
    return clean_take_name(value)
