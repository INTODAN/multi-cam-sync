from dataclasses import replace
from decimal import Decimal

import pytest

from multi_cam_sync.planning import (
    FrameRate,
    MediaDescriptor,
    PlanningError,
    PlanningInputs,
    SegmentInput,
    VideoAssignment,
    VideoStatus,
    create_edit_plan,
    seconds_to_frame,
    validate_edit_plan,
)
from multi_cam_sync.planning.colors import RESOLVE_COLORS, assign_take_colors


def _segments() -> tuple[SegmentInput, ...]:
    return (
        SegmentInput("segment-0001", 0, "Take A", "take a", Decimal("0"), Decimal("2")),
        SegmentInput("segment-0002", 1, "Take B", "take b", Decimal("2"), Decimal("5")),
        SegmentInput("segment-0003", 2, "Take C", "take c", Decimal("5"), Decimal("7.5")),
        SegmentInput("segment-0004", 3, "Take A", "take a", Decimal("7.5"), Decimal("10")),
    )


def _media(media_id: str, duration: str = "30", rate: str = "24") -> MediaDescriptor:
    return MediaDescriptor(media_id, media_id, Decimal(duration), FrameRate.parse(rate))


def _matched(segment_id: str, source_in: str) -> tuple[str, VideoAssignment]:
    duration = next(
        segment.end_seconds - segment.start_seconds
        for segment in _segments()
        if segment.id == segment_id
    )
    source_in_decimal = Decimal(source_in)
    return (
        segment_id,
        VideoAssignment(
            status=VideoStatus.MATCHED,
            source_id="source-a",
            media=_media("video-a"),
            source_in_seconds=source_in_decimal,
            predicted_source_out_seconds=source_in_decimal + duration,
            method="dtw",
        ),
    )


def _inputs(*, enabled: frozenset[str] = frozenset(), assignments=None) -> PlanningInputs:
    return PlanningInputs(
        timeline_name="Synced",
        timeline_rate=FrameRate.parse("24000/1001"),
        timeline_start_frame=86400,
        master_media=_media("master", duration="10", rate="24000/1001"),
        segments=_segments(),
        enabled_take_keys=enabled,
        assignments={} if assignments is None else assignments,
        expected_snapshot="project-fingerprint",
    )


@pytest.mark.parametrize(
    ("rate", "seconds", "expected"),
    [
        ("24", "0.5", 12),
        ("25", "0.02", 1),
        ("30000/1001", "1", 30),
        ("24000/1001", "10", 240),
    ],
)
def test_seconds_to_frame(rate: str, seconds: str, expected: int) -> None:
    assert seconds_to_frame(Decimal(seconds), FrameRate.parse(rate)) == expected


def test_frame_rate_normalizes_and_rejects_invalid() -> None:
    assert str(FrameRate(48000, 2002)) == "24000/1001"
    assert FrameRate.parse(23.976).numerator == 2997
    assert FrameRate.parse(Decimal(24_000) / Decimal(1_001)) == FrameRate(24_000, 1_001)
    with pytest.raises(ValueError, match="positive"):
        FrameRate(0)


def test_partial_video_places_every_enabled_take_occurrence() -> None:
    assignments = dict((_matched("segment-0001", "3"), _matched("segment-0004", "12")))
    plan = create_edit_plan(_inputs(enabled=frozenset({"take a"}), assignments=assignments))

    assert len(plan.audio_clips) == 4
    assert [clip.segment_id for clip in plan.video_clips] == ["segment-0001", "segment-0004"]
    assert [gap.segment_id for gap in plan.video_gaps] == ["segment-0002", "segment-0003"]
    assert plan.audio_clips[0].record_start_frame == 86400
    assert all(clip.media_type == "video" for clip in plan.video_clips)
    assert all(segment.video_status is VideoStatus.NOT_PROVIDED for segment in plan.segments[1:3])
    assert len(plan.markers) == 3
    assert plan.expected_snapshot == "project-fingerprint"


def test_zero_sources_creates_audio_and_explicit_gaps_only() -> None:
    plan = create_edit_plan(_inputs())
    assert len(plan.audio_clips) == 4
    assert plan.video_clips == ()
    assert len(plan.video_gaps) == 4
    assert plan.audio_clips[-1].record_end_frame == 86400 + seconds_to_frame(
        Decimal(10), FrameRate.parse("24000/1001")
    )


def test_enabled_take_requires_safe_match_for_every_occurrence() -> None:
    assignments = dict([_matched("segment-0001", "3")])
    with pytest.raises(PlanningError, match="segment-0004 has no match"):
        create_edit_plan(_inputs(enabled=frozenset({"take a"}), assignments=assignments))

    assignments["segment-0004"] = VideoAssignment(
        status=VideoStatus.UNSAFE,
        blockers=("ambiguous",),
    )
    with pytest.raises(PlanningError, match="unsafe: ambiguous"):
        create_edit_plan(_inputs(enabled=frozenset({"take a"}), assignments=assignments))


def test_not_provided_cannot_hide_enabled_take_failure() -> None:
    assignments = dict([_matched("segment-0001", "3")])
    assignments["segment-0004"] = VideoAssignment.not_provided()
    with pytest.raises(PlanningError, match="cannot be not_provided"):
        create_edit_plan(_inputs(enabled=frozenset({"take a"}), assignments=assignments))


def test_drift_and_source_duration_are_enforced() -> None:
    first_id, first = _matched("segment-0001", "29")
    second_id, second = _matched("segment-0004", "12")
    with pytest.raises(PlanningError, match="exceeds source media duration"):
        create_edit_plan(
            _inputs(enabled=frozenset({"take a"}), assignments={first_id: first, second_id: second})
        )

    first = replace(
        first, source_in_seconds=Decimal("3"), predicted_source_out_seconds=Decimal("5.2")
    )
    with pytest.raises(PlanningError, match="two-frame drift"):
        create_edit_plan(
            _inputs(enabled=frozenset({"take a"}), assignments={first_id: first, second_id: second})
        )


def test_master_boundaries_never_accumulate_gaps() -> None:
    segments = tuple(
        SegmentInput(
            f"segment-{index + 1:04d}",
            index,
            f"Take {index}",
            f"take {index}",
            Decimal(index) / Decimal(10),
            Decimal(index + 1) / Decimal(10),
        )
        for index in range(100)
    )
    inputs = replace(
        _inputs(),
        timeline_rate=FrameRate.parse("30000/1001"),
        master_media=_media("master", duration="10", rate="30000/1001"),
        segments=segments,
    )
    plan = create_edit_plan(inputs)
    for left, right in zip(plan.audio_clips, plan.audio_clips[1:], strict=False):
        assert left.record_end_frame == right.record_start_frame


@pytest.mark.parametrize(("source_rate", "expected_duration"), [("24", 119), ("30", 149)])
def test_video_source_duration_reproduces_independently_rounded_record_span(
    source_rate: str, expected_duration: int
) -> None:
    segments = (
        SegmentInput(
            "segment-0001",
            0,
            "Take B",
            "take b",
            Decimal(0),
            Decimal("50.478"),
        ),
        SegmentInput(
            "segment-0002",
            1,
            "Take A",
            "take a",
            Decimal("50.478"),
            Decimal("55.412"),
        ),
    )
    source_in = Decimal(1322) / Decimal(24)
    assignment = VideoAssignment(
        status=VideoStatus.MATCHED,
        source_id="source-a",
        media=_media("video-a", duration="100", rate=source_rate),
        source_in_seconds=source_in,
        predicted_source_out_seconds=source_in + Decimal("4.934"),
    )
    inputs = replace(
        _inputs(),
        timeline_rate=FrameRate.parse("24"),
        master_media=_media("master", duration="55.412", rate="24"),
        segments=segments,
        enabled_take_keys=frozenset({"take a"}),
        assignments={"segment-0002": assignment},
    )

    plan = create_edit_plan(inputs)
    video = plan.video_clips[0]

    assert video.record_end_frame - video.record_start_frame == 119
    assert video.source_end_frame - video.source_start_frame == expected_duration
    source_duration_seconds = Decimal(expected_duration) / FrameRate.parse(source_rate).decimal
    assert seconds_to_frame(source_duration_seconds, inputs.timeline_rate) == 119


def test_validator_detects_video_in_declared_gap() -> None:
    plan = create_edit_plan(_inputs())
    broken_segment = replace(
        plan.segments[0],
        video_clip=replace(plan.segments[0].audio_clip, media_type="video", id="video-bad"),
    )
    broken = replace(plan, segments=(broken_segment, *plan.segments[1:]))
    with pytest.raises(PlanningError, match="one gap and no video"):
        validate_edit_plan(broken)


def test_colors_are_stable_supported_and_reused_after_palette() -> None:
    sequence = [f"take {index}" for index in range(20)] + ["take 0", "take 1"]
    first = assign_take_colors(sequence)
    second = assign_take_colors(sequence)
    assert first == second
    assert set(first.values()) <= set(RESOLVE_COLORS)
    assert len(first) == 20
    assert len(set(first.values())) == len(RESOLVE_COLORS)
