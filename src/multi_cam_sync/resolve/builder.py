"""Preflight, native timeline construction, verification, and narrow rollback."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import cast

from .connection import ResolveSession
from .errors import (
    ResolveBuildError,
    ResolveError,
    ResolveOperationError,
    ResolvePreflightError,
    ResolveVerificationError,
    RollbackStatus,
)
from .protocols import (
    BuildResult,
    EditPlanLike,
    RawMediaPoolItem,
    RawTimeline,
    RawTimelineItem,
    ResolveProjectSnapshot,
)

SUPPORTED_CLIP_COLORS = frozenset(
    {
        "Orange",
        "Apricot",
        "Yellow",
        "Lime",
        "Olive",
        "Green",
        "Teal",
        "Navy",
        "Blue",
        "Purple",
        "Violet",
        "Pink",
        "Tan",
        "Beige",
        "Brown",
        "Chocolate",
    }
)
SUPPORTED_MARKER_COLORS = frozenset(
    {
        "Blue",
        "Cyan",
        "Green",
        "Yellow",
        "Red",
        "Pink",
        "Purple",
        "Fuchsia",
        "Rose",
        "Lavender",
        "Sky",
        "Mint",
        "Lemon",
        "Sand",
        "Cocoa",
        "Cream",
    }
)


@dataclass(frozen=True, slots=True)
class _Marker:
    frame: int
    color: str
    name: str
    note: str
    duration: int
    custom_data: str


@dataclass(frozen=True, slots=True)
class _Clip:
    media_id: str
    media_type: str
    track_index: int
    source_start: int
    source_end: int
    record_start: int
    record_end: int
    name: str
    color: str
    marker: _Marker | None


@dataclass(frozen=True, slots=True)
class _Gap:
    record_start: int
    record_end: int


@dataclass(frozen=True, slots=True)
class _Plan:
    timeline_name: str
    expected_snapshot: ResolveProjectSnapshot
    audio: tuple[_Clip, ...]
    video: tuple[_Clip, ...]
    gaps: tuple[_Gap, ...]
    markers: tuple[_Marker, ...]


def _attribute(value: object, name: str, *, default: object = ...) -> object:
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
    else:
        try:
            return getattr(value, name)
        except AttributeError:
            pass
    if default is not ...:
        return default
    raise ResolvePreflightError("validate edit plan", f"missing required field {name!r}")


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ResolvePreflightError("validate edit plan", f"{field} must be an int, got {value!r}")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResolvePreflightError("validate edit plan", f"{field} must be non-empty text")
    return value


def _normalize_marker(value: object, context: str) -> _Marker:
    return _Marker(
        frame=_integer(_attribute(value, "frame"), f"{context}.frame"),
        color=_text(_attribute(value, "color"), f"{context}.color"),
        name=_text(_attribute(value, "name"), f"{context}.name"),
        note=str(_attribute(value, "note", default="")),
        duration=_integer(_attribute(value, "duration", default=1), f"{context}.duration"),
        custom_data=str(_attribute(value, "custom_data", default="")),
    )


def _normalize_clip(value: object, context: str) -> _Clip:
    marker_value = _attribute(
        value, "marker", default=_attribute(value, "clip_marker", default=None)
    )
    marker = None if marker_value is None else _normalize_marker(marker_value, f"{context}.marker")
    return _Clip(
        media_id=_text(_attribute(value, "media_id"), f"{context}.media_id"),
        media_type=_text(_attribute(value, "media_type"), f"{context}.media_type"),
        track_index=_integer(_attribute(value, "track_index"), f"{context}.track_index"),
        source_start=_integer(
            _attribute(value, "source_start_frame"), f"{context}.source_start_frame"
        ),
        source_end=_integer(_attribute(value, "source_end_frame"), f"{context}.source_end_frame"),
        record_start=_integer(
            _attribute(value, "record_start_frame"), f"{context}.record_start_frame"
        ),
        record_end=_integer(_attribute(value, "record_end_frame"), f"{context}.record_end_frame"),
        name=_text(_attribute(value, "name"), f"{context}.name"),
        color=_text(_attribute(value, "color"), f"{context}.color"),
        marker=marker,
    )


def normalize_plan(plan: EditPlanLike) -> _Plan:
    """Validate the public structural contract and freeze it for one transaction."""

    validator = getattr(plan, "validate", None)
    if not callable(validator):
        raise ResolvePreflightError("validate edit plan", "plan has no callable validate()")
    try:
        validation = validator()
    except Exception as exc:
        raise ResolvePreflightError(
            "validate edit plan", f"plan validator raised {type(exc).__name__}: {exc}"
        ) from exc
    if validation is False or (
        isinstance(validation, Sequence)
        and not isinstance(validation, (str, bytes))
        and len(validation) > 0
    ):
        raise ResolvePreflightError(
            "validate edit plan", f"plan validator rejected plan: {validation!r}"
        )

    snapshot = _attribute(plan, "expected_snapshot")
    if not isinstance(snapshot, ResolveProjectSnapshot):
        raise ResolvePreflightError(
            "validate edit plan", "expected_snapshot must be a ResolveProjectSnapshot"
        )
    audio_values = _attribute(plan, "audio_clips")
    video_values = _attribute(plan, "video_clips")
    gap_values = _attribute(plan, "video_gaps")
    marker_values = _attribute(plan, "markers")
    try:
        audio = tuple(
            _normalize_clip(value, f"audio_clips[{index}]")
            for index, value in enumerate(cast("Sequence[object]", audio_values))
        )
        video = tuple(
            _normalize_clip(value, f"video_clips[{index}]")
            for index, value in enumerate(cast("Sequence[object]", video_values))
        )
        gaps = tuple(
            _Gap(
                record_start=_integer(
                    _attribute(value, "record_start_frame"),
                    f"video_gaps[{index}].record_start_frame",
                ),
                record_end=_integer(
                    _attribute(value, "record_end_frame"),
                    f"video_gaps[{index}].record_end_frame",
                ),
            )
            for index, value in enumerate(cast("Sequence[object]", gap_values))
        )
        for index, value in enumerate(cast("Sequence[object]", gap_values)):
            if _attribute(value, "media_id", default=None) is not None:
                raise ResolvePreflightError(
                    "validate edit plan", f"video_gaps[{index}] must not carry a media_id"
                )
        markers = tuple(
            _normalize_marker(value, f"markers[{index}]")
            for index, value in enumerate(cast("Sequence[object]", marker_values))
        )
    except TypeError as exc:
        raise ResolvePreflightError(
            "validate edit plan", "clip/gap/marker fields must be sequences"
        ) from exc
    return _Plan(
        timeline_name=_text(_attribute(plan, "timeline_name"), "timeline_name"),
        expected_snapshot=snapshot,
        audio=audio,
        video=video,
        gaps=gaps,
        markers=markers,
    )


def _operation(operation: str, function: Callable[..., object], *args: object) -> object:
    try:
        return function(*args)
    except ResolveError:
        raise
    except Exception as exc:
        raise ResolveOperationError(
            operation, f"API call raised {type(exc).__name__}: {exc}"
        ) from exc


def _require_true(operation: str, function: Callable[..., object], *args: object) -> None:
    result = _operation(operation, function, *args)
    if result is not True:
        raise ResolveOperationError(operation, f"expected True, got {result!r}")


def _require_int(operation: str, function: Callable[..., object], *args: object) -> int:
    result = _operation(operation, function, *args)
    if not isinstance(result, int) or isinstance(result, bool):
        raise ResolveOperationError(operation, f"expected int, got {result!r}")
    return result


def _require_text(operation: str, function: Callable[..., object], *args: object) -> str:
    result = _operation(operation, function, *args)
    if not isinstance(result, str) or not result.strip():
        raise ResolveOperationError(operation, f"expected non-empty text, got {result!r}")
    return result


def _require_items(operation: str, value: object) -> list[RawTimelineItem]:
    if value is None or value is False or isinstance(value, (str, bytes, Mapping)):
        raise ResolveOperationError(operation, f"expected item list, got {value!r}")
    try:
        return [cast("RawTimelineItem", item) for item in cast("Sequence[object]", value)]
    except TypeError as exc:
        raise ResolveOperationError(operation, f"expected item list, got {value!r}") from exc


def _preflight_plan(
    plan: _Plan,
    current_snapshot: ResolveProjectSnapshot,
    media_by_id: Mapping[str, RawMediaPoolItem],
) -> None:
    if plan.expected_snapshot.fingerprint != current_snapshot.fingerprint:
        raise ResolvePreflightError(
            "compare Resolve snapshot",
            "project, timelines, settings, or selected media changed since analysis",
        )
    if plan.timeline_name in current_snapshot.timeline_names:
        raise ResolvePreflightError(
            "validate target timeline", f"timeline {plan.timeline_name!r} already exists"
        )
    if not plan.audio:
        raise ResolvePreflightError(
            "validate edit plan", "at least one master-audio clip is required"
        )

    metadata = current_snapshot.media_by_id
    for track_name, clips, expected_kind in (
        ("audio", plan.audio, "master"),
        ("video", plan.video, "video"),
    ):
        for index, clip in enumerate(clips):
            item = metadata.get(clip.media_id)
            if item is None or clip.media_id not in media_by_id:
                raise ResolvePreflightError(
                    "validate media IDs",
                    f"{track_name}[{index}] references unresolved media {clip.media_id!r}",
                )
            if item.kind != expected_kind:
                raise ResolvePreflightError(
                    "validate media type",
                    f"{track_name}[{index}] requires {expected_kind!r} media, got {item.kind!r}",
                )
            if clip.media_type != track_name or clip.track_index != 1:
                raise ResolvePreflightError(
                    "validate media type",
                    f"{track_name}[{index}] must be {track_name}-only on track 1",
                )
            if clip.source_start < 0 or clip.source_end <= clip.source_start:
                raise ResolvePreflightError(
                    "validate source bounds", f"{track_name}[{index}] has invalid source interval"
                )
            if clip.source_end > item.duration_frames:
                raise ResolvePreflightError(
                    "validate source bounds",
                    f"{track_name}[{index}] ends at {clip.source_end}, beyond media "
                    f"duration {item.duration_frames}",
                )
            if clip.record_end <= clip.record_start:
                raise ResolvePreflightError(
                    "validate record bounds", f"{track_name}[{index}] has invalid record interval"
                )
            if clip.color not in SUPPORTED_CLIP_COLORS:
                raise ResolvePreflightError(
                    "validate clip color", f"unsupported Resolve clip color {clip.color!r}"
                )
            if clip.marker is not None:
                _preflight_marker(clip.marker, f"{track_name}[{index}].marker")

    for index, gap in enumerate(plan.gaps):
        if gap.record_end <= gap.record_start:
            raise ResolvePreflightError(
                "validate video gap", f"video_gaps[{index}] has invalid record interval"
            )
    for index, marker in enumerate(plan.markers):
        _preflight_marker(marker, f"markers[{index}]")
    if len({marker.frame for marker in plan.markers}) != len(plan.markers):
        raise ResolvePreflightError(
            "validate timeline markers", "multiple markers use the same timeline frame"
        )

    for prior, current in zip(plan.audio, plan.audio[1:], strict=False):
        if prior.record_end != current.record_start:
            raise ResolvePreflightError(
                "validate continuous master audio",
                f"audio boundary {prior.record_end} does not meet {current.record_start}",
            )
    audio_start = plan.audio[0].record_start
    audio_end = plan.audio[-1].record_end
    if (
        current_snapshot.timeline_start_frame is not None
        and audio_start != current_snapshot.timeline_start_frame
    ):
        raise ResolvePreflightError(
            "validate timeline start",
            f"plan starts at {audio_start}, Resolve start is "
            f"{current_snapshot.timeline_start_frame}",
        )

    coverage = sorted(
        [(clip.record_start, clip.record_end, "video") for clip in plan.video]
        + [(gap.record_start, gap.record_end, "gap") for gap in plan.gaps]
    )
    if not coverage or coverage[0][0] != audio_start or coverage[-1][1] != audio_end:
        raise ResolvePreflightError(
            "validate video coverage",
            "matched video and intentional gaps must span the full master range",
        )
    for prior, current in pairwise(coverage):
        if prior[1] != current[0]:
            relation = "overlap" if prior[1] > current[0] else "undeclared gap"
            raise ResolvePreflightError(
                "validate video coverage",
                f"{relation} between frames {prior[1]} and {current[0]}",
            )
    for marker in plan.markers:
        if not audio_start <= marker.frame <= audio_end:
            raise ResolvePreflightError(
                "validate timeline marker", f"marker frame {marker.frame} lies outside master range"
            )


def _preflight_marker(marker: _Marker, context: str) -> None:
    if marker.duration <= 0:
        raise ResolvePreflightError("validate marker", f"{context} duration must be positive")
    if marker.color not in SUPPORTED_MARKER_COLORS:
        raise ResolvePreflightError(
            "validate marker", f"{context} uses unsupported Resolve marker color {marker.color!r}"
        )


def _ensure_track(timeline: RawTimeline, track_type: str) -> None:
    count = _require_int(
        f"Timeline.GetTrackCount({track_type})", timeline.GetTrackCount, track_type
    )
    if count < 0:
        raise ResolveOperationError(
            f"Timeline.GetTrackCount({track_type})", f"expected non-negative count, got {count}"
        )
    if count == 0:
        if track_type == "audio":
            _require_true("Timeline.AddTrack(audio)", timeline.AddTrack, "audio", "stereo")
        else:
            _require_true("Timeline.AddTrack(video)", timeline.AddTrack, "video")
        count = _require_int(
            f"Timeline.GetTrackCount({track_type})", timeline.GetTrackCount, track_type
        )
        if count < 1:
            raise ResolveOperationError(
                f"Timeline.AddTrack({track_type})",
                "track count remained zero after successful AddTrack",
            )


def _append_clip(
    session: ResolveSession,
    clip: _Clip,
    raw_media: RawMediaPoolItem,
    *,
    media_type: int,
    track_type: str,
) -> RawTimelineItem:
    clip_info: dict[str, object] = {
        "mediaPoolItem": raw_media,
        "startFrame": clip.source_start,
        "endFrame": clip.source_end,
        "mediaType": media_type,
        "trackIndex": 1,
        "recordFrame": clip.record_start,
    }
    operation = f"MediaPool.AppendToTimeline({track_type})"
    result = _operation(operation, session.media_pool.AppendToTimeline, [clip_info])
    items = _require_items(operation, result)
    if len(items) != 1:
        raise ResolveOperationError(
            operation, f"expected exactly one TimelineItem, got {len(items)}"
        )
    item = items[0]
    _require_true("TimelineItem.SetName", item.SetName, clip.name)
    _require_true("TimelineItem.SetClipColor", item.SetClipColor, clip.color)
    if clip.marker is not None:
        marker = clip.marker
        _require_true(
            "TimelineItem.AddMarker",
            item.AddMarker,
            marker.frame,
            marker.color,
            marker.name,
            marker.note,
            marker.duration,
            marker.custom_data,
        )
    return item


def _as_int(operation: str, value: object) -> int:
    if isinstance(value, bool):
        raise ResolveVerificationError(operation, f"expected integral frame, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ResolveVerificationError(operation, f"expected integral frame, got {value!r}")


def _marker_map(operation: str, value: object) -> dict[int, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        raise ResolveVerificationError(operation, f"expected marker mapping, got {value!r}")
    result: dict[int, Mapping[str, object]] = {}
    for raw_frame, raw_info in value.items():
        frame = _as_int(operation, raw_frame)
        if not isinstance(raw_info, Mapping):
            raise ResolveVerificationError(operation, f"marker {raw_frame!r} has invalid metadata")
        result[frame] = cast("Mapping[str, object]", raw_info)
    return result


def _verify_marker(actual: Mapping[str, object], expected: _Marker, *, operation: str) -> None:
    checks = {
        "color": expected.color,
        "name": expected.name,
        "note": expected.note,
        "customData": expected.custom_data,
    }
    for key, expected_value in checks.items():
        if actual.get(key, "") != expected_value:
            raise ResolveVerificationError(
                operation, f"marker {key} expected {expected_value!r}, got {actual.get(key)!r}"
            )
    if _as_int(operation, actual.get("duration")) != expected.duration:
        raise ResolveVerificationError(operation, "marker duration differs from plan")


def _verify_item(item: RawTimelineItem, expected: _Clip, *, track_type: str) -> None:
    operation = f"verify {track_type} TimelineItem"
    actual = (
        _as_int(operation, _operation("TimelineItem.GetStart", item.GetStart, False)),
        _as_int(operation, _operation("TimelineItem.GetEnd", item.GetEnd, False)),
        _as_int(
            operation, _operation("TimelineItem.GetSourceStartFrame", item.GetSourceStartFrame)
        ),
        _as_int(operation, _operation("TimelineItem.GetSourceEndFrame", item.GetSourceEndFrame)),
    )
    wanted = (
        expected.record_start,
        expected.record_end,
        expected.source_start,
        expected.source_end,
    )
    if actual != wanted:
        raise ResolveVerificationError(
            operation, f"frame tuple expected {wanted!r}, got {actual!r}"
        )
    if _require_text("TimelineItem.GetName", item.GetName) != expected.name:
        raise ResolveVerificationError(operation, "item name differs from plan")
    if _require_text("TimelineItem.GetClipColor", item.GetClipColor) != expected.color:
        raise ResolveVerificationError(operation, "item color differs from plan")
    track = _operation("TimelineItem.GetTrackTypeAndIndex", item.GetTrackTypeAndIndex)
    if (
        not isinstance(track, Sequence)
        or isinstance(track, (str, bytes))
        or list(track) != [track_type, 1]
    ):
        raise ResolveVerificationError(
            operation, f"expected track {[track_type, 1]!r}, got {track!r}"
        )
    media = _operation("TimelineItem.GetMediaPoolItem", item.GetMediaPoolItem)
    if media is None or media is False:
        raise ResolveVerificationError(operation, "item has no Media Pool item")
    media_item = cast("RawMediaPoolItem", media)
    media_id = _require_text("MediaPoolItem.GetMediaId", media_item.GetMediaId)
    if media_id != expected.media_id:
        raise ResolveVerificationError(
            operation, f"expected media ID {expected.media_id!r}, got {media_id!r}"
        )
    markers = _marker_map(
        "TimelineItem.GetMarkers", _operation("TimelineItem.GetMarkers", item.GetMarkers)
    )
    if expected.marker is None:
        if markers:
            raise ResolveVerificationError(operation, "item has an unplanned clip marker")
    else:
        if set(markers) != {expected.marker.frame}:
            raise ResolveVerificationError(operation, "clip marker positions differ from plan")
        _verify_marker(markers[expected.marker.frame], expected.marker, operation=operation)


def verify_timeline(timeline: RawTimeline, plan: _Plan) -> None:
    """Read the built timeline back and compare every planned invariant."""

    if _require_text("Timeline.GetName", timeline.GetName) != plan.timeline_name:
        raise ResolveVerificationError("verify timeline", "timeline name differs from plan")
    timeline_start = _require_int("Timeline.GetStartFrame", timeline.GetStartFrame)
    timeline_end = _require_int("Timeline.GetEndFrame", timeline.GetEndFrame)
    expected_range = (plan.audio[0].record_start, plan.audio[-1].record_end)
    if (timeline_start, timeline_end) != expected_range:
        raise ResolveVerificationError(
            "verify timeline range",
            f"expected {expected_range!r}, got {(timeline_start, timeline_end)!r}",
        )
    if _require_int("Timeline.GetTrackCount(audio)", timeline.GetTrackCount, "audio") < 1:
        raise ResolveVerificationError("verify timeline", "Audio Track 1 is absent")
    audio_items = _require_items(
        "Timeline.GetItemListInTrack(audio, 1)",
        _operation(
            "Timeline.GetItemListInTrack(audio, 1)", timeline.GetItemListInTrack, "audio", 1
        ),
    )
    if len(audio_items) != len(plan.audio):
        raise ResolveVerificationError(
            "verify timeline", f"expected {len(plan.audio)} audio items, got {len(audio_items)}"
        )
    for item, expected in zip(audio_items, plan.audio, strict=True):
        _verify_item(item, expected, track_type="audio")

    if plan.video:
        if _require_int("Timeline.GetTrackCount(video)", timeline.GetTrackCount, "video") < 1:
            raise ResolveVerificationError("verify timeline", "Video Track 1 is absent")
        video_items = _require_items(
            "Timeline.GetItemListInTrack(video, 1)",
            _operation(
                "Timeline.GetItemListInTrack(video, 1)", timeline.GetItemListInTrack, "video", 1
            ),
        )
    else:
        # An empty timeline may already contain V1. Inspect it if present, but do not
        # require or create it.
        video_track_count = _require_int(
            "Timeline.GetTrackCount(video)", timeline.GetTrackCount, "video"
        )
        video_items = (
            _require_items(
                "Timeline.GetItemListInTrack(video, 1)",
                _operation(
                    "Timeline.GetItemListInTrack(video, 1)", timeline.GetItemListInTrack, "video", 1
                ),
            )
            if video_track_count >= 1
            else []
        )
    if len(video_items) != len(plan.video):
        raise ResolveVerificationError(
            "verify timeline", f"expected {len(plan.video)} video items, got {len(video_items)}"
        )
    for item, expected in zip(video_items, plan.video, strict=True):
        _verify_item(item, expected, track_type="video")

    # Exact item ranges plus the preflight partition prove every declared gap is empty,
    # and that there are no filler clips, undeclared gaps, or overlaps.
    actual_ranges = [
        (
            _as_int("verify video gap", _operation("TimelineItem.GetStart", item.GetStart, False)),
            _as_int("verify video gap", _operation("TimelineItem.GetEnd", item.GetEnd, False)),
        )
        for item in video_items
    ]
    for gap in plan.gaps:
        if any(start < gap.record_end and end > gap.record_start for start, end in actual_ranges):
            raise ResolveVerificationError(
                "verify intentional video gap",
                f"a video item occupies planned empty range {gap.record_start}:{gap.record_end}",
            )

    markers = _marker_map(
        "Timeline.GetMarkers", _operation("Timeline.GetMarkers", timeline.GetMarkers)
    )
    expected_markers = {marker.frame: marker for marker in plan.markers}
    if set(markers) != set(expected_markers):
        raise ResolveVerificationError(
            "verify timeline markers", "marker positions differ from plan"
        )
    for frame, expected in expected_markers.items():
        _verify_marker(markers[frame], expected, operation="verify timeline markers")


class TimelineBuilder:
    """One-shot timeline builder; preflight is guaranteed before first mutation."""

    def __init__(
        self,
        session: ResolveSession,
        current_snapshot: ResolveProjectSnapshot,
        raw_media_by_id: Mapping[str, RawMediaPoolItem],
    ) -> None:
        self._session = session
        self._snapshot = current_snapshot
        self._raw_media = raw_media_by_id

    def build(self, plan_like: EditPlanLike) -> BuildResult:
        plan = normalize_plan(plan_like)
        _preflight_plan(plan, self._snapshot, self._raw_media)

        created: RawTimeline | None = None
        try:
            value = _operation(
                "MediaPool.CreateEmptyTimeline",
                self._session.media_pool.CreateEmptyTimeline,
                plan.timeline_name,
            )
            if value is None or value is False:
                raise ResolveOperationError(
                    "MediaPool.CreateEmptyTimeline", f"expected Timeline, got {value!r}"
                )
            created = cast("RawTimeline", value)
            _require_true(
                "Project.SetCurrentTimeline", self._session.project.SetCurrentTimeline, created
            )
            timeline_id = _require_text("Timeline.GetUniqueId", created.GetUniqueId)
            _ensure_track(created, "audio")
            if plan.video:
                _ensure_track(created, "video")

            for clip in plan.audio:
                _append_clip(
                    self._session,
                    clip,
                    self._raw_media[clip.media_id],
                    media_type=2,
                    track_type="audio",
                )
            for clip in plan.video:
                _append_clip(
                    self._session,
                    clip,
                    self._raw_media[clip.media_id],
                    media_type=1,
                    track_type="video",
                )
            for marker in plan.markers:
                _require_true(
                    "Timeline.AddMarker",
                    created.AddMarker,
                    marker.frame,
                    marker.color,
                    marker.name,
                    marker.note,
                    marker.duration,
                    marker.custom_data,
                )
            verify_timeline(created, plan)
            return BuildResult(
                timeline_id=timeline_id,
                timeline_name=plan.timeline_name,
                audio_item_count=len(plan.audio),
                video_item_count=len(plan.video),
                marker_count=len(plan.markers),
            )
        except Exception as exc:
            if created is None:
                raise
            rollback = self._rollback(created)
            if isinstance(exc, ResolveError):
                operation = exc.operation
                detail = exc.detail
            else:
                operation = "build Resolve timeline"
                detail = f"unexpected {type(exc).__name__}: {exc}"
            raise ResolveBuildError(operation, detail, rollback=rollback) from exc

    def _rollback(self, created: RawTimeline) -> RollbackStatus:
        try:
            value = self._session.media_pool.DeleteTimelines([created])
        except Exception as exc:
            return RollbackStatus(
                attempted=True,
                succeeded=False,
                detail=f"DeleteTimelines raised {type(exc).__name__}: {exc}",
            )
        if value is not True:
            return RollbackStatus(
                attempted=True,
                succeeded=False,
                detail=f"DeleteTimelines returned {value!r}",
            )
        return RollbackStatus(attempted=True, succeeded=True)
