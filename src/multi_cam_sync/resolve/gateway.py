"""Public gateway coordinating fresh Resolve reads and timeline builds."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .builder import TimelineBuilder, normalize_plan
from .connection import ResolveSession, connect_resolve
from .discovery import capture_snapshot
from .protocols import BuildResult, EditPlanLike, MediaSelector, ResolveProjectSnapshot


class DaVinciResolveGateway:
    """Lazy production gateway; construction and import have no Resolve side effects."""

    def __init__(self, connector: Callable[[], ResolveSession] = connect_resolve) -> None:
        self._connector = connector

    def snapshot(self, selectors: Iterable[MediaSelector]) -> ResolveProjectSnapshot:
        session = self._connector()
        snapshot, _ = capture_snapshot(session, selectors)
        return snapshot

    def build_timeline(self, plan: EditPlanLike) -> BuildResult:
        # Normalize once before contacting Resolve so malformed plans cannot even trigger
        # connection work. TimelineBuilder repeats normalization when freezing the actual
        # build transaction; both passes are read-only and deterministic.
        normalized = normalize_plan(plan)
        session = self._connector()
        current, raw_media = capture_snapshot(session, normalized.expected_snapshot.selectors)
        return TimelineBuilder(session, current, raw_media).build(plan)
