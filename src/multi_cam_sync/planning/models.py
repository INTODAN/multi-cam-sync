"""Immutable inputs and outputs for pure edit planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from multi_cam_sync.planning.frame_math import FrameRate


class VideoStatus(StrEnum):
    """The video decision for one master segment."""

    NOT_PROVIDED = "not_provided"
    MATCHED = "matched"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class MediaDescriptor:
    """The media facts required by the pure planner."""

    media_id: str
    name: str
    duration_seconds: Decimal
    frame_rate: FrameRate


@dataclass(frozen=True, slots=True)
class SegmentInput:
    """One contiguous interval in the final master."""

    id: str
    index: int
    display_take: str
    take_key: str
    start_seconds: Decimal
    end_seconds: Decimal


@dataclass(frozen=True, slots=True)
class VideoAssignment:
    """A source decision for one segment."""

    status: VideoStatus
    source_id: str | None = None
    media: MediaDescriptor | None = None
    source_in_seconds: Decimal | None = None
    predicted_source_out_seconds: Decimal | None = None
    method: str | None = None
    warnings: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    @classmethod
    def not_provided(cls) -> VideoAssignment:
        return cls(status=VideoStatus.NOT_PROVIDED)


@dataclass(frozen=True, slots=True)
class PlannedClip:
    """One Resolve clip-info placement."""

    id: str
    segment_id: str
    take_key: str
    media_id: str
    media_type: str
    track_index: int
    source_start_frame: int
    source_end_frame: int
    record_start_frame: int
    record_end_frame: int
    name: str
    color: str


@dataclass(frozen=True, slots=True)
class PlannedGap:
    """An explicit interval with no video item."""

    id: str
    segment_id: str
    take_key: str
    record_start_frame: int
    record_end_frame: int


@dataclass(frozen=True, slots=True)
class PlannedSegment:
    """The paired audio and optional video decision for a master segment."""

    segment_id: str
    index: int
    display_take: str
    take_key: str
    video_status: VideoStatus
    audio_clip: PlannedClip
    video_clip: PlannedClip | None = None
    video_gap: PlannedGap | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedMarker:
    """A Resolve timeline marker at a master cut."""

    id: str
    frame: int
    color: str
    name: str
    note: str
    duration: int
    custom_data: str


@dataclass(frozen=True, slots=True)
class EditPlan:
    """A fully precomputed, Resolve-independent timeline edit."""

    timeline_name: str
    timeline_rate: FrameRate
    timeline_start_frame: int
    segments: tuple[PlannedSegment, ...]
    markers: tuple[PlannedMarker, ...]
    color_map: tuple[tuple[str, str], ...]
    expected_snapshot: object | None = None

    @property
    def audio_clips(self) -> tuple[PlannedClip, ...]:
        return tuple(segment.audio_clip for segment in self.segments)

    @property
    def video_clips(self) -> tuple[PlannedClip, ...]:
        return tuple(
            segment.video_clip for segment in self.segments if segment.video_clip is not None
        )

    @property
    def video_gaps(self) -> tuple[PlannedGap, ...]:
        return tuple(
            segment.video_gap for segment in self.segments if segment.video_gap is not None
        )

    def validate(self) -> None:
        """Validate this plan using the canonical planning invariants."""
        from multi_cam_sync.planning.planner import validate_edit_plan

        validate_edit_plan(self)


@dataclass(frozen=True, slots=True)
class PlanningInputs:
    """All values needed to create an EditPlan."""

    timeline_name: str
    timeline_rate: FrameRate
    timeline_start_frame: int
    master_media: MediaDescriptor
    segments: tuple[SegmentInput, ...]
    enabled_take_keys: frozenset[str] = frozenset()
    assignments: Mapping[str, VideoAssignment] = field(default_factory=dict)
    expected_snapshot: object | None = None
