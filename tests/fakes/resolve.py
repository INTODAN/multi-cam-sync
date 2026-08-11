"""Strict, deterministic DaVinci Resolve API fakes shared by adapter tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, cast


def _result(failures: dict[str, object], operation: str, default: object) -> object:
    outcome = failures.get(operation, default)
    if isinstance(outcome, BaseException):
        raise outcome
    if callable(outcome):
        return cast("Callable[[], object]", outcome)()
    return outcome


@dataclass
class FakeMediaItem:
    name: str
    media_id: str
    properties: dict[str, object]
    events: list[tuple[object, ...]]

    def GetName(self) -> str:
        self.events.append(("MediaPoolItem.GetName", self.media_id))
        return self.name

    def GetMediaId(self) -> str:
        self.events.append(("MediaPoolItem.GetMediaId", self.media_id))
        return self.media_id

    def GetClipProperty(self, property_name: str | None = None) -> object:
        self.events.append(("MediaPoolItem.GetClipProperty", self.media_id, property_name))
        if property_name is None:
            return dict(self.properties)
        return self.properties.get(property_name, "")


@dataclass
class FakeFolder:
    name: str
    events: list[tuple[object, ...]]
    clips: list[FakeMediaItem] = field(default_factory=list)
    folders: list[FakeFolder] = field(default_factory=list)

    def GetName(self) -> str:
        self.events.append(("Folder.GetName", self.name))
        return self.name

    def GetClipList(self) -> list[FakeMediaItem]:
        self.events.append(("Folder.GetClipList", self.name))
        return list(self.clips)

    def GetSubFolderList(self) -> list[FakeFolder]:
        self.events.append(("Folder.GetSubFolderList", self.name))
        return list(self.folders)


@dataclass
class FakeTimelineItem:
    media: FakeMediaItem
    source_start: int
    source_end: int
    record_start: int
    track_type: str
    events: list[tuple[object, ...]]
    failures: dict[str, object]
    track_index: int = 1
    name: str = ""
    color: str = ""
    markers: dict[float, dict[str, object]] = field(default_factory=dict)

    @property
    def record_end(self) -> int:
        return self.record_start + (self.source_end - self.source_start)

    def SetName(self, name: str) -> object:
        self.events.append(("TimelineItem.SetName", self.track_type, name))
        result = _result(self.failures, "TimelineItem.SetName", True)
        if result is True:
            self.name = name
        return result

    def SetClipColor(self, color: str) -> object:
        self.events.append(("TimelineItem.SetClipColor", self.track_type, color))
        result = _result(self.failures, "TimelineItem.SetClipColor", True)
        if result is True:
            self.color = color
        return result

    def GetClipColor(self) -> str:
        self.events.append(("TimelineItem.GetClipColor", self.track_type))
        return self.color

    def AddMarker(
        self,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        custom_data: str = "",
    ) -> object:
        self.events.append(
            ("TimelineItem.AddMarker", frame, color, name, note, duration, custom_data)
        )
        result = _result(self.failures, "TimelineItem.AddMarker", True)
        if result is True:
            self.markers[float(frame)] = {
                "color": color,
                "name": name,
                "note": note,
                "duration": float(duration),
                "customData": custom_data,
            }
        return result

    def GetMarkers(self) -> dict[float, dict[str, object]]:
        self.events.append(("TimelineItem.GetMarkers", self.track_type))
        return dict(self.markers)

    def GetName(self) -> str:
        self.events.append(("TimelineItem.GetName", self.track_type))
        return cast(
            "str",
            _result(self.failures, f"TimelineItem.GetName.{self.track_type}", self.name),
        )

    def GetStart(self, subframe_precision: bool = False) -> int:
        self.events.append(("TimelineItem.GetStart", self.track_type, subframe_precision))
        return self.record_start

    def GetEnd(self, subframe_precision: bool = False) -> int:
        self.events.append(("TimelineItem.GetEnd", self.track_type, subframe_precision))
        return self.record_end

    def GetSourceStartFrame(self) -> int:
        self.events.append(("TimelineItem.GetSourceStartFrame", self.track_type))
        return cast(
            "int",
            _result(
                self.failures,
                f"TimelineItem.GetSourceStartFrame.{self.track_type}",
                self.source_start,
            ),
        )

    def GetSourceEndFrame(self) -> int:
        self.events.append(("TimelineItem.GetSourceEndFrame", self.track_type))
        return cast(
            "int",
            _result(
                self.failures,
                f"TimelineItem.GetSourceEndFrame.{self.track_type}",
                self.source_end,
            ),
        )

    def GetSourceStartTime(self) -> object:
        self.events.append(("TimelineItem.GetSourceStartTime", self.track_type))
        return _result(
            self.failures,
            f"TimelineItem.GetSourceStartTime.{self.track_type}",
            self.source_start / 24,
        )

    def GetSourceEndTime(self) -> object:
        self.events.append(("TimelineItem.GetSourceEndTime", self.track_type))
        return _result(
            self.failures,
            f"TimelineItem.GetSourceEndTime.{self.track_type}",
            self.source_end / 24,
        )

    def GetMediaPoolItem(self) -> FakeMediaItem:
        self.events.append(("TimelineItem.GetMediaPoolItem", self.track_type))
        return self.media

    def GetTrackTypeAndIndex(self) -> list[object]:
        self.events.append(("TimelineItem.GetTrackTypeAndIndex", self.track_type))
        return [self.track_type, self.track_index]


@dataclass
class FakeTimeline:
    name: str
    timeline_id: str
    events: list[tuple[object, ...]]
    failures: dict[str, object]
    start_frame: int = 100
    start_timecode: str = "00:00:04:04"
    track_counts: dict[str, int] = field(
        default_factory=lambda: {"audio": 0, "video": 0, "subtitle": 0}
    )
    items: dict[str, list[FakeTimelineItem]] = field(
        default_factory=lambda: {"audio": [], "video": []}
    )
    markers: dict[float, dict[str, object]] = field(default_factory=dict)

    def GetName(self) -> str:
        self.events.append(("Timeline.GetName", self.name))
        return self.name

    def GetUniqueId(self) -> str:
        self.events.append(("Timeline.GetUniqueId", self.timeline_id))
        return self.timeline_id

    def GetStartFrame(self) -> int:
        self.events.append(("Timeline.GetStartFrame", self.name))
        return self.start_frame

    def GetEndFrame(self) -> int:
        self.events.append(("Timeline.GetEndFrame", self.name))
        all_items = self.items["audio"] + self.items["video"]
        return max((item.record_end for item in all_items), default=self.start_frame)

    def GetStartTimecode(self) -> str:
        self.events.append(("Timeline.GetStartTimecode", self.name))
        return self.start_timecode

    def GetTrackCount(self, track_type: str) -> int:
        if track_type not in self.track_counts:
            raise AssertionError(f"unexpected track type: {track_type}")
        self.events.append(("Timeline.GetTrackCount", track_type))
        return self.track_counts[track_type]

    def AddTrack(self, track_type: str, sub_track_type: str | None = None) -> object:
        if track_type not in {"audio", "video"}:
            raise AssertionError(f"unexpected AddTrack type: {track_type}")
        if track_type == "audio" and sub_track_type != "stereo":
            raise AssertionError(f"unexpected audio subtype: {sub_track_type}")
        if track_type == "video" and sub_track_type is not None:
            raise AssertionError("video AddTrack must not pass a subtype")
        self.events.append(("Timeline.AddTrack", track_type, sub_track_type))
        result = _result(self.failures, f"Timeline.AddTrack.{track_type}", True)
        if result is True:
            self.track_counts[track_type] += 1
        return result

    def GetItemListInTrack(self, track_type: str, index: int) -> object:
        if track_type not in self.items or index != 1:
            raise AssertionError(f"unexpected track lookup: {track_type} {index}")
        self.events.append(("Timeline.GetItemListInTrack", track_type, index))
        return _result(
            self.failures,
            f"Timeline.GetItemListInTrack.{track_type}",
            list(self.items[track_type]),
        )

    def AddMarker(
        self,
        frame: int,
        color: str,
        name: str,
        note: str,
        duration: int,
        custom_data: str = "",
    ) -> object:
        self.events.append(("Timeline.AddMarker", frame, color, name, note, duration, custom_data))
        result = _result(self.failures, "Timeline.AddMarker", True)
        if result is True:
            self.markers[float(frame)] = {
                "color": color,
                "name": name,
                "note": note,
                "duration": float(duration),
                "customData": custom_data,
            }
        return result

    def GetMarkers(self) -> object:
        self.events.append(("Timeline.GetMarkers", self.name))
        return _result(self.failures, "Timeline.GetMarkers", dict(self.markers))


@dataclass
class FakeMediaPool:
    root: FakeFolder
    events: list[tuple[object, ...]]
    failures: dict[str, object]
    project: FakeProject | None = None
    deleted: list[list[FakeTimeline]] = field(default_factory=list)
    append_infos: list[dict[str, object]] = field(default_factory=list)
    inject_video_filler: bool = False

    def GetRootFolder(self) -> object:
        self.events.append(("MediaPool.GetRootFolder",))
        return _result(self.failures, "MediaPool.GetRootFolder", self.root)

    def CreateEmptyTimeline(self, name: str) -> object:
        self.events.append(("MediaPool.CreateEmptyTimeline", name))
        result = _result(self.failures, "MediaPool.CreateEmptyTimeline", None)
        if "MediaPool.CreateEmptyTimeline" in self.failures:
            return result
        timeline = FakeTimeline(name, f"timeline-{name}", self.events, self.failures)
        if self.project is None:
            raise AssertionError("media pool has no project")
        self.project.timelines.append(timeline)
        return timeline

    def AppendToTimeline(self, clips: list[dict[str, object]]) -> object:
        self.events.append(("MediaPool.AppendToTimeline", clips))
        if len(clips) != 1:
            raise AssertionError("fake only accepts one clipInfo per append")
        expected_keys = {
            "mediaPoolItem",
            "startFrame",
            "endFrame",
            "mediaType",
            "trackIndex",
            "recordFrame",
        }
        info = clips[0]
        if set(info) != expected_keys:
            raise AssertionError(f"unexpected clipInfo keys: {set(info)}")
        self.append_infos.append(dict(info))
        failure = _result(self.failures, "MediaPool.AppendToTimeline", ...)
        if failure is not ...:
            return failure
        if self.project is None or self.project.current_timeline is None:
            raise AssertionError("AppendToTimeline requires a current timeline")
        media_type = info["mediaType"]
        if media_type not in {1, 2} or info["trackIndex"] != 1:
            raise AssertionError(f"unexpected media type/track: {media_type}/{info['trackIndex']}")
        track_type = "video" if media_type == 1 else "audio"
        media = info["mediaPoolItem"]
        source_start = info["startFrame"]
        source_end = info["endFrame"]
        record_start = info["recordFrame"]
        if not isinstance(media, FakeMediaItem):
            raise AssertionError("mediaPoolItem must be a FakeMediaItem")
        if any(
            not isinstance(frame, int) or isinstance(frame, bool)
            for frame in (source_start, source_end, record_start)
        ):
            raise AssertionError("clipInfo frames must be integers")
        item = FakeTimelineItem(
            media=media,
            source_start=cast("int", source_start),
            source_end=cast("int", source_end),
            record_start=cast("int", record_start),
            track_type=track_type,
            events=self.events,
            failures=self.failures,
        )
        self.project.current_timeline.items[track_type].append(item)
        if self.inject_video_filler and track_type == "video":
            self.project.current_timeline.items["video"].append(
                FakeTimelineItem(
                    media=item.media,
                    source_start=0,
                    source_end=1,
                    record_start=item.record_end,
                    track_type="video",
                    events=self.events,
                    failures=self.failures,
                    name="filler",
                    color="Blue",
                )
            )
        return [item]

    def DeleteTimelines(self, timelines: list[FakeTimeline]) -> object:
        self.events.append(("MediaPool.DeleteTimelines", timelines))
        self.deleted.append(list(timelines))
        result = _result(self.failures, "MediaPool.DeleteTimelines", True)
        if result is True and self.project is not None:
            for timeline in timelines:
                if timeline in self.project.timelines:
                    self.project.timelines.remove(timeline)
        return result


@dataclass
class FakeProject:
    name: str
    project_id: str
    events: list[tuple[object, ...]]
    failures: dict[str, object]
    timelines: list[FakeTimeline]
    current_timeline: FakeTimeline | None
    settings: dict[str, object]
    media_pool: FakeMediaPool | None = None

    def GetMediaPool(self) -> object:
        self.events.append(("Project.GetMediaPool",))
        return _result(self.failures, "Project.GetMediaPool", self.media_pool)

    def GetTimelineCount(self) -> int:
        self.events.append(("Project.GetTimelineCount",))
        return len(self.timelines)

    def GetTimelineByIndex(self, index: int) -> FakeTimeline:
        self.events.append(("Project.GetTimelineByIndex", index))
        return self.timelines[index - 1]

    def GetCurrentTimeline(self) -> FakeTimeline | None:
        self.events.append(("Project.GetCurrentTimeline",))
        return self.current_timeline

    def SetCurrentTimeline(self, timeline: FakeTimeline) -> object:
        self.events.append(("Project.SetCurrentTimeline", timeline))
        result = _result(self.failures, "Project.SetCurrentTimeline", True)
        if result is True:
            self.current_timeline = timeline
        return result

    def GetName(self) -> str:
        self.events.append(("Project.GetName",))
        return self.name

    def GetUniqueId(self) -> str:
        self.events.append(("Project.GetUniqueId",))
        return self.project_id

    def GetSetting(self, setting_name: str) -> object:
        if setting_name not in {"timelineFrameRate", "timelineStartTimecode"}:
            raise AssertionError(f"unexpected setting: {setting_name}")
        self.events.append(("Project.GetSetting", setting_name))
        return self.settings.get(setting_name, "")


@dataclass
class FakeProjectManager:
    project: FakeProject | None
    events: list[tuple[object, ...]]
    failures: dict[str, object]

    def GetCurrentProject(self) -> object:
        self.events.append(("ProjectManager.GetCurrentProject",))
        return _result(self.failures, "ProjectManager.GetCurrentProject", self.project)


@dataclass
class FakeResolve:
    manager: FakeProjectManager | None
    events: list[tuple[object, ...]]
    failures: dict[str, object]

    def GetProjectManager(self) -> object:
        self.events.append(("Resolve.GetProjectManager",))
        return _result(self.failures, "Resolve.GetProjectManager", self.manager)


@dataclass
class FakeResolveModule:
    resolve: FakeResolve | None
    events: list[tuple[object, ...]]
    failures: dict[str, object]

    def scriptapp(self, name: str) -> object:
        if name != "Resolve":
            raise AssertionError(f"unexpected app name: {name}")
        self.events.append(("scriptapp", name))
        return _result(self.failures, "scriptapp", self.resolve)


@dataclass
class ResolveFake:
    session: Any
    module: FakeResolveModule
    project: FakeProject
    media_pool: FakeMediaPool
    master: FakeMediaItem
    video: FakeMediaItem
    events: list[tuple[object, ...]]
    failures: dict[str, object]


def make_resolve_fake(*, failures: Mapping[str, object] | None = None) -> ResolveFake:
    """Return a fully wired project with exact Masters and Media/Multicam folders."""

    from multi_cam_sync.resolve.connection import ResolveSession
    from multi_cam_sync.resolve.protocols import (
        RawFolder,
        RawMediaPool,
        RawProject,
        RawProjectManager,
        RawResolve,
    )

    event_log: list[tuple[object, ...]] = []
    configured_failures = dict(failures or {})
    master = FakeMediaItem(
        "Master.wav",
        "master-id",
        {"File Path": "/media/Master.wav", "Frames": "1000", "FPS": "24"},
        event_log,
    )
    video = FakeMediaItem(
        "Take 1 multicam",
        "video-id",
        {"FrameCount": "2000", "Frame Rate": "24000/1001"},
        event_log,
    )
    masters = FakeFolder("Masters", event_log, clips=[master])
    multicam = FakeFolder("Multicam", event_log, clips=[video])
    media = FakeFolder("Media", event_log, folders=[multicam])
    root = FakeFolder("Root", event_log, folders=[masters, media])
    baseline = FakeTimeline("Existing", "timeline-existing", event_log, configured_failures)
    pool = FakeMediaPool(root, event_log, configured_failures)
    project = FakeProject(
        "Test Project",
        "project-id",
        event_log,
        configured_failures,
        [baseline],
        baseline,
        {"timelineFrameRate": "24000/1001", "timelineStartTimecode": "00:00:04:04"},
        pool,
    )
    pool.project = project
    manager = FakeProjectManager(project, event_log, configured_failures)
    resolve = FakeResolve(manager, event_log, configured_failures)
    module = FakeResolveModule(resolve, event_log, configured_failures)
    session = ResolveSession(
        cast("RawResolve", resolve),
        cast("RawProjectManager", manager),
        cast("RawProject", project),
        cast("RawMediaPool", pool),
        cast("RawFolder", root),
    )
    return ResolveFake(
        session=session,
        module=module,
        project=project,
        media_pool=pool,
        master=master,
        video=video,
        events=event_log,
        failures=configured_failures,
    )
