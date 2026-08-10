"""Project-owned errors for the DaVinci Resolve boundary."""

from __future__ import annotations

from dataclasses import dataclass


class ResolveError(RuntimeError):
    """Base class for actionable Resolve integration failures."""

    def __init__(self, operation: str, message: str) -> None:
        self.operation = operation
        self.detail = message
        super().__init__(f"{operation}: {message}")


class ResolveConnectionError(ResolveError):
    """Resolve cannot be imported, reached, or has no usable current project."""


class ResolveOperationError(ResolveError):
    """A Resolve API call raised or returned an invalid result."""


class ResolveDiscoveryError(ResolveError):
    """A configured Media Pool selector did not resolve uniquely."""


class ResolvePreflightError(ResolveError):
    """The complete edit plan is not safe to apply."""


class ResolveVerificationError(ResolveError):
    """The timeline read-back differs from the edit plan."""


@dataclass(frozen=True, slots=True)
class RollbackStatus:
    """Outcome of deleting the one timeline created by a failed build."""

    attempted: bool
    succeeded: bool
    detail: str | None = None


class ResolveBuildError(ResolveError):
    """A post-creation failure, together with its narrow rollback outcome."""

    def __init__(
        self,
        operation: str,
        message: str,
        *,
        rollback: RollbackStatus,
    ) -> None:
        self.rollback = rollback
        rollback_text = "rollback succeeded" if rollback.succeeded else "rollback failed"
        if rollback.detail:
            rollback_text = f"{rollback_text}: {rollback.detail}"
        super().__init__(operation, f"{message}; {rollback_text}")
