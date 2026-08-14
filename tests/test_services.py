from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import cast

import numpy as np
import pytest

from multi_cam_sync import __version__
from multi_cam_sync.alignment import (
    AlignmentCandidate,
    AlignmentSettings,
    BlockerCode,
    CandidateMatch,
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
    def __init__(
        self,
        *,
        unsafe: bool = False,
        unsafe_reference_ids: frozenset[str] = frozenset(),
    ) -> None:
        self.unsafe = unsafe
        self.unsafe_reference_ids = unsafe_reference_ids
        self.calls: list[SegmentRequest] = []
        self.candidate_calls: list[tuple[AlignmentCandidate, ...]] = []

    def match(
        self,
        segment: SegmentRequest,
        master_audio: AnalysisAudio,
        candidates: Sequence[AlignmentCandidate],
        settings: AlignmentSettings,
    ) -> SegmentMatch:
        del master_audio
        self.calls.append(segment)
        self.candidate_calls.append(tuple(candidates))
        selected = candidates[0]
        method = (
            MatchMethod.MANUAL
            if selected.manual_offset_seconds is not None
            else MatchMethod.AUTOMATIC
        )
        source_in = segment.master_start_seconds + (
            selected.manual_offset_seconds
            if selected.manual_offset_seconds is not None
            else Decimal(1)
        )
        source_out = source_in + segment.duration_seconds
        unsafe = method is MatchMethod.AUTOMATIC and (
            self.unsafe or selected.audio_reference_id in self.unsafe_reference_ids
        )
        blockers = (BlockerCode.AMBIGUOUS_RUNNER_UP,) if unsafe else ()
        diagnostics = MatchDiagnostics(
            settings=settings.as_dict(),
            normalized_cost=None if method is MatchMethod.MANUAL else 0.1,
            coverage=None if method is MatchMethod.MANUAL else 1.0,
            mapped_source_end_seconds=source_out,
            predicted_drift_seconds=Decimal(0),
        )
        candidate_matches = tuple(
            CandidateMatch(
                source_id=candidate.source_id,
                method=method,
                source_in_seconds=source_in,
                source_out_seconds=source_out,
                diagnostics=diagnostics,
                blockers=blockers,
                warnings=("manual test override",) if method is MatchMethod.MANUAL else (),
                search_start_seconds=candidate.start_seconds,
                search_end_seconds=candidate.end_seconds,
                audio_reference_id=candidate.audio_reference_id,
            )
            for candidate in candidates
        )
        return SegmentMatch(
            segment_id=segment.segment_id,
            take=segment.take,
            status=MatchStatus.UNSAFE if unsafe else MatchStatus.MATCHED,
            method=method,
            source_id=selected.source_id,
            source_in_seconds=source_in,
            source_out_seconds=source_out,
            diagnostics=diagnostics,
            candidates=candidate_matches,
            blockers=blockers,
            warnings=("manual test override",) if method is MatchMethod.MANUAL else (),
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


def _add_additional_audio_references(
    config_path: Path,
    source_path: Path,
    reader: FakeMediaReader,
    names: tuple[str, ...] = ("camera B reference.wav",),
) -> tuple[Path, ...]:
    fallback_paths = tuple(source_path.with_name(name) for name in names)
    for fallback_path in fallback_paths:
        fallback_path.write_bytes(b"fallback-source-input")
        reader.durations[fallback_path.resolve()] = reader.durations[source_path.resolve()]
    fallback_lines = "".join(f'    "{path}",\n' for path in fallback_paths)
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            f'audio_reference_path = "{source_path}"',
            (
                f'audio_reference_path = "{source_path}"\n'
                "additional_audio_reference_paths = [\n"
                f"{fallback_lines}"
                "]"
            ),
        ),
        encoding="utf-8",
    )
    return fallback_paths


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


def test_analysis_applies_one_segment_search_range_without_extra_decode(tmp_path: Path) -> None:
    config, _, _, _, reader, matcher, service = _system(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8")
        + """

[[sources.segment_search_ranges]]
segment_id = "segment-0001"
source_start = "00:00:03.250"
source_end = "00:00:08.750"
""",
        encoding="utf-8",
    )

    outcome = service.analyze(config)

    assert outcome.unsafe_count == 0
    assert len(reader.audio_requests) == 2  # master and broad source occurrence, each once
    first_candidate = matcher.candidate_calls[0][0]
    later_candidate = matcher.candidate_calls[1][0]
    assert first_candidate.start_seconds == Decimal("3.250")
    assert first_candidate.end_seconds == Decimal("8.750")
    assert later_candidate.start_seconds == Decimal(0)
    assert later_candidate.end_seconds == Decimal(20)


def test_segment_manual_offset_does_not_change_later_automatic_segment(
    tmp_path: Path,
) -> None:
    config, master_path, source_path, gateway, reader, matcher, service = _system(tmp_path)
    (fallback_path,) = _add_additional_audio_references(config, source_path, reader)
    config.write_text(
        config.read_text(encoding="utf-8")
        + """

[[sources.segment_manual_offsets]]
segment_id = "segment-0001"
manual_offset_seconds = 5.25
""",
        encoding="utf-8",
    )
    matcher.unsafe_reference_ids = frozenset({"primary"})

    outcome = service.analyze(config)

    assert outcome.report.safe_to_build
    assert [request.path for request in reader.audio_requests] == [
        master_path.resolve(),
        source_path.resolve(),
        fallback_path.resolve(),
    ]
    assert [
        (candidates[0].audio_reference_id, candidates[0].manual_offset_seconds)
        for candidates in matcher.candidate_calls
    ] == [
        ("primary", Decimal("5.25")),
        ("primary", None),
        ("additional-1", None),
    ]
    manual_segment = outcome.report.segments[0]
    automatic_segment = outcome.report.segments[2]
    assert manual_segment.segment_id == "segment-0001"
    assert manual_segment.method == "manual"
    assert manual_segment.source_in_seconds == Decimal("5.25")
    assert automatic_segment.segment_id == "segment-0003"
    assert automatic_segment.method == "automatic"
    assert automatic_segment.source_in_seconds == Decimal(5)
    assert any("additional audio reference 1" in warning for warning in automatic_segment.warnings)
    assert gateway.build_calls == []


def test_additional_reference_is_fingerprinted_but_not_decoded_when_primary_matches(
    tmp_path: Path,
) -> None:
    config, master_path, source_path, gateway, reader, matcher, service = _system(tmp_path)
    (fallback_path,) = _add_additional_audio_references(config, source_path, reader)

    outcome = service.analyze(config)

    assert outcome.report.safe_to_build
    assert [request.path for request in reader.audio_requests] == [
        master_path.resolve(),
        source_path.resolve(),
    ]
    assert all(
        candidate.audio_reference_id == "primary"
        for candidates in matcher.candidate_calls
        for candidate in candidates
    )
    assert [record.role for record in outcome.report.input_files] == [
        "master",
        "source",
        "source_additional_1",
    ]

    fallback_path.write_bytes(b"changed-fallback-input")
    with pytest.raises(ServiceInputError, match="input media file changed"):
        service.build(config, outcome.report)
    assert gateway.build_calls == []


def test_unsafe_primary_retries_and_reuses_first_safe_additional_reference(
    tmp_path: Path,
) -> None:
    config, master_path, source_path, _, reader, matcher, service = _system(tmp_path)
    (fallback_path,) = _add_additional_audio_references(config, source_path, reader)
    matcher.unsafe_reference_ids = frozenset({"primary"})

    outcome = service.analyze(config)

    assert outcome.unsafe_count == 0
    assert [request.path for request in reader.audio_requests] == [
        master_path.resolve(),
        source_path.resolve(),
        fallback_path.resolve(),
    ]
    assert [candidates[0].audio_reference_id for candidates in matcher.candidate_calls] == [
        "primary",
        "additional-1",
        "primary",
        "additional-1",
    ]
    matched = [
        segment
        for segment in outcome.report.segments
        if segment.video_status is VideoStatus.MATCHED
    ]
    assert len(matched) == 2
    assert all(
        "matched using additional audio reference 1" in segment.warnings[0] for segment in matched
    )
    assert all(
        [candidate["audio_reference_id"] for candidate in segment.candidates]
        == ["primary", "additional-1"]
        for segment in matched
    )


def test_additional_references_are_tried_in_order_until_one_is_safe(tmp_path: Path) -> None:
    config, master_path, source_path, _, reader, matcher, service = _system(tmp_path)
    first_fallback, second_fallback = _add_additional_audio_references(
        config,
        source_path,
        reader,
        ("camera B reference.wav", "camera C reference.wav"),
    )
    matcher.unsafe_reference_ids = frozenset({"primary", "additional-1"})

    outcome = service.analyze(config)

    assert outcome.unsafe_count == 0
    assert [request.path for request in reader.audio_requests] == [
        master_path.resolve(),
        source_path.resolve(),
        first_fallback.resolve(),
        second_fallback.resolve(),
    ]
    assert [candidates[0].audio_reference_id for candidates in matcher.candidate_calls] == [
        "primary",
        "additional-1",
        "additional-2",
        "primary",
        "additional-1",
        "additional-2",
    ]
    matched = [
        segment
        for segment in outcome.report.segments
        if segment.video_status is VideoStatus.MATCHED
    ]
    assert all(
        [candidate["audio_reference_id"] for candidate in segment.candidates]
        == ["primary", "additional-1", "additional-2"]
        for segment in matched
    )
    assert all(
        any("additional audio reference 2" in warning for warning in segment.warnings)
        for segment in matched
    )


def test_additional_reference_must_have_exact_primary_duration(tmp_path: Path) -> None:
    config, _, source_path, gateway, reader, _, service = _system(tmp_path)
    (fallback_path,) = _add_additional_audio_references(config, source_path, reader)
    reader.durations[fallback_path.resolve()] = Decimal("19.999")

    with pytest.raises(ServiceInputError, match=r"exactly the same length"):
        service.validate(config)

    assert reader.audio_requests == []
    assert gateway.build_calls == []


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


def test_segment_search_range_cannot_exceed_unbounded_source_media(tmp_path: Path) -> None:
    config, _, _, gateway, _, _, service = _system(tmp_path)
    config.write_text(
        config.read_text(encoding="utf-8").replace('source_end = "00:00:20"\n', "")
        + """

[[sources.segment_search_ranges]]
segment_id = "segment-0001"
source_start = "00:00:19"
source_end = "00:00:21"
""",
        encoding="utf-8",
    )

    with pytest.raises(ServiceInputError, match=r"segment-0001.*exceeds reference duration"):
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
