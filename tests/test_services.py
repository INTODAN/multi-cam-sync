from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from multi_cam_sync import __version__
from multi_cam_sync.alignment import (
    AlignmentSettings,
    BlockerCode,
    MatchDiagnostics,
    MatchMethod,
    MatchStatus,
    SegmentMatch,
    SegmentMatcher,
    SegmentRequest,
)
from multi_cam_sync.media import (
    AnalysisAudio,
    AudioRequest,
    ContentFingerprint,
    MediaProbe,
    MediaReader,
    fingerprint_file,
)
from multi_cam_sync.planning import VideoStatus
from multi_cam_sync.progress import ProgressEvent
from multi_cam_sync.reporting import AlignmentReport, read_report, write_report
from multi_cam_sync.resolve import (
    BuildResult,
    EditPlanLike,
    MediaSelector,
    ResolvedMediaItem,
    ResolvePreflightError,
    ResolveProjectSnapshot,
)
from multi_cam_sync.services import MultiCamSyncService, ServiceInputError


class FakeGateway:
    def __init__(self, snapshot: ResolveProjectSnapshot) -> None:
        self.current_snapshot = snapshot
        self.snapshot_calls: list[tuple[MediaSelector, ...]] = []
        self.build_calls: list[EditPlanLike] = []

    def snapshot(self, selectors: tuple[MediaSelector, ...]) -> ResolveProjectSnapshot:
        self.snapshot_calls.append(selectors)
        return self.current_snapshot

    def build_timeline(self, plan: EditPlanLike) -> BuildResult:
        self.build_calls.append(plan)
        return BuildResult(
            timeline_id="timeline-id",
            timeline_name=plan.timeline_name,
            audio_item_count=len(plan.audio_clips),
            video_item_count=len(plan.video_clips),
            marker_count=len(plan.markers),
        )


class FakeMediaReader:
    def __init__(self, durations: dict[Path, Decimal]) -> None:
        self.durations = durations
        self.probe_calls: list[Path] = []
        self.audio_requests: list[AudioRequest] = []

    def probe(self, path: Path) -> MediaProbe:
        self.probe_calls.append(path)
        return MediaProbe(path, self.durations[path], (), None, None)

    def load_audio(self, request: AudioRequest) -> AnalysisAudio:
        self.audio_requests.append(request)
        end = request.source_end_seconds or self.durations[request.path]
        sample_count = int((end - request.source_start_seconds) * request.sample_rate)
        return AnalysisAudio(
            samples=np.zeros(sample_count, dtype=np.float32),
            sample_rate=request.sample_rate,
            origin_seconds=request.source_start_seconds,
            fingerprint=fingerprint_file(request.path),
        )


class FakeMatcher:
    def __init__(self, *, unsafe: bool = False) -> None:
        self.unsafe = unsafe
        self.calls: list[SegmentRequest] = []

    def match(
        self,
        segment: SegmentRequest,
        master_audio: AnalysisAudio,
        candidates: object,
        settings: AlignmentSettings,
    ) -> SegmentMatch:
        del master_audio, candidates
        self.calls.append(segment)
        source_in = segment.master_start_seconds + Decimal(1)
        source_out = source_in + segment.duration_seconds
        blockers = (BlockerCode.AMBIGUOUS_RUNNER_UP,) if self.unsafe else ()
        diagnostics = MatchDiagnostics(
            settings=settings.as_dict(),
            normalized_cost=0.1,
            coverage=1.0,
            mapped_source_end_seconds=source_out,
            predicted_drift_seconds=Decimal(0),
        )
        return SegmentMatch(
            segment_id=segment.segment_id,
            take=segment.take,
            status=MatchStatus.UNSAFE if self.unsafe else MatchStatus.MATCHED,
            method=MatchMethod.AUTOMATIC,
            source_id="take-a-source",
            source_in_seconds=source_in,
            source_out_seconds=source_out,
            diagnostics=diagnostics,
            blockers=blockers,
        )


def _project_files(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    master_path = tmp_path / "media" / "master audio.wav"
    source_path = tmp_path / "media" / "camera reference.mov"
    master_path.parent.mkdir()
    master_path.write_bytes(b"master-input")
    source_path.write_bytes(b"source-input")
    cuts_path = tmp_path / "cuts.txt"
    cuts_path.write_text(
        "Out: Take A\nIn: Take B\n00:00:02\n\nOut: Take B\nIn: Take A\n00:00:04\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "project.toml"
    config_path.write_text(
        f'''schema_version = 1

[project]
timeline_name = "Partial synced timeline"
cuts_file = "{cuts_path.name}"

[master]
media_pool_folder = "Audio/Masters"
media_pool_name = "Master.wav"
audio_path = "{master_path}"

[[sources]]
id = "take-a-source"
take = "Take A"
media_pool_folder = "Video/Multicam"
media_pool_name = "Take A multicam"
audio_reference_path = "{source_path}"
source_start = "00:00:00"
source_end = "00:00:20"
''',
        encoding="utf-8",
    )
    return config_path, cuts_path, master_path, source_path


def _snapshot(master_path: Path, source_path: Path) -> ResolveProjectSnapshot:
    master_selector = MediaSelector.from_folder("Audio/Masters", "Master.wav", "master")
    source_selector = MediaSelector.from_folder("Video/Multicam", "Take A multicam", "video")
    return ResolveProjectSnapshot(
        project_id="project-id",
        project_name="Test Project",
        timeline_frame_rate=Decimal(24),
        timeline_start_frame=86400,
        timeline_start_timecode="01:00:00:00",
        timeline_names=("Existing timeline",),
        media=(
            ResolvedMediaItem(
                "master-id",
                master_selector,
                "Master.wav",
                master_path,
                144,
                Decimal(24),
                {"File Path": str(master_path)},
            ),
            ResolvedMediaItem(
                "source-media-id",
                source_selector,
                "Take A multicam",
                source_path,
                480,
                Decimal(24),
                {"File Path": str(source_path)},
            ),
        ),
    )


def _system(
    tmp_path: Path, *, unsafe: bool = False
) -> tuple[Path, Path, Path, FakeGateway, FakeMediaReader, FakeMatcher, MultiCamSyncService]:
    config_path, _, master_path, source_path = _project_files(tmp_path)
    gateway = FakeGateway(_snapshot(master_path, source_path))
    reader = FakeMediaReader(
        {master_path.resolve(): Decimal(6), source_path.resolve(): Decimal(20)}
    )
    matcher = FakeMatcher(unsafe=unsafe)
    service = MultiCamSyncService(
        gateway=gateway,
        media_reader=cast("MediaReader", reader),
        matcher=cast("SegmentMatcher", matcher),
    )
    return config_path, master_path, source_path, gateway, reader, matcher, service


def test_validate_and_partial_analysis_have_zero_resolve_mutations(tmp_path: Path) -> None:
    config, _, _, gateway, reader, matcher, service = _system(tmp_path)

    context = service.validate(config)
    assert len(context.segments) == 3
    assert reader.audio_requests == []
    assert gateway.build_calls == []

    progress: list[ProgressEvent] = []
    outcome = service.analyze(config, progress=progress.append)
    assert outcome.unsafe_count == 0
    assert [segment.video_status for segment in outcome.report.segments] == [
        VideoStatus.MATCHED,
        VideoStatus.NOT_PROVIDED,
        VideoStatus.MATCHED,
    ]
    assert [request.segment_id for request in matcher.calls] == [
        "segment-0001",
        "segment-0003",
    ]
    assert len(reader.audio_requests) == 2  # master once, shared source occurrence once
    assert gateway.build_calls == []
    aligned = [event for event in progress if event.item_index is not None]
    assert [(event.item_index, event.item_total) for event in aligned] == [(1, 2), (2, 2)]
    assert progress[0].message == "Validating configuration and Resolve media"
    assert progress[-1].message == "Fingerprinting input media"

    plan = outcome.report.plan
    assert plan is not None
    assert len(plan.audio_clips) == 3
    assert len(plan.video_clips) == 2
    assert len(plan.video_gaps) == 1
    assert plan.video_gaps[0].segment_id == "segment-0002"
    assert all(
        left.record_end_frame == right.record_start_frame
        for left, right in zip(plan.audio_clips, plan.audio_clips[1:], strict=False)
    )


def test_resolve_master_end_is_authoritative_within_probe_tolerance(tmp_path: Path) -> None:
    config, master_path, _, _, reader, _, service = _system(tmp_path)
    reader.durations[master_path.resolve()] = Decimal("6.03")

    outcome = service.analyze(config)

    assert outcome.report.segments[-1].master_end_seconds == Decimal(6)
    assert outcome.report.plan is not None
    assert outcome.report.plan.audio_clips[-1].source_end_frame == 144


def test_master_reference_shorter_than_resolve_item_is_rejected(tmp_path: Path) -> None:
    config, master_path, _, gateway, reader, _, service = _system(tmp_path)
    reader.durations[master_path.resolve()] = Decimal("5.9")

    with pytest.raises(ServiceInputError, match=r"shorter.*by more than two frames"):
        service.validate(config)

    assert gateway.build_calls == []


def test_zero_sources_skip_all_audio_decode_and_matching(tmp_path: Path) -> None:
    config, _, _, gateway, reader, matcher, service = _system(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").split("\n[[sources]]", maxsplit=1)[0] + "\n",
        encoding="utf-8",
    )
    gateway.current_snapshot = replace(
        gateway.current_snapshot, media=(gateway.current_snapshot.media[0],)
    )

    outcome = service.analyze(config)

    assert reader.audio_requests == []
    assert matcher.calls == []
    assert all(
        segment.video_status is VideoStatus.NOT_PROVIDED for segment in outcome.report.segments
    )
    assert outcome.report.plan is not None
    assert outcome.report.plan.video_clips == ()
    assert len(outcome.report.plan.video_gaps) == 3
    assert gateway.build_calls == []


def test_safe_report_builds_exactly_once(tmp_path: Path) -> None:
    config, _, _, gateway, _, _, service = _system(tmp_path)
    report = service.analyze(config).report
    report_path = tmp_path / "report.json"
    write_report(report_path, report)
    reloaded = read_report(report_path)

    progress: list[ProgressEvent] = []
    result = service.build(config, reloaded, progress=progress.append)

    assert result.verified
    assert len(gateway.build_calls) == 1
    assert gateway.build_calls[0] is reloaded.plan
    assert [event.completed for event in progress] == [1, 2, 3, 4]


def test_unsafe_requested_take_blocks_plan_and_build(tmp_path: Path) -> None:
    config, _, _, gateway, _, matcher, service = _system(tmp_path, unsafe=True)

    outcome = service.analyze(config)

    assert outcome.unsafe_count == 2
    assert outcome.report.plan is None
    assert len(matcher.calls) == 2
    with pytest.raises(ServiceInputError, match="no safe edit plan"):
        service.build(config, outcome.report)
    assert gateway.build_calls == []


def test_changed_input_and_tampered_plan_never_mutate_resolve(tmp_path: Path) -> None:
    config, _, source_path, gateway, _, _, service = _system(tmp_path)
    report = service.analyze(config).report
    assert report.plan is not None

    tampered_plan = replace(report.plan, timeline_name="Tampered timeline")
    tampered_report = replace(report, plan=tampered_plan)
    with pytest.raises(ServiceInputError, match="embedded edit plan differs"):
        service.build(config, tampered_report)

    source_path.write_bytes(b"changed-source-input")
    with pytest.raises(ServiceInputError, match="input media file changed"):
        service.build(config, report)

    assert gateway.build_calls == []


def test_all_report_staleness_checks_precede_mutation(tmp_path: Path) -> None:
    config, _, _, gateway, _, _, service = _system(tmp_path)
    report = service.analyze(config).report
    assert report.plan is not None

    rejected: tuple[AlignmentReport, ...] = (
        replace(report, tool_version="0.0.0"),
        replace(report, configuration_hash="different"),
        replace(report, cuts_hash="different"),
        replace(report, alignment_settings={"different": True}),
    )
    for stale in rejected:
        with pytest.raises(ServiceInputError):
            service.build(config, stale)

    original_snapshot = gateway.current_snapshot
    gateway.current_snapshot = replace(original_snapshot, project_name="Changed Project")
    with pytest.raises(ResolvePreflightError, match="changed after analysis"):
        service.build(config, report)

    assert report.tool_version == __version__
    assert gateway.build_calls == []


def test_target_timeline_collision_is_read_only(tmp_path: Path) -> None:
    config, _, _, gateway, _, _, service = _system(tmp_path)
    gateway.current_snapshot = replace(
        gateway.current_snapshot,
        timeline_names=("Existing timeline", "Partial synced timeline"),
    )

    with pytest.raises(ResolvePreflightError, match="already exists"):
        service.validate(config)

    assert gateway.build_calls == []


def test_test_fixture_fingerprints_are_real(tmp_path: Path) -> None:
    _, master_path, _, _, _, _, _ = _system(tmp_path)
    fingerprint: ContentFingerprint = fingerprint_file(master_path)
    assert fingerprint.size_bytes == len(b"master-input")
    assert Fraction(24, 1) == Fraction("24")
