"""Offline whole-system proof using generated media and strict Resolve fakes."""

from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from shutil import copyfile
from typing import cast

import numpy as np
import pytest
import soundfile as sf

from multi_cam_sync.media import (
    AnalysisAudio,
    AnalysisCache,
    AudioRequest,
    CachingMediaReader,
    FFmpegMediaReader,
    MediaProbe,
    MediaReader,
)
from multi_cam_sync.planning import VideoStatus
from multi_cam_sync.reporting import read_report, write_report
from multi_cam_sync.reporting.io import canonical_payload
from multi_cam_sync.resolve import DaVinciResolveGateway, ResolveGateway
from multi_cam_sync.services import MultiCamSyncService, ServiceInputError
from tests.fakes.resolve import ResolveFake, make_resolve_fake  # ty: ignore[unresolved-import]
from tests.system_fixtures import (  # ty: ignore[unresolved-import]
    SEGMENT_SECONDS,
    SEGMENT_TAKES,
    SoundFileProbeRunner,
    generate_performance,
)


class RecordingMediaReader:
    """Record cache-miss work while delegating all media behavior to production."""

    def __init__(self, backend: FFmpegMediaReader) -> None:
        self.backend = backend
        self.probes: list[Path] = []
        self.audio_requests: list[AudioRequest] = []

    def probe(self, path: Path) -> MediaProbe:
        self.probes.append(path)
        return self.backend.probe(path)

    def load_audio(self, request: AudioRequest) -> AnalysisAudio:
        self.audio_requests.append(request)
        return self.backend.load_audio(request)


def _mutation_events(fake: ResolveFake) -> list[tuple[object, ...]]:
    operations = {
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
    return [event for event in fake.events if event[0] in operations]


def _system(
    tmp_path: Path,
) -> tuple[
    Path,
    Path,
    ResolveFake,
    RecordingMediaReader,
    MultiCamSyncService,
]:
    fixture = generate_performance(tmp_path)
    runner = SoundFileProbeRunner()
    backend = RecordingMediaReader(
        FFmpegMediaReader(
            runner=runner,
            ffprobe_executable="test-ffprobe",
            ffmpeg_executable="forbidden-ffmpeg",
        )
    )
    reader = CachingMediaReader(backend, AnalysisCache(tmp_path / "analysis cache"))
    fake = make_resolve_fake()
    fake.master.properties["Frames"] = "360"
    gateway = DaVinciResolveGateway(connector=lambda: fake.session)
    service = MultiCamSyncService(
        gateway=cast("ResolveGateway", gateway),
        media_reader=cast("MediaReader", reader),
    )
    return fixture.config_path, fixture.shared_source_path, fake, backend, service


def _assert_within_two_frames(actual: Decimal, expected: Decimal) -> None:
    rate = Fraction(24_000, 1_001)
    tolerance = Decimal(2 * rate.denominator) / Decimal(rate.numerator)
    assert abs(actual - expected) <= tolerance


def test_generated_partial_video_round_trip_and_strict_fake_build(tmp_path: Path) -> None:
    config_path, shared_source_path, fake, backend, service = _system(tmp_path)

    context = service.validate(config_path)
    assert len(context.segments) == 10
    assert len({segment.take_key for segment in context.segments}) == 9
    assert context.segments[-1].take_key == context.segments[0].take_key
    assert len(context.snapshot.media) == 2  # shared selector is resolved only once
    assert backend.audio_requests == []
    assert _mutation_events(fake) == []

    cold = service.analyze(config_path).report
    assert cold.safe_to_build
    assert len(backend.audio_requests) == 3  # master plus two bounded crops of one WAV
    source_requests = [
        request for request in backend.audio_requests if request.path == shared_source_path
    ]
    assert [
        (request.source_start_seconds, request.source_end_seconds) for request in source_requests
    ] == [
        (Decimal("0.500"), Decimal("16.500")),
        (Decimal("16.500"), Decimal("32.500")),
    ]
    assert _mutation_events(fake) == []

    warm = service.analyze(config_path).report
    assert len(backend.audio_requests) == 3  # every analysis decode came from the warm cache
    assert canonical_payload(warm) == canonical_payload(cold)
    assert _mutation_events(fake) == []

    matched = [segment for segment in cold.segments if segment.video_status is VideoStatus.MATCHED]
    omitted = [
        segment for segment in cold.segments if segment.video_status is VideoStatus.NOT_PROVIDED
    ]
    assert [segment.index for segment in matched] == [0, 7, 9]
    assert len(omitted) == 7
    assert all(segment.diagnostics is None for segment in omitted)
    assert all(segment.candidates == () for segment in omitted)

    expected_offsets = {
        0: Decimal(1),
        7: Decimal(17),
        9: Decimal(1),
    }
    for segment in matched:
        assert segment.source_in_seconds is not None
        expected = Decimal(segment.index) * SEGMENT_SECONDS + expected_offsets[segment.index]
        _assert_within_two_frames(segment.source_in_seconds, expected)

    plan = cold.plan
    assert plan is not None
    assert len(plan.audio_clips) == len(SEGMENT_TAKES)
    assert len(plan.video_clips) == 3
    assert len(plan.video_gaps) == 7
    assert len(plan.markers) == len(SEGMENT_TAKES) - 1
    assert all(
        left.record_end_frame == right.record_start_frame
        for left, right in zip(plan.audio_clips, plan.audio_clips[1:], strict=False)
    )
    assert {clip.segment_id for clip in plan.video_clips} == {
        "segment-0001",
        "segment-0008",
        "segment-0010",
    }
    assert {gap.segment_id for gap in plan.video_gaps} == {
        f"segment-{index:04d}" for index in (2, 3, 4, 5, 6, 7, 9)
    }

    report_path = tmp_path / "reports with spaces" / "alignment.json"
    write_report(report_path, cold)
    reviewed = read_report(report_path)
    assert canonical_payload(reviewed) == canonical_payload(cold)
    assert reviewed.plan == cold.plan
    assert reviewed.plan is not None
    assert reviewed.plan.timeline_rate.numerator == 24_000
    assert reviewed.plan.timeline_rate.denominator == 1_001
    assert all(isinstance(segment.master_start_seconds, Decimal) for segment in reviewed.segments)

    fake.events.clear()
    result = service.build(config_path, reviewed)
    assert result.verified
    assert result.audio_item_count == 10
    assert result.video_item_count == 3
    assert result.marker_count == 9
    assert len(fake.media_pool.append_infos) == 13
    audio_appends = [info for info in fake.media_pool.append_infos if info["mediaType"] == 2]
    video_appends = [info for info in fake.media_pool.append_infos if info["mediaType"] == 1]
    assert len(audio_appends) == 10
    assert all(info["mediaPoolItem"] is fake.master for info in audio_appends)
    assert len(video_appends) == 3
    assert all(info["mediaPoolItem"] is fake.video for info in video_appends)
    assert {info["recordFrame"] for info in video_appends} == {
        clip.record_start_frame for clip in plan.video_clips
    }
    assert fake.media_pool.deleted == []


def test_changed_shared_physical_input_blocks_before_resolve_mutation(tmp_path: Path) -> None:
    config_path, source_path, fake, _, service = _system(tmp_path)
    report = service.analyze(config_path).report
    assert report.safe_to_build
    assert _mutation_events(fake) == []

    source_path.write_bytes(source_path.read_bytes() + b"changed-after-analysis")
    fake.events.clear()

    with pytest.raises(ServiceInputError, match="input media file changed"):
        service.build(config_path, report)

    assert _mutation_events(fake) == []


def test_generated_segment_manual_offset_leaves_later_same_take_segment_automatic(
    tmp_path: Path,
) -> None:
    config_path, _, fake, _, service = _system(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'source_end = "00:00:16.500"\n\n[[sources]]',
            """source_end = "00:00:16.500"

[[sources.segment_manual_offsets]]
segment_id = "segment-0001"
manual_offset_seconds = 1.25

[[sources]]""",
        ),
        encoding="utf-8",
    )

    report = service.analyze(config_path).report

    assert report.safe_to_build
    first = report.segments[0]
    later = report.segments[9]
    assert first.method == "manual"
    assert first.source_in_seconds == Decimal("1.25")
    assert any("manual_offset_seconds" in warning for warning in first.warnings)
    assert later.take == first.take
    assert later.method == "automatic"
    assert later.source_in_seconds is not None
    _assert_within_two_frames(later.source_in_seconds, Decimal("14.5"))
    assert _mutation_events(fake) == []


def test_generated_silent_primary_uses_same_length_camera_fallback(tmp_path: Path) -> None:
    config_path, source_path, fake, backend, service = _system(tmp_path)
    fallback_path = source_path.with_name("second camera reference.wav")
    copyfile(source_path, fallback_path)
    source_audio, sample_rate = sf.read(source_path, dtype="float32", always_2d=True)
    sf.write(
        source_path,
        np.zeros_like(source_audio),
        sample_rate,
        subtype="FLOAT",
    )
    primary_config_path = source_path.relative_to(tmp_path)
    fallback_config_path = fallback_path.relative_to(tmp_path)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            f'audio_reference_path = "{primary_config_path}"',
            (
                f'audio_reference_path = "{primary_config_path}"\n'
                "additional_audio_reference_paths = [\n"
                f'    "{fallback_config_path}",\n'
                "]"
            ),
        ),
        encoding="utf-8",
    )

    report = service.analyze(config_path).report

    assert report.safe_to_build
    assert len(backend.audio_requests) == 5  # master, then two crops from each camera reference
    matched = [
        segment for segment in report.segments if segment.video_status is VideoStatus.MATCHED
    ]
    assert len(matched) == 3
    assert all(
        any("matched using additional audio reference 1" in warning for warning in segment.warnings)
        for segment in matched
    )
    assert all(
        {candidate["audio_reference_id"] for candidate in segment.candidates}
        == {"primary", "additional-1"}
        for segment in matched
    )
    assert [record.role for record in report.input_files] == [
        "master",
        "source",
        "source_additional_1",
        "source",
        "source_additional_1",
    ]
    assert _mutation_events(fake) == []

    fallback_path.write_bytes(fallback_path.read_bytes() + b"changed-after-analysis")
    fake.events.clear()

    with pytest.raises(ServiceInputError, match="input media file changed"):
        service.build(config_path, report)

    assert _mutation_events(fake) == []
