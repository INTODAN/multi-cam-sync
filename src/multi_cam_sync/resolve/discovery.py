"""Exact Media Pool discovery and normalized project snapshots."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import cast

from .connection import ResolveSession
from .errors import ResolveDiscoveryError, ResolveOperationError
from .protocols import (
    MediaSelector,
    RawFolder,
    RawMediaPoolItem,
    RawTimeline,
    ResolvedMediaItem,
    ResolveProjectSnapshot,
)

_PATH_KEYS = ("File Path", "FilePath", "Path")
_FRAME_KEYS = ("Frames", "Frame Count", "FrameCount")
_FPS_KEYS = ("FPS", "Frame Rate", "FrameRate")
_DURATION_KEYS = ("Duration",)


def _call(operation: str, function: Callable[..., object], *args: object) -> object:
    try:
        return function(*args)
    except Exception as exc:
        raise ResolveOperationError(
            operation, f"API call raised {type(exc).__name__}: {exc}"
        ) from exc


def _nonempty_text(operation: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResolveOperationError(operation, f"expected non-empty text, got {value!r}")
    return value.strip()


def parse_resolve_rate(value: object, *, operation: str) -> Decimal:
    """Parse integer, decimal, or rational Resolve frame-rate values exactly."""

    if not isinstance(value, str) or not value.strip():
        raise ResolveOperationError(operation, f"invalid frame rate {value!r}")
    text = value.strip().upper().removesuffix(" DF").strip()
    try:
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            rate = Decimal(numerator.strip()) / Decimal(denominator.strip())
        else:
            rate = Decimal(text)
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        raise ResolveOperationError(operation, f"invalid frame rate {value!r}") from exc
    if not rate.is_finite() or rate <= 0:
        raise ResolveOperationError(operation, f"frame rate must be positive, got {value!r}")
    return rate


def parse_resolve_timecode_frame(
    value: object,
    rate: Decimal,
    *,
    drop_frame: bool,
    operation: str,
) -> int:
    """Convert a Resolve start timecode to its absolute integer frame number."""

    text = _nonempty_text(operation, value)
    parts = text.replace(";", ":").split(":")
    if len(parts) != 4:
        raise ResolveOperationError(operation, f"invalid start timecode {value!r}")
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError as exc:
        raise ResolveOperationError(operation, f"invalid start timecode {value!r}") from exc
    nominal_rate = int(rate.to_integral_value(rounding=ROUND_HALF_UP))
    if (
        hours < 0
        or not 0 <= minutes < 60
        or not 0 <= seconds < 60
        or not 0 <= frames < nominal_rate
    ):
        raise ResolveOperationError(operation, f"invalid start timecode {value!r}")
    result = ((hours * 60 + minutes) * 60 + seconds) * nominal_rate + frames
    if drop_frame:
        if nominal_rate not in {30, 60}:
            raise ResolveOperationError(
                operation, f"drop-frame timecode is unsupported at rate {rate}"
            )
        dropped_per_minute = 2 if nominal_rate == 30 else 4
        total_minutes = hours * 60 + minutes
        if minutes % 10 != 0 and seconds == 0 and frames < dropped_per_minute:
            raise ResolveOperationError(operation, f"invalid dropped frame number in {value!r}")
        result -= dropped_per_minute * (total_minutes - total_minutes // 10)
    return result


def _mapping(operation: str, value: object) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ResolveOperationError(
            operation, f"expected non-empty property mapping, got {value!r}"
        )
    result: dict[str, str] = {}
    for key, item in value.items():
        if isinstance(key, str):
            result[key] = "" if item is None else str(item)
    if not result:
        raise ResolveOperationError(operation, "property mapping contains no string keys")
    return result


def _property(properties: Mapping[str, str], aliases: Sequence[str]) -> str | None:
    folded = {key.casefold().replace(" ", ""): value for key, value in properties.items()}
    for alias in aliases:
        value = folded.get(alias.casefold().replace(" ", ""))
        if value is not None and value.strip():
            return value.strip()
    return None


def _duration_timecode_to_frames(value: str, rate: Decimal, *, operation: str) -> int:
    parts = value.replace(";", ":").split(":")
    if len(parts) != 4:
        raise ResolveOperationError(operation, f"invalid Resolve duration timecode {value!r}")
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError as exc:
        raise ResolveOperationError(
            operation, f"invalid Resolve duration timecode {value!r}"
        ) from exc
    if min(hours, minutes, seconds, frames) < 0 or minutes >= 60 or seconds >= 60:
        raise ResolveOperationError(operation, f"invalid Resolve duration timecode {value!r}")
    whole_seconds = Decimal(hours * 3600 + minutes * 60 + seconds)
    return int((whole_seconds * rate).to_integral_value(rounding=ROUND_HALF_UP)) + frames


def _duration_frames(
    properties: Mapping[str, str], rate: Decimal, *, selector: MediaSelector
) -> int:
    value = _property(properties, _FRAME_KEYS)
    operation = f"MediaPoolItem.GetClipProperty({selector.display!r})"
    if value is not None:
        try:
            frames = int(value.replace(",", ""))
        except ValueError as exc:
            raise ResolveOperationError(operation, f"invalid frame count {value!r}") from exc
    else:
        duration = _property(properties, _DURATION_KEYS)
        if duration is None:
            raise ResolveOperationError(
                operation, "missing Frames/Duration metadata; refusing guessed duration"
            )
        frames = _duration_timecode_to_frames(duration, rate, operation=operation)
    if frames <= 0:
        raise ResolveOperationError(operation, f"duration must be positive, got {frames}")
    return frames


def _list(operation: str, value: object) -> list[object]:
    if value is None or value is False or isinstance(value, (str, bytes, Mapping)):
        raise ResolveOperationError(operation, f"expected a list, got {value!r}")
    try:
        return list(cast("Iterable[object]", value))
    except TypeError as exc:
        raise ResolveOperationError(operation, f"expected an iterable list, got {value!r}") from exc


def _exact_child(parent: RawFolder, component: str, *, parent_path: tuple[str, ...]) -> RawFolder:
    operation = f"Folder.GetSubFolderList({'/'.join(parent_path) or '<root>'})"
    children = _list(operation, _call(operation, parent.GetSubFolderList))
    matches: list[RawFolder] = []
    for child in children:
        typed = cast("RawFolder", child)
        name = _nonempty_text("Folder.GetName", _call("Folder.GetName", typed.GetName))
        if name == component:
            matches.append(typed)
    if not matches:
        parent_display = "/".join(parent_path) or "<root>"
        raise ResolveDiscoveryError(
            "resolve Media Pool folder",
            f"exact folder component {component!r} not found below {parent_display}",
        )
    if len(matches) > 1:
        raise ResolveDiscoveryError(
            "resolve Media Pool folder",
            f"multiple exact folders named {component!r} below {'/'.join(parent_path) or '<root>'}",
        )
    return matches[0]


def resolve_selector(
    root: RawFolder,
    selector: MediaSelector,
    *,
    project_frame_rate: Decimal,
) -> tuple[ResolvedMediaItem, RawMediaPoolItem]:
    """Resolve one exact selector without recursively broadening its scope."""

    folder = root
    traversed: tuple[str, ...] = ()
    for component in selector.folder:
        folder = _exact_child(folder, component, parent_path=traversed)
        traversed += (component,)

    operation = f"Folder.GetClipList({'/'.join(selector.folder)})"
    clips = _list(operation, _call(operation, folder.GetClipList))
    matches: list[RawMediaPoolItem] = []
    for clip in clips:
        typed = cast("RawMediaPoolItem", clip)
        name = _nonempty_text(
            "MediaPoolItem.GetName", _call("MediaPoolItem.GetName", typed.GetName)
        )
        if name == selector.name:
            matches.append(typed)
    if not matches:
        raise ResolveDiscoveryError(
            "resolve Media Pool item", f"exact selector {selector.display!r} matched no item"
        )
    if len(matches) > 1:
        raise ResolveDiscoveryError(
            "resolve Media Pool item",
            f"exact selector {selector.display!r} matched {len(matches)} items",
        )

    raw = matches[0]
    name = _nonempty_text("MediaPoolItem.GetName", _call("MediaPoolItem.GetName", raw.GetName))
    media_id = _nonempty_text(
        "MediaPoolItem.GetMediaId", _call("MediaPoolItem.GetMediaId", raw.GetMediaId)
    )
    properties = _mapping(
        "MediaPoolItem.GetClipProperty", _call("MediaPoolItem.GetClipProperty", raw.GetClipProperty)
    )
    fps_value = _property(properties, _FPS_KEYS)
    if fps_value is None:
        if selector.kind == "video":
            raise ResolveOperationError(
                "MediaPoolItem.GetClipProperty",
                f"video selector {selector.display!r} has no FPS metadata",
            )
        frame_rate = project_frame_rate
    else:
        frame_rate = parse_resolve_rate(fps_value, operation="MediaPoolItem FPS")
    duration_frames = _duration_frames(properties, frame_rate, selector=selector)
    path_value = _property(properties, _PATH_KEYS)
    file_path = Path(path_value) if path_value is not None else None
    return (
        ResolvedMediaItem(
            media_id=media_id,
            selector=selector,
            name=name,
            file_path=file_path,
            duration_frames=duration_frames,
            frame_rate=frame_rate,
            raw_properties=properties,
        ),
        raw,
    )


def capture_snapshot(
    session: ResolveSession,
    selectors: Iterable[MediaSelector],
) -> tuple[ResolveProjectSnapshot, dict[str, RawMediaPoolItem]]:
    """Capture project settings, timelines, and exact selected media in one read pass."""

    project = session.project
    project_name = _nonempty_text("Project.GetName", _call("Project.GetName", project.GetName))
    project_id = _nonempty_text(
        "Project.GetUniqueId", _call("Project.GetUniqueId", project.GetUniqueId)
    )
    raw_timeline_rate = _call(
        "Project.GetSetting(timelineFrameRate)", project.GetSetting, "timelineFrameRate"
    )
    timeline_frame_rate = parse_resolve_rate(
        raw_timeline_rate,
        operation="Project.GetSetting(timelineFrameRate)",
    )

    count_value = _call("Project.GetTimelineCount", project.GetTimelineCount)
    if not isinstance(count_value, int) or isinstance(count_value, bool) or count_value < 0:
        raise ResolveOperationError(
            "Project.GetTimelineCount", f"expected non-negative int, got {count_value!r}"
        )
    timeline_names: list[str] = []
    for index in range(1, count_value + 1):
        timeline_value = _call("Project.GetTimelineByIndex", project.GetTimelineByIndex, index)
        if timeline_value is None or timeline_value is False:
            raise ResolveOperationError(
                "Project.GetTimelineByIndex", f"index {index} returned no timeline"
            )
        timeline = cast("RawTimeline", timeline_value)
        name = _nonempty_text("Timeline.GetName", _call("Timeline.GetName", timeline.GetName))
        timeline_names.append(name)

    current = _call("Project.GetCurrentTimeline", project.GetCurrentTimeline)
    if current is None or current is False:
        start_timecode = _nonempty_text(
            "Project.GetSetting(timelineStartTimecode)",
            _call(
                "Project.GetSetting(timelineStartTimecode)",
                project.GetSetting,
                "timelineStartTimecode",
            ),
        )
        start_frame = parse_resolve_timecode_frame(
            start_timecode,
            timeline_frame_rate,
            drop_frame=isinstance(raw_timeline_rate, str)
            and raw_timeline_rate.upper().strip().endswith("DF"),
            operation="Project.GetSetting(timelineStartTimecode)",
        )
    else:
        current_timeline = cast("RawTimeline", current)
        start_frame_value = _call("Timeline.GetStartFrame", current_timeline.GetStartFrame)
        if not isinstance(start_frame_value, int) or isinstance(start_frame_value, bool):
            raise ResolveOperationError(
                "Timeline.GetStartFrame", f"expected int, got {start_frame_value!r}"
            )
        start_frame = start_frame_value
        start_timecode = _nonempty_text(
            "Timeline.GetStartTimecode",
            _call("Timeline.GetStartTimecode", current_timeline.GetStartTimecode),
        )

    unique_selectors = tuple(dict.fromkeys(selectors))
    resolved: list[ResolvedMediaItem] = []
    raw_by_id: dict[str, RawMediaPoolItem] = {}
    selector_by_id: dict[str, MediaSelector] = {}
    for selector in unique_selectors:
        item, raw = resolve_selector(
            session.root_folder, selector, project_frame_rate=timeline_frame_rate
        )
        prior = selector_by_id.get(item.media_id)
        if prior is not None and prior != selector:
            # Sharing one physical item is valid; retain one object but all selector metadata.
            pass
        selector_by_id[item.media_id] = selector
        raw_by_id[item.media_id] = raw
        resolved.append(item)

    snapshot = ResolveProjectSnapshot(
        project_id=project_id,
        project_name=project_name,
        timeline_frame_rate=timeline_frame_rate,
        timeline_start_frame=start_frame,
        timeline_start_timecode=start_timecode,
        timeline_names=tuple(timeline_names),
        media=tuple(resolved),
    )
    return snapshot, raw_by_id
