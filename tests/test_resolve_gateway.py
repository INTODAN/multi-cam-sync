from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import cast

import pytest

from multi_cam_sync.resolve.errors import (
    ResolveBuildError,
    ResolveOperationError,
    ResolvePreflightError,
)
from multi_cam_sync.resolve.gateway import DaVinciResolveGateway
from multi_cam_sync.resolve.protocols import MediaSelector, ResolveProjectSnapshot

from .fakes.resolve import (  # ty: ignore[unresolved-import]
    FakeTimelineItem,
    ResolveFake,
    make_resolve_fake,
)

MASTER = MediaSelector(("Masters",), "Master.wav", "master")
VIDEO = MediaSelector(("Media", "Multicam"), "Take 1 multicam", "video")


@dataclass(frozen=True)
class Marker:
    frame: int
    color: str
    name: str
    note: str = ""
    duration: int = 1
    custom_data: str = ""


@dataclass(frozen=True)
class Clip:
    media_id: str
    media_type: str
    track_index: int
    source_start_frame: int
    source_end_frame: int
    record_start_frame: int
    record_end_frame: int
    name: str
    color: str
    marker: Marker | None = None


@dataclass(frozen=True)
class Gap:
    record_start_frame: int
    record_end_frame: int


@dataclass(frozen=True)
class Plan:
    timeline_name: str
    expected_snapshot: ResolveProjectSnapshot
    audio_clips: tuple[Clip, ...]
    video_clips: tuple[Clip, ...]
    video_gaps: tuple[Gap, ...]
    markers: tuple[Marker, ...]
    valid: bool = True

    def validate(self) -> bool:
        return self.valid


def gateway(fake: ResolveFake) -> DaVinciResolveGateway:
    return DaVinciResolveGateway(connector=lambda: fake.session)


def make_plan(fake: ResolveFake, *, include_video: bool = True) -> Plan:
    snapshot = gateway(fake).snapshot([MASTER, VIDEO])
    audio = (
        Clip("master-id", "audio", 1, 0, 50, 100, 150, "Take 1 - 01", "Orange"),
        Clip("master-id", "audio", 1, 50, 100, 150, 200, "Take 2 - 02", "Teal"),
    )
    video = (
        (
            Clip(
                "video-id",
                "video",
                1,
                200,
                250,
                100,
                150,
                "Take 1 video - 01",
                "Orange",
                Marker(0, "Cyan", "Take 1", custom_data="segment-01"),
            ),
        )
        if include_video
        else ()
    )
    gaps = (Gap(150, 200),) if include_video else (Gap(100, 200),)
    markers = (Marker(150, "Cyan", "Cut 01", "Take 1 -> Take 2", 1, "cut-01"),)
    return Plan("Synced", snapshot, audio, video, gaps, markers)


def mutation_events(fake: ResolveFake) -> list[tuple[object, ...]]:
    names = {
        "MediaPool.CreateEmptyTimeline",
        "Project.SetCurrentTimeline",
        "Timeline.AddTrack",
        "MediaPool.AppendToTimeline",
        "TimelineItem.SetName",
        "TimelineItem.SetClipColor",
        "TimelineItem.AddMarker",
        "Timeline.AddMarker",
        "MediaPool.DeleteTimelines",
    }
    return [event for event in fake.events if event[0] in names]


def test_partial_video_build_uses_exact_native_append_dictionaries() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    fake.events.clear()

    result = gateway(fake).build_timeline(plan)

    assert result.verified is True
    assert result.audio_item_count == 2
    assert result.video_item_count == 1
    assert len(fake.media_pool.append_infos) == 3
    assert fake.media_pool.append_infos == [
        {
            "mediaPoolItem": fake.master,
            "startFrame": 0,
            "endFrame": 50,
            "mediaType": 2,
            "trackIndex": 1,
            "recordFrame": 100,
        },
        {
            "mediaPoolItem": fake.master,
            "startFrame": 50,
            "endFrame": 100,
            "mediaType": 2,
            "trackIndex": 1,
            "recordFrame": 150,
        },
        {
            "mediaPoolItem": fake.video,
            "startFrame": 200,
            "endFrame": 250,
            "mediaType": 1,
            "trackIndex": 1,
            "recordFrame": 100,
        },
    ]
    assert all(
        info["mediaType"] != 1 or info["recordFrame"] != 150
        for info in fake.media_pool.append_infos
    )
    assert not fake.media_pool.deleted


def test_gateway_accepts_the_real_partial_video_edit_plan() -> None:
    from multi_cam_sync.planning.frame_math import FrameRate
    from multi_cam_sync.planning.models import (
        MediaDescriptor,
        PlanningInputs,
        SegmentInput,
        VideoAssignment,
        VideoStatus,
    )
    from multi_cam_sync.planning.planner import create_edit_plan

    fake = make_resolve_fake()
    snapshot = gateway(fake).snapshot([MASTER, VIDEO])
    rate = FrameRate.parse("24000/1001")
    video_media = MediaDescriptor("video-id", "Take 1 multicam", Decimal("80"), rate)
    plan = create_edit_plan(
        PlanningInputs(
            timeline_name="Real plan",
            timeline_rate=rate,
            timeline_start_frame=100,
            master_media=MediaDescriptor(
                "master-id", "Master.wav", Decimal("40"), FrameRate.parse("24")
            ),
            segments=(
                SegmentInput("segment-0001", 0, "Take 1", "take 1", Decimal(0), Decimal(1)),
                SegmentInput("segment-0002", 1, "Take 2", "take 2", Decimal(1), Decimal(2)),
            ),
            enabled_take_keys=frozenset({"take 1"}),
            assignments={
                "segment-0001": VideoAssignment(
                    status=VideoStatus.MATCHED,
                    source_id="source-1",
                    media=video_media,
                    source_in_seconds=Decimal(0),
                    predicted_source_out_seconds=Decimal(1),
                )
            },
            expected_snapshot=snapshot,
        )
    )

    result = gateway(fake).build_timeline(plan)

    assert result.audio_item_count == 2
    assert result.video_item_count == 1
    assert [(gap.record_start_frame, gap.record_end_frame) for gap in plan.video_gaps] == [
        (124, 148)
    ]


def test_audio_only_plan_never_requires_or_appends_video_track() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake, include_video=False)
    fake.events.clear()

    result = gateway(fake).build_timeline(plan)

    assert result.video_item_count == 0
    assert ("Timeline.AddTrack", "video", None) not in fake.events
    assert [info["mediaType"] for info in fake.media_pool.append_infos] == [2, 2]


def test_full_video_plan_has_no_gap_or_placeholder_calls() -> None:
    fake = make_resolve_fake()
    partial = make_plan(fake)
    second_video = Clip(
        "video-id",
        "video",
        1,
        250,
        300,
        150,
        200,
        "Take 2 video - 02",
        "Teal",
    )
    plan = replace(partial, video_clips=(*partial.video_clips, second_video), video_gaps=())

    result = gateway(fake).build_timeline(plan)

    assert result.video_item_count == 2
    assert [
        info["recordFrame"] for info in fake.media_pool.append_infos if info["mediaType"] == 1
    ] == [
        100,
        150,
    ]


def test_preflight_existing_timeline_has_zero_mutation() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    fake.project.timelines[0].name = plan.timeline_name
    plan = Plan(
        plan.timeline_name,
        gateway(fake).snapshot([MASTER, VIDEO]),
        plan.audio_clips,
        plan.video_clips,
        plan.video_gaps,
        plan.markers,
    )
    fake.events.clear()

    with pytest.raises(ResolvePreflightError, match="already exists"):
        gateway(fake).build_timeline(plan)

    assert mutation_events(fake) == []


def test_stale_snapshot_has_zero_mutation() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    fake.project.name = "Changed Project"
    fake.events.clear()

    with pytest.raises(ResolvePreflightError, match="changed since analysis"):
        gateway(fake).build_timeline(plan)

    assert mutation_events(fake) == []


@pytest.mark.parametrize(
    ("change", "match"),
    [
        ("invalid", "validator rejected"),
        ("source_bounds", "beyond media duration"),
        ("unsupported_color", "unsupported Resolve clip color"),
        ("undeclared_gap", "undeclared gap"),
        ("gap_media", "must not carry a media_id"),
    ],
)
def test_all_plan_preflight_failures_have_zero_mutation(change: str, match: str) -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    if change == "invalid":
        plan = replace(plan, valid=False)
    elif change == "source_bounds":
        bad = Clip("master-id", "audio", 1, 0, 1001, 100, 150, "bad", "Orange")
        plan = Plan(plan.timeline_name, plan.expected_snapshot, (bad,), (), (Gap(100, 150),), ())
    elif change == "unsupported_color":
        bad = Clip("master-id", "audio", 1, 0, 50, 100, 150, "bad", "Cyan")
        plan = Plan(plan.timeline_name, plan.expected_snapshot, (bad,), (), (Gap(100, 150),), ())
    elif change == "undeclared_gap":
        plan = Plan(
            plan.timeline_name,
            plan.expected_snapshot,
            plan.audio_clips,
            (),
            (Gap(100, 140), Gap(150, 200)),
            (),
        )
    else:

        @dataclass(frozen=True)
        class BadGap:
            record_start_frame: int
            record_end_frame: int
            media_id: str

        plan = Plan(
            plan.timeline_name,
            plan.expected_snapshot,
            plan.audio_clips,
            (),
            (cast(Gap, BadGap(100, 200, "video-id")),),
            (),
        )
    fake.events.clear()

    with pytest.raises(ResolvePreflightError, match=match):
        gateway(fake).build_timeline(plan)

    assert mutation_events(fake) == []


@pytest.mark.parametrize(
    ("operation", "result"),
    [
        ("Project.SetCurrentTimeline", False),
        ("Timeline.AddTrack.audio", None),
        ("Timeline.AddTrack.video", False),
        ("MediaPool.AppendToTimeline", []),
        ("TimelineItem.SetName", False),
        ("TimelineItem.SetClipColor", None),
        ("TimelineItem.AddMarker", False),
        ("Timeline.AddMarker", None),
        ("Timeline.GetMarkers", False),
        ("TimelineItem.GetSourceStartTime.audio", False),
        ("TimelineItem.GetSourceEndTime.audio", None),
    ],
)
def test_each_post_creation_falsey_result_rolls_back_new_timeline_only(
    operation: str, result: object
) -> None:
    fake = make_resolve_fake(failures={operation: result})
    plan = make_plan(fake)
    preexisting = fake.project.timelines[0]
    fake.events.clear()

    with pytest.raises(ResolveBuildError) as caught:
        gateway(fake).build_timeline(plan)

    assert caught.value.rollback.succeeded is True
    assert len(fake.media_pool.deleted) == 1
    assert len(fake.media_pool.deleted[0]) == 1
    assert fake.media_pool.deleted[0][0] is not preexisting
    assert preexisting in fake.project.timelines


def test_create_failure_does_not_attempt_rollback() -> None:
    fake = make_resolve_fake(failures={"MediaPool.CreateEmptyTimeline": None})
    plan = make_plan(fake)
    fake.events.clear()

    with pytest.raises(ResolveOperationError, match="CreateEmptyTimeline"):
        gateway(fake).build_timeline(plan)

    assert fake.media_pool.deleted == []


def test_rollback_failure_is_attached_to_original_error() -> None:
    fake = make_resolve_fake(
        failures={"TimelineItem.SetName": False, "MediaPool.DeleteTimelines": False}
    )
    plan = make_plan(fake)

    with pytest.raises(ResolveBuildError) as caught:
        gateway(fake).build_timeline(plan)

    assert caught.value.operation == "TimelineItem.SetName"
    assert caught.value.rollback.attempted is True
    assert caught.value.rollback.succeeded is False
    assert "DeleteTimelines returned False" in str(caught.value)


def test_readback_rejects_filler_in_intentional_gap_and_rolls_back() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    fake.media_pool.inject_video_filler = True

    with pytest.raises(ResolveBuildError, match="expected 1 video items, got 2"):
        gateway(fake).build_timeline(plan)

    assert fake.media_pool.deleted


def test_readback_rejects_video_overlap() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)

    def malformed_items() -> list[FakeTimelineItem]:
        timeline = fake.project.current_timeline
        assert timeline is not None
        items = list(timeline.items["video"])
        if items:
            items[0].record_start = 149
        return items

    fake.failures["Timeline.GetItemListInTrack.video"] = malformed_items

    with pytest.raises(ResolveBuildError, match="record frame tuple expected"):
        gateway(fake).build_timeline(plan)


def test_audio_source_frame_getters_may_truncate_exact_times_by_one_frame() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    source_starts = iter((0, 49))
    fake.failures["TimelineItem.GetSourceStartFrame.audio"] = lambda: next(source_starts)

    result = gateway(fake).build_timeline(plan)

    assert result.verified is True
    assert not fake.media_pool.deleted


def test_audio_source_time_readback_rejects_a_real_one_frame_shift() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    source_start_times = iter((0.0, 49 / 24))
    fake.failures["TimelineItem.GetSourceStartTime.audio"] = lambda: next(source_start_times)

    with pytest.raises(ResolveBuildError, match="start expected source frame 50"):
        gateway(fake).build_timeline(plan)

    assert fake.media_pool.deleted


@pytest.mark.parametrize(
    ("getter", "value"),
    [
        ("TimelineItem.GetSourceStartFrame.video", 199),
        ("TimelineItem.GetSourceEndFrame.video", 249),
    ],
)
def test_video_source_frame_getters_may_truncate_by_one_frame(getter: str, value: int) -> None:
    fake = make_resolve_fake(failures={getter: value})
    plan = make_plan(fake)

    result = gateway(fake).build_timeline(plan)

    assert result.verified is True
    assert not fake.media_pool.deleted


@pytest.mark.parametrize(
    ("getter", "value"),
    [
        ("TimelineItem.GetSourceStartFrame.video", 198),
        ("TimelineItem.GetSourceEndFrame.video", 248),
    ],
)
def test_video_source_frame_getters_reject_more_than_one_frame_truncation(
    getter: str, value: int
) -> None:
    fake = make_resolve_fake(failures={getter: value})
    plan = make_plan(fake)

    with pytest.raises(ResolveBuildError, match="source frame tuple expected"):
        gateway(fake).build_timeline(plan)

    assert fake.media_pool.deleted


@pytest.mark.parametrize("suffix", ["Angle 1", "Video 2"])
def test_multicam_video_name_keeps_exact_label_with_resolve_track_suffix(suffix: str) -> None:
    fake = make_resolve_fake(
        failures={"TimelineItem.GetName.video": f"Take 1 video - 01 - {suffix}"}
    )
    plan = make_plan(fake)

    result = gateway(fake).build_timeline(plan)

    assert result.verified is True
    assert not fake.media_pool.deleted


def test_multicam_video_name_rejects_a_different_base_label() -> None:
    fake = make_resolve_fake(failures={"TimelineItem.GetName.video": "Wrong - Video 2"})
    plan = make_plan(fake)

    with pytest.raises(ResolveBuildError, match="item name expected"):
        gateway(fake).build_timeline(plan)

    assert fake.media_pool.deleted


def test_call_order_preflights_before_creation_and_verifies_after_markers() -> None:
    fake = make_resolve_fake()
    plan = make_plan(fake)
    fake.events.clear()

    gateway(fake).build_timeline(plan)

    names = [event[0] for event in fake.events]
    creation = names.index("MediaPool.CreateEmptyTimeline")
    assert names.index("MediaPoolItem.GetClipProperty") < creation
    assert names.index("Project.SetCurrentTimeline") > creation
    assert names.index("MediaPool.AppendToTimeline") > names.index("Timeline.AddTrack")
    assert names.index("Timeline.GetItemListInTrack") > names.index("Timeline.AddMarker")
