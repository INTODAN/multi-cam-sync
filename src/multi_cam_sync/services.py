"""Read-only validation/analysis orchestration and one-shot timeline builds."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

from multi_cam_sync import __version__
from multi_cam_sync.alignment import (
    AlignmentCandidate,
    AlignmentSettings,
    CandidateMatch,
    MatchDiagnostics,
    SegmentMatch,
    SegmentMatcher,
    SegmentRequest,
)
from multi_cam_sync.config import load_project_spec
from multi_cam_sync.cuts import build_master_segments, parse_cut_list
from multi_cam_sync.domain import MasterSegment, ProjectSpec, SourceSpec
from multi_cam_sync.media import (
    AnalysisCache,
    AudioRequest,
    CachingMediaReader,
    FFmpegMediaReader,
    MediaProbe,
    MediaReader,
    fingerprint_file,
)
from multi_cam_sync.planning import (
    EditPlan,
    FrameRate,
    MediaDescriptor,
    PlanningError,
    PlanningInputs,
    SegmentInput,
    VideoAssignment,
    VideoStatus,
    create_edit_plan,
)
from multi_cam_sync.progress import (
    ANALYZE_STEP_COUNT,
    BUILD_STEP_COUNT,
    ProgressCallback,
    ProgressEvent,
)
from multi_cam_sync.reporting import AlignmentReport, InputFileRecord, SegmentReport
from multi_cam_sync.resolve import (
    BuildResult,
    DaVinciResolveGateway,
    EditPlanLike,
    MediaSelector,
    ResolvedMediaItem,
    ResolveGateway,
    ResolvePreflightError,
    ResolveProjectSnapshot,
)


class ServiceInputError(RuntimeError):
    """Validated configuration cannot be connected to usable physical media."""


class GatewayLike(Protocol):
    def snapshot(self, selectors: tuple[MediaSelector, ...]) -> ResolveProjectSnapshot: ...

    def build_timeline(self, plan: EditPlanLike) -> BuildResult: ...


@dataclass(frozen=True, slots=True)
class ValidationContext:
    """Complete read-only state shared by validate and analyze."""

    spec: ProjectSpec
    cuts_text: str
    cuts_hash: str
    configuration_hash: str
    segments: tuple[MasterSegment, ...]
    snapshot: ResolveProjectSnapshot
    master_item: ResolvedMediaItem
    source_items: Mapping[str, ResolvedMediaItem]
    master_path: Path
    source_paths: Mapping[str, Path]
    additional_source_paths: Mapping[str, tuple[Path, ...]]
    master_probe: MediaProbe
    source_probes: Mapping[str, MediaProbe]
    additional_source_probes: Mapping[str, tuple[MediaProbe, ...]]

    @property
    def enabled_take_keys(self) -> frozenset[str]:
        return frozenset(self.spec.sources_by_take)


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    report: AlignmentReport
    unsafe_count: int


def _notify(progress: ProgressCallback | None, event: ProgressEvent) -> None:
    if progress is not None:
        progress(event)


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise ServiceInputError(f"cannot read {label} {path}: {error}") from error


def _selector(folder: str, name: str, kind: str) -> MediaSelector:
    try:
        return MediaSelector.from_folder(folder, name, kind)
    except ValueError as error:
        raise ServiceInputError(f"invalid Media Pool selector {folder}/{name}: {error}") from error


def _snapshot_item(snapshot: ResolveProjectSnapshot, selector: MediaSelector) -> ResolvedMediaItem:
    matches = [item for item in snapshot.media if item.selector == selector]
    if len(matches) != 1:
        raise ServiceInputError(
            f"Resolve snapshot did not retain exactly one item for {selector.display!r}"
        )
    return matches[0]


def _physical_path(configured: Path | None, item: ResolvedMediaItem, label: str) -> Path:
    path = configured or item.file_path
    if path is None:
        raise ServiceInputError(
            f"{label} is a virtual Resolve item without a readable File Path; "
            "set an explicit audio path in the configuration"
        )
    return path.expanduser().resolve(strict=False)


def _media_duration(item: ResolvedMediaItem) -> Decimal:
    return Decimal(item.duration_frames) / item.frame_rate


def _timeline_start_frame(snapshot: ResolveProjectSnapshot) -> int:
    if snapshot.timeline_start_frame is not None:
        return snapshot.timeline_start_frame
    normalized = snapshot.timeline_start_timecode.replace(";", ":")
    parts = normalized.split(":")
    if len(parts) != 4:
        raise ServiceInputError(
            f"unsupported Resolve timeline start timecode {snapshot.timeline_start_timecode!r}"
        )
    try:
        hours, minutes, seconds, frames = (int(part) for part in parts)
    except ValueError as error:
        raise ServiceInputError(
            f"invalid Resolve timeline start timecode {snapshot.timeline_start_timecode!r}"
        ) from error
    nominal_rate = int(snapshot.timeline_frame_rate.to_integral_value(rounding=ROUND_HALF_UP))
    if not (0 <= minutes < 60 and 0 <= seconds < 60 and 0 <= frames < nominal_rate):
        raise ServiceInputError(
            f"invalid Resolve timeline start timecode {snapshot.timeline_start_timecode!r}"
        )
    return ((hours * 60 + minutes) * 60 + seconds) * nominal_rate + frames


def _diagnostics_dict(value: MatchDiagnostics) -> Mapping[str, object]:
    result = asdict(value)
    return cast("Mapping[str, object]", result)


def _candidate_dict(value: CandidateMatch) -> Mapping[str, object]:
    return cast("Mapping[str, object]", asdict(value))


def _audio_reference_id(reference_index: int) -> str:
    return "primary" if reference_index == 0 else f"additional-{reference_index}"


def _source_reference_paths(context: ValidationContext, source: SourceSpec) -> tuple[Path, ...]:
    return (context.source_paths[source.id], *context.additional_source_paths[source.id])


def _input_file_records(context: ValidationContext) -> tuple[InputFileRecord, ...]:
    files = [InputFileRecord("master", None, fingerprint_file(context.master_path))]
    for source in context.spec.sources:
        files.append(
            InputFileRecord(
                "source",
                source.id,
                fingerprint_file(context.source_paths[source.id]),
            )
        )
        files.extend(
            InputFileRecord(
                f"source_additional_{reference_index}",
                source.id,
                fingerprint_file(path),
            )
            for reference_index, path in enumerate(
                context.additional_source_paths[source.id], start=1
            )
        )
    return tuple(files)


def _merge_reference_attempts(
    attempts: list[tuple[int, SegmentMatch]],
) -> SegmentMatch:
    """Keep all evidence while selecting the first safe reference or best unsafe attempt."""
    if not attempts:
        raise ValueError("at least one audio-reference match attempt is required")
    last_reference_index, last = attempts[-1]
    if last.safe_for_planning:
        selected = last
    else:
        _, selected = min(
            attempts,
            key=lambda item: (
                item[1].diagnostics.normalized_cost is None,
                item[1].diagnostics.normalized_cost
                if item[1].diagnostics.normalized_cost is not None
                else float("inf"),
                item[0],
            ),
        )
    if len(attempts) == 1:
        return selected

    candidates = tuple(candidate for _, attempt in attempts for candidate in attempt.candidates)
    if last.safe_for_planning:
        warnings = (
            *selected.warnings,
            f"matched using additional audio reference {last_reference_index} after "
            f"{len(attempts) - 1} earlier reference attempt(s) were unsafe",
        )
        blockers = selected.blockers
    else:
        warnings = (
            *selected.warnings,
            f"automatic matching tried the primary plus {len(attempts) - 1} additional "
            "audio reference(s); none was safe",
        )
        blockers = tuple(
            dict.fromkeys(blocker for _, attempt in attempts for blocker in attempt.blockers)
        )
    return replace(selected, candidates=candidates, blockers=blockers, warnings=warnings)


def _segment_inputs(context: ValidationContext) -> tuple[SegmentInput, ...]:
    return tuple(
        SegmentInput(
            id=segment.id,
            index=segment.index,
            display_take=segment.display_take,
            take_key=segment.take_key,
            start_seconds=segment.start_seconds,
            end_seconds=cast("Decimal", segment.end_seconds),
        )
        for segment in context.segments
    )


def _planning_inputs(
    context: ValidationContext,
    assignments: Mapping[str, VideoAssignment],
) -> PlanningInputs:
    return PlanningInputs(
        timeline_name=context.spec.project.timeline_name,
        timeline_rate=FrameRate.parse(context.snapshot.timeline_frame_rate),
        timeline_start_frame=_timeline_start_frame(context.snapshot),
        master_media=MediaDescriptor(
            media_id=context.master_item.media_id,
            name=context.master_item.name,
            duration_seconds=_media_duration(context.master_item),
            frame_rate=FrameRate.parse(context.master_item.frame_rate),
        ),
        segments=_segment_inputs(context),
        enabled_take_keys=context.enabled_take_keys,
        assignments=assignments,
        expected_snapshot=context.snapshot,
    )


def _recreate_report_plan(context: ValidationContext, report: AlignmentReport) -> EditPlan:
    """Recreate the pure plan from current inputs and reviewed match decisions."""
    if len(report.segments) != len(context.segments):
        raise ServiceInputError("report segment count differs from the current cut list")
    by_id = {segment.segment_id: segment for segment in report.segments}
    if len(by_id) != len(report.segments):
        raise ServiceInputError("report contains duplicate segment IDs")
    sources_by_id = {source.id: source for source in context.spec.sources}
    assignments: dict[str, VideoAssignment] = {}

    for master_segment in context.segments:
        report_segment = by_id.get(master_segment.id)
        if report_segment is None or master_segment.end_seconds is None:
            raise ServiceInputError("report segments differ from the current cut list")
        expected_identity = (
            master_segment.index,
            master_segment.display_take,
            master_segment.take_key,
            master_segment.start_seconds,
            master_segment.end_seconds,
        )
        report_identity = (
            report_segment.index,
            report_segment.take,
            report_segment.take_key,
            report_segment.master_start_seconds,
            report_segment.master_end_seconds,
        )
        if report_identity != expected_identity:
            raise ServiceInputError(
                f"report segment {master_segment.id!r} differs from the current cut list"
            )

        configured_sources = context.spec.sources_by_take.get(master_segment.take_key, ())
        if report_segment.video_status is VideoStatus.NOT_PROVIDED:
            if configured_sources:
                raise ServiceInputError(
                    f"report marks video-enabled segment {master_segment.id!r} as not provided"
                )
            if any(
                value is not None
                for value in (
                    report_segment.source_id,
                    report_segment.source_in_seconds,
                    report_segment.source_out_seconds,
                    report_segment.method,
                )
            ):
                raise ServiceInputError(
                    f"audio-only report segment {master_segment.id!r} contains source data"
                )
            assignments[master_segment.id] = VideoAssignment.not_provided()
            continue

        if report_segment.video_status is not VideoStatus.MATCHED:
            raise ServiceInputError(
                f"report segment {master_segment.id!r} is not safe for planning"
            )
        source_id = report_segment.source_id
        source_in = report_segment.source_in_seconds
        source_out = report_segment.source_out_seconds
        if source_id is None or source_in is None or source_out is None:
            raise ServiceInputError(
                f"matched report segment {master_segment.id!r} lacks source bounds"
            )
        if report_segment.blockers:
            raise ServiceInputError(
                f"matched report segment {master_segment.id!r} still contains blockers"
            )
        if report_segment.method not in {"automatic", "manual"}:
            raise ServiceInputError(
                f"matched report segment {master_segment.id!r} has an invalid method"
            )
        expected_source_out = source_in + (
            master_segment.end_seconds - master_segment.start_seconds
        )
        if source_out != expected_source_out:
            raise ServiceInputError(
                f"report segment {master_segment.id!r} source duration differs from the master"
            )
        source = sources_by_id.get(source_id)
        if source is None or source not in configured_sources:
            raise ServiceInputError(
                f"report segment {master_segment.id!r} selects an ineligible source"
            )
        source_item = context.source_items[source.id]
        assignments[master_segment.id] = VideoAssignment(
            status=VideoStatus.MATCHED,
            source_id=source.id,
            media=MediaDescriptor(
                media_id=source_item.media_id,
                name=source_item.name,
                duration_seconds=_media_duration(source_item),
                frame_rate=FrameRate.parse(source_item.frame_rate),
            ),
            source_in_seconds=source_in,
            predicted_source_out_seconds=source_out,
            method=report_segment.method,
            warnings=report_segment.warnings,
            blockers=report_segment.blockers,
        )

    try:
        return create_edit_plan(_planning_inputs(context, assignments))
    except PlanningError as error:
        raise ServiceInputError(f"report cannot reproduce a safe edit plan: {error}") from error


class MultiCamSyncService:
    """Application service with injectable media, matcher, and Resolve boundaries."""

    def __init__(
        self,
        *,
        gateway: GatewayLike,
        media_reader: MediaReader,
        matcher: SegmentMatcher | None = None,
    ) -> None:
        self._gateway = gateway
        self._media_reader = media_reader
        self._matcher = matcher or SegmentMatcher()

    @classmethod
    def production(cls) -> MultiCamSyncService:
        reader = CachingMediaReader(FFmpegMediaReader(), AnalysisCache())
        return cls(gateway=cast("ResolveGateway", DaVinciResolveGateway()), media_reader=reader)

    def validate(self, config_path: Path) -> ValidationContext:
        """Perform every read-only check that does not require full audio decode."""
        spec = load_project_spec(config_path)
        config_bytes = _read_bytes(spec.config_path, "configuration")
        cuts_bytes = _read_bytes(spec.project.cuts_file, "cut list")
        try:
            cuts_text = cuts_bytes.decode("utf-8-sig")
        except UnicodeDecodeError as error:
            raise ServiceInputError(
                f"cut list is not valid UTF-8: {spec.project.cuts_file}"
            ) from error
        cuts = parse_cut_list(cuts_text)

        master_selector = _selector(
            spec.master.media_pool_folder, spec.master.media_pool_name, "master"
        )
        source_selectors = {
            source.id: _selector(source.media_pool_folder, source.media_pool_name, "video")
            for source in spec.sources
        }
        ordered_selectors = tuple(
            dict.fromkeys(
                (master_selector, *(source_selectors[source.id] for source in spec.sources))
            )
        )
        snapshot = self._gateway.snapshot(ordered_selectors)
        if spec.project.timeline_name in snapshot.timeline_names:
            raise ResolvePreflightError(
                "validate target timeline",
                f"timeline {spec.project.timeline_name!r} already exists",
            )

        master_item = _snapshot_item(snapshot, master_selector)
        source_items = {
            source.id: _snapshot_item(snapshot, source_selectors[source.id])
            for source in spec.sources
        }
        master_path = _physical_path(spec.master.audio_path, master_item, "master.audio_path")
        source_paths = {
            source.id: _physical_path(
                source.audio_reference_path,
                source_items[source.id],
                f"sources[{source.id}].audio_reference_path",
            )
            for source in spec.sources
        }
        additional_source_paths = {
            source.id: tuple(
                path.expanduser().resolve(strict=False)
                for path in source.additional_audio_reference_paths
            )
            for source in spec.sources
        }

        master_probe = self._media_reader.probe(master_path)
        master_resolve_duration = _media_duration(master_item)
        frame_tolerance = Decimal(2) / snapshot.timeline_frame_rate
        if master_probe.duration_seconds > master_resolve_duration + frame_tolerance:
            raise ServiceInputError(
                "master audio file is longer than the selected Resolve master item "
                "by more than two frames"
            )
        if master_resolve_duration > master_probe.duration_seconds + frame_tolerance:
            raise ServiceInputError(
                "master audio file is shorter than the selected Resolve master item "
                "by more than two frames"
            )
        segments = build_master_segments(cuts, master_resolve_duration)

        source_probes: dict[str, MediaProbe] = {}
        additional_source_probes: dict[str, tuple[MediaProbe, ...]] = {}
        for source in spec.sources:
            reference_paths = (source_paths[source.id], *additional_source_paths[source.id])
            if len(set(reference_paths)) != len(reference_paths):
                raise ServiceInputError(
                    f"source {source.id!r} audio reference paths must be unique"
                )
            probe = self._media_reader.probe(reference_paths[0])
            fallback_probes: list[MediaProbe] = []
            for reference_index, path in enumerate(reference_paths[1:], start=1):
                fallback_probe = self._media_reader.probe(path)
                if fallback_probe.duration_seconds != probe.duration_seconds:
                    raise ServiceInputError(
                        f"source {source.id!r} additional audio reference {reference_index} "
                        f"duration {fallback_probe.duration_seconds} differs from primary "
                        f"duration {probe.duration_seconds}; fallback references must have "
                        "exactly the same length"
                    )
                fallback_probes.append(fallback_probe)
            start = source.source_start
            end = source.source_end or probe.duration_seconds
            if start >= probe.duration_seconds or end > probe.duration_seconds:
                raise ServiceInputError(
                    f"source {source.id!r} bounds {start}..{end} exceed reference duration "
                    f"{probe.duration_seconds}"
                )
            resolve_duration = _media_duration(source_items[source.id])
            if end > resolve_duration + frame_tolerance:
                raise ServiceInputError(
                    f"source {source.id!r} bounds exceed its Resolve item duration"
                )
            for search_range in source.segment_search_ranges:
                if search_range.source_end > end:
                    raise ServiceInputError(
                        f"source {source.id!r} search range for "
                        f"{search_range.segment_id!r} exceeds reference duration {end}"
                    )
            source_probes[source.id] = probe
            additional_source_probes[source.id] = tuple(fallback_probes)

        return ValidationContext(
            spec=spec,
            cuts_text=cuts_text,
            cuts_hash=_sha256_bytes(cuts_bytes),
            configuration_hash=_sha256_bytes(config_bytes),
            segments=segments,
            snapshot=snapshot,
            master_item=master_item,
            source_items=source_items,
            master_path=master_path,
            source_paths=source_paths,
            additional_source_paths=additional_source_paths,
            master_probe=master_probe,
            source_probes=source_probes,
            additional_source_probes=additional_source_probes,
        )

    def analyze(
        self, config_path: Path, *, progress: ProgressCallback | None = None
    ) -> AnalysisOutcome:
        """Analyze supplied takes and return a complete report without mutating Resolve."""
        _notify(
            progress,
            ProgressEvent(0, ANALYZE_STEP_COUNT, "Validating configuration and Resolve media"),
        )
        context = self.validate(config_path)
        timeline_rate = FrameRate.parse(context.snapshot.timeline_frame_rate)
        settings = AlignmentSettings(
            timeline_frame_rate=Fraction(
                timeline_rate.numerator,
                timeline_rate.denominator,
            )
        )
        enabled = context.enabled_take_keys
        master_audio = None
        if enabled:
            _notify(progress, ProgressEvent(1, ANALYZE_STEP_COUNT, "Loading master analysis audio"))
            master_audio = self._media_reader.load_audio(AudioRequest(context.master_path))
        else:
            _notify(
                progress,
                ProgressEvent(1, ANALYZE_STEP_COUNT, "Skipping audio decode; no video is enabled"),
            )

        sources_by_id = {source.id: source for source in context.spec.sources}
        loaded_candidates: dict[tuple[str, int], AlignmentCandidate] = {}
        segment_reports: list[SegmentReport] = []
        assignments: dict[str, VideoAssignment] = {}
        unsafe_count = 0
        enabled_segment_count = sum(segment.take_key in enabled for segment in context.segments)
        enabled_segment_index = 0
        if not enabled_segment_count:
            _notify(
                progress,
                ProgressEvent(2, ANALYZE_STEP_COUNT, "Skipping alignment; no video is enabled"),
            )

        for segment in context.segments:
            assert segment.end_seconds is not None
            sources = context.spec.sources_by_take.get(segment.take_key, ())
            if not sources:
                assignments[segment.id] = VideoAssignment.not_provided()
                segment_reports.append(
                    SegmentReport(
                        segment_id=segment.id,
                        index=segment.index,
                        take=segment.display_take,
                        take_key=segment.take_key,
                        master_start_seconds=segment.start_seconds,
                        master_end_seconds=segment.end_seconds,
                        video_status=VideoStatus.NOT_PROVIDED,
                    )
                )
                continue

            enabled_segment_index += 1
            _notify(
                progress,
                ProgressEvent(
                    2,
                    ANALYZE_STEP_COUNT,
                    f"Aligning {segment.id} ({segment.display_take})",
                    item_index=enabled_segment_index,
                    item_total=enabled_segment_count,
                ),
            )
            assert master_audio is not None
            segment_request = SegmentRequest(
                segment_id=segment.id,
                take=segment.display_take,
                master_start_seconds=segment.start_seconds,
                master_end_seconds=segment.end_seconds,
            )
            max_reference_count = max(
                len(_source_reference_paths(context, source)) for source in sources
            )
            reference_attempts: list[tuple[int, SegmentMatch]] = []
            for reference_index in range(max_reference_count):
                candidates: list[AlignmentCandidate] = []
                for source in sources:
                    manual_offset = source.manual_offset_for(segment.id)
                    if manual_offset is not None and reference_index > 0:
                        # A manual offset is independent of microphone choice. Evaluate it
                        # exactly once while preserving fallbacks for automatic segments.
                        continue
                    reference_paths = _source_reference_paths(context, source)
                    if reference_index >= len(reference_paths):
                        continue
                    candidate_key = (source.id, reference_index)
                    base_candidate = loaded_candidates.get(candidate_key)
                    if base_candidate is None:
                        audio = self._media_reader.load_audio(
                            AudioRequest(
                                reference_paths[reference_index],
                                source_start_seconds=source.source_start,
                                source_end_seconds=source.source_end,
                                sample_rate=settings.sample_rate,
                            )
                        )
                        base_candidate = AlignmentCandidate(
                            source_id=source.id,
                            audio=audio,
                            source_start_seconds=source.source_start,
                            source_end_seconds=source.source_end,
                            audio_reference_id=_audio_reference_id(reference_index),
                        )
                        loaded_candidates[candidate_key] = base_candidate
                    search_range = source.search_range_for(segment.id)
                    candidate = (
                        AlignmentCandidate(
                            source_id=source.id,
                            audio=base_candidate.audio,
                            source_start_seconds=(
                                search_range.source_start
                                if search_range is not None
                                else base_candidate.source_start_seconds
                            ),
                            source_end_seconds=(
                                search_range.source_end
                                if search_range is not None
                                else base_candidate.source_end_seconds
                            ),
                            manual_offset_seconds=manual_offset,
                            audio_reference_id=base_candidate.audio_reference_id,
                        )
                        if search_range is not None or manual_offset is not None
                        else base_candidate
                    )
                    candidates.append(candidate)

                if not candidates:
                    continue
                attempt = self._matcher.match(
                    segment_request,
                    master_audio,
                    candidates,
                    settings,
                )
                reference_attempts.append((reference_index, attempt))
                if attempt.safe_for_planning:
                    break
            match = _merge_reference_attempts(reference_attempts)
            status = VideoStatus.MATCHED if match.safe_for_planning else VideoStatus.UNSAFE
            if status is VideoStatus.UNSAFE:
                unsafe_count += 1
            source_spec: SourceSpec | None = (
                sources_by_id.get(match.source_id) if match.source_id is not None else None
            )
            source_media = (
                MediaDescriptor(
                    media_id=context.source_items[source_spec.id].media_id,
                    name=context.source_items[source_spec.id].name,
                    duration_seconds=_media_duration(context.source_items[source_spec.id]),
                    frame_rate=FrameRate.parse(context.source_items[source_spec.id].frame_rate),
                )
                if source_spec is not None
                else None
            )
            assignments[segment.id] = VideoAssignment(
                status=status,
                source_id=match.source_id,
                media=source_media,
                source_in_seconds=match.source_in_seconds,
                predicted_source_out_seconds=match.diagnostics.mapped_source_end_seconds,
                method=match.method.value,
                warnings=match.warnings,
                blockers=tuple(blocker.value for blocker in match.blockers),
            )
            segment_reports.append(
                SegmentReport(
                    segment_id=segment.id,
                    index=segment.index,
                    take=segment.display_take,
                    take_key=segment.take_key,
                    master_start_seconds=segment.start_seconds,
                    master_end_seconds=segment.end_seconds,
                    video_status=status,
                    source_id=match.source_id,
                    source_in_seconds=match.source_in_seconds,
                    source_out_seconds=match.source_out_seconds,
                    method=match.method.value,
                    blockers=tuple(blocker.value for blocker in match.blockers),
                    warnings=match.warnings,
                    diagnostics=_diagnostics_dict(match.diagnostics),
                    candidates=tuple(_candidate_dict(candidate) for candidate in match.candidates),
                )
            )

        _notify(
            progress,
            ProgressEvent(3, ANALYZE_STEP_COUNT, "Preparing alignment results and edit plan"),
        )
        plan: EditPlan | None = None
        if unsafe_count == 0:
            plan = create_edit_plan(_planning_inputs(context, assignments))

        _notify(progress, ProgressEvent(4, ANALYZE_STEP_COUNT, "Fingerprinting input media"))
        report = AlignmentReport(
            tool_version=__version__,
            created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            run_id=str(uuid4()),
            config_path=str(context.spec.config_path),
            configuration_hash=context.configuration_hash,
            cuts_hash=context.cuts_hash,
            alignment_settings=settings.as_dict(),
            project_snapshot=context.snapshot,
            input_files=_input_file_records(context),
            segments=tuple(segment_reports),
            plan=plan,
        )
        return AnalysisOutcome(report=report, unsafe_count=unsafe_count)

    def build(
        self,
        config_path: Path,
        report: AlignmentReport,
        *,
        progress: ProgressCallback | None = None,
    ) -> BuildResult:
        """Reject every stale dimension before calling the one mutation gateway."""
        _notify(
            progress,
            ProgressEvent(1, BUILD_STEP_COUNT, "Validating report and current Resolve project"),
        )
        if report.report_schema_version != 1:
            raise ServiceInputError("unsupported report schema")
        if report.tool_version != __version__:
            raise ServiceInputError(
                f"report tool version {report.tool_version!r} differs from {__version__!r}"
            )
        if not report.safe_to_build or report.plan is None:
            raise ServiceInputError(
                "report has no safe edit plan; run analyze and resolve unsafe matches"
            )

        current = self.validate(config_path)
        if current.configuration_hash != report.configuration_hash:
            raise ServiceInputError("configuration changed after analysis; analyze again")
        if current.cuts_hash != report.cuts_hash:
            raise ServiceInputError("cut list changed after analysis; analyze again")
        if str(current.spec.config_path) != report.config_path:
            raise ServiceInputError("report belongs to a different configuration path")
        if current.snapshot.fingerprint != report.project_snapshot.fingerprint:
            raise ResolvePreflightError(
                "compare Resolve snapshot",
                "project, timelines, settings, or selected media changed after analysis",
            )

        _notify(
            progress,
            ProgressEvent(2, BUILD_STEP_COUNT, "Checking input fingerprints and settings"),
        )
        if _input_file_records(current) != report.input_files:
            raise ServiceInputError("an input media file changed after analysis; analyze again")

        current_rate = FrameRate.parse(current.snapshot.timeline_frame_rate)
        expected_settings = AlignmentSettings(
            timeline_frame_rate=Fraction(current_rate.numerator, current_rate.denominator)
        ).as_dict()
        if dict(report.alignment_settings) != expected_settings:
            raise ServiceInputError("alignment settings differ from the report; analyze again")

        _notify(
            progress,
            ProgressEvent(3, BUILD_STEP_COUNT, "Reproducing the reviewed edit plan"),
        )
        reproduced_plan = _recreate_report_plan(current, report)
        if reproduced_plan != report.plan:
            raise ServiceInputError("embedded edit plan differs from current inputs and matches")

        _notify(
            progress,
            ProgressEvent(4, BUILD_STEP_COUNT, "Building and verifying the Resolve timeline"),
        )
        return self._gateway.build_timeline(cast("EditPlanLike", report.plan))
