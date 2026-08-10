"""Exact conversions between decimal seconds and media frames."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction


@dataclass(frozen=True, slots=True)
class FrameRate:
    """An exact rational frame rate."""

    numerator: int
    denominator: int = 1
    drop_frame: bool = False

    def __post_init__(self) -> None:
        if self.numerator <= 0 or self.denominator <= 0:
            raise ValueError("frame rate must be positive")
        normalized = Fraction(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", normalized.numerator)
        object.__setattr__(self, "denominator", normalized.denominator)

    @classmethod
    def parse(cls, value: FrameRate | Fraction | Decimal | float | int | str) -> FrameRate:
        """Parse Resolve-style integer, decimal, or rational frame rates."""
        if isinstance(value, cls):
            return value
        if isinstance(value, Fraction):
            fraction = value
        elif isinstance(value, Decimal):
            # Resolve's rational strings pass through its Decimal snapshot boundary.
            # Recover the small exact video-rate ratio instead of publishing the finite
            # Decimal expansion as an enormous fraction (for example, 24000/1001).
            fraction = Fraction(value).limit_denominator(1_000_000)
        elif isinstance(value, int):
            fraction = Fraction(value, 1)
        elif isinstance(value, float):
            fraction = Fraction(str(value))
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                raise ValueError("frame rate cannot be empty")
            fraction = Fraction(text)
        else:  # pragma: no cover - defensive runtime boundary
            raise TypeError(f"unsupported frame-rate value: {type(value).__name__}")
        return cls(fraction.numerator, fraction.denominator)

    @property
    def decimal(self) -> Decimal:
        """Return the exact rate as a Decimal division."""
        return Decimal(self.numerator) / Decimal(self.denominator)

    def __str__(self) -> str:
        if self.denominator == 1:
            return str(self.numerator)
        return f"{self.numerator}/{self.denominator}"


def seconds_to_frame(value: Decimal, rate: FrameRate) -> int:
    """Round a non-negative absolute time to the nearest frame, half up."""
    if value < 0:
        raise ValueError("seconds cannot be negative")
    frames = value * Decimal(rate.numerator) / Decimal(rate.denominator)
    return int(frames.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def frame_error(value: Decimal, rate: FrameRate) -> Decimal:
    """Return an absolute duration expressed as fractional frames."""
    return abs(value) * Decimal(rate.numerator) / Decimal(rate.denominator)
