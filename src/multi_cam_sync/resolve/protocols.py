"""Typed contracts at the otherwise dynamic DaVinci Resolve boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True, order=True)
class MediaSelector:
    """An exact Media Pool folder path and exact item name."""

    folder: tuple[str, ...]
    name: str
    kind: str

    def __post_init__(self) -> None:
        if not self.folder or any(not component.strip() for component in self.folder):
            raise ValueError("media selector folder must contain non-empty components")
        if not self.name.strip():
            raise ValueError("media selector name must not be empty")
        if self.kind not in {"master", "video"}:
            raise ValueError("media selector kind must be 'master' or 'video'")

    @classmethod
    def from_folder(cls, folder: str, name: str, kind: str) -> MediaSelector:
        components = tuple(
            part.strip() for part in folder.replace("\\", "/").split("/") if part.strip()
        )
        return cls(folder=components, name=name, kind=kind)

    @property
    def display(self) -> str:
        return f"{'/'.join(self.folder)}/{self.name}"


@dataclass(frozen=True, slots=True)
class ResolvedMediaItem:
    """Stable metadata read from a uniquely selected Media Pool item."""

    media_id: str
    selector: MediaSelector
    name: str
    file_path: Path | None
    duration_frames: int
    frame_rate: Decimal
    raw_properties: Mapping[str, str] = field(compare=False, repr=False)

    @property
    def kind(self) -> str:
        return self.selector.kind


@dataclass(frozen=True, slots=True)
class ResolveProjectSnapshot:
    """Read-only project/media state used to reject stale build reports."""

    project_id: str
    project_name: str
    timeline_frame_rate: Decimal
    timeline_start_frame: int | None
    timeline_start_timecode: str
    timeline_names: tuple[str, ...]
    media: tuple[ResolvedMediaItem, ...]

    @property
    def media_by_id(self) -> Mapping[str, ResolvedMediaItem]:
        return {item.media_id: item for item in self.media}

    @property
    def selectors(self) -> tuple[MediaSelector, ...]:
        return tuple(item.selector for item in self.media)

    @property
    def fingerprint(self) -> tuple[object, ...]:
        media = tuple(
            (
                item.media_id,
                item.selector,
                str(item.file_path) if item.file_path is not None else None,
                item.duration_frames,
                item.frame_rate,
            )
            for item in self.media
        )
        return (
            self.project_id,
            self.project_name,
            self.timeline_frame_rate,
            self.timeline_start_frame,
            self.timeline_start_timecode,
            self.timeline_names,
            media,
        )


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Successful, verified timeline build."""

    timeline_id: str
    timeline_name: str
    audio_item_count: int
    video_item_count: int
    marker_count: int
    verified: bool = True


class ClipMarkerLike(Protocol):
    @property
    def frame(self) -> int: ...

    @property
    def color(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def note(self) -> str: ...

    @property
    def duration(self) -> int: ...

    @property
    def custom_data(self) -> str: ...


class PlannedClipLike(Protocol):
    @property
    def media_id(self) -> str: ...

    @property
    def media_type(self) -> str: ...

    @property
    def track_index(self) -> int: ...

    @property
    def source_start_frame(self) -> int: ...

    @property
    def source_end_frame(self) -> int: ...

    @property
    def record_start_frame(self) -> int: ...

    @property
    def record_end_frame(self) -> int: ...

    @property
    def name(self) -> str: ...

    @property
    def color(self) -> str: ...


class VideoGapLike(Protocol):
    @property
    def record_start_frame(self) -> int: ...

    @property
    def record_end_frame(self) -> int: ...


class TimelineMarkerLike(Protocol):
    @property
    def frame(self) -> int: ...

    @property
    def color(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def note(self) -> str: ...

    @property
    def duration(self) -> int: ...

    @property
    def custom_data(self) -> str: ...


class EditPlanLike(Protocol):
    @property
    def timeline_name(self) -> str: ...

    @property
    def expected_snapshot(self) -> object: ...

    @property
    def audio_clips(self) -> Sequence[PlannedClipLike]: ...

    @property
    def video_clips(self) -> Sequence[PlannedClipLike]: ...

    @property
    def video_gaps(self) -> Sequence[VideoGapLike]: ...

    @property
    def markers(self) -> Sequence[TimelineMarkerLike]: ...

    def validate(self) -> object: ...


class ResolveGateway(Protocol):
    """Public Resolve boundary consumed by CLI orchestration."""

    def snapshot(self, selectors: Iterable[MediaSelector]) -> ResolveProjectSnapshot: ...

    def build_timeline(self, plan: EditPlanLike) -> BuildResult: ...


# Raw API protocols intentionally stop dynamic values from spreading into the app.
class RawTimelineItem(Protocol):
    def SetName(self, name: str) -> bool: ...

    def SetClipColor(self, color: str) -> bool: ...

    def GetClipColor(self) -> str: ...

    def AddMarker(
        self,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        custom_data: str = "",
    ) -> bool: ...

    def GetMarkers(self) -> Mapping[object, object]: ...

    def GetName(self) -> str: ...

    def GetStart(self, subframe_precision: bool = False) -> int | float: ...

    def GetEnd(self, subframe_precision: bool = False) -> int | float: ...

    def GetSourceStartFrame(self) -> int: ...

    def GetSourceEndFrame(self) -> int: ...

    def GetMediaPoolItem(self) -> RawMediaPoolItem: ...

    def GetTrackTypeAndIndex(self) -> Sequence[object]: ...


class RawMediaPoolItem(Protocol):
    def GetName(self) -> str: ...

    def GetMediaId(self) -> str: ...

    def GetClipProperty(self, property_name: str | None = None) -> object: ...


class RawFolder(Protocol):
    def GetName(self) -> str: ...

    def GetClipList(self) -> Sequence[RawMediaPoolItem]: ...

    def GetSubFolderList(self) -> Sequence[RawFolder]: ...


class RawTimeline(Protocol):
    def GetName(self) -> str: ...

    def GetUniqueId(self) -> str: ...

    def GetStartFrame(self) -> int: ...

    def GetEndFrame(self) -> int: ...

    def GetStartTimecode(self) -> str: ...

    def GetTrackCount(self, track_type: str) -> int: ...

    def AddTrack(self, track_type: str, sub_track_type: str | None = None) -> bool: ...

    def GetItemListInTrack(self, track_type: str, index: int) -> Sequence[RawTimelineItem]: ...

    def AddMarker(
        self,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        custom_data: str = "",
    ) -> bool: ...

    def GetMarkers(self) -> Mapping[object, object]: ...


class RawMediaPool(Protocol):
    def GetRootFolder(self) -> RawFolder: ...

    def CreateEmptyTimeline(self, name: str) -> RawTimeline: ...

    def AppendToTimeline(self, clips: list[dict[str, object]]) -> Sequence[RawTimelineItem]: ...

    def DeleteTimelines(self, timelines: list[RawTimeline]) -> bool: ...


class RawProject(Protocol):
    def GetMediaPool(self) -> RawMediaPool: ...

    def GetTimelineCount(self) -> int: ...

    def GetTimelineByIndex(self, index: int) -> RawTimeline: ...

    def GetCurrentTimeline(self) -> RawTimeline | None: ...

    def SetCurrentTimeline(self, timeline: RawTimeline) -> bool: ...

    def GetName(self) -> str: ...

    def GetUniqueId(self) -> str: ...

    def GetSetting(self, setting_name: str) -> object: ...


class RawProjectManager(Protocol):
    def GetCurrentProject(self) -> RawProject: ...


class RawResolve(Protocol):
    def GetProjectManager(self) -> RawProjectManager: ...


class ResolveScriptModule(Protocol):
    def scriptapp(self, name: str) -> RawResolve | None: ...


ModuleLoader = Callable[[str], object]
