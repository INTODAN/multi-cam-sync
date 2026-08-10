"""Project-owned exceptions intended for concise user-facing diagnostics."""

from __future__ import annotations

from collections.abc import Iterable


class DomainError(ValueError):
    """Base class for invalid user input at the domain boundary."""


class ConfigError(DomainError):
    """The project configuration is missing, malformed, or inconsistent."""


class CutListError(DomainError):
    """The composite cut list cannot define a valid segment sequence."""


class TimeValueError(DomainError):
    """A timestamp or exact-second value is invalid."""


def format_validation_errors(summary: str, errors: Iterable[str]) -> str:
    """Format independent validation failures without exposing library tracebacks."""
    items = tuple(dict.fromkeys(errors))
    if not items:
        return summary
    return "\n".join((summary, *(f"- {item}" for item in items)))
