"""Read-only validation/analysis orchestration and one-shot timeline builds."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
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
    MatchStatus,
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
    master_probe: MediaProbe
    source_probes: Mapping[str, MediaProbe]

    @property
    def enabled_take_keys(self) -> frozenset[str]:
        return frozenset(self.spec.sources_by_take)


@dataclass(frozen=True, slots=True)
class AnalysisOutcome:
    report: AlignmentReport
    unsafe_count: int


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

        master_probe = self._media_reader.probe(master_path)
        segments = build_master_segments(cuts, master_probe.duration_seconds)
        master_resolve_duration = _media_duration(master_item)
        frame_tolerance = Decimal(2) / snapshot.timeline_frame_rate
        if master_probe.duration_seconds > master_resolve_duration + frame_tolerance:
            raise ServiceInputError(
                "master audio file is longer than the selected Resolve master item "
                "by more than two frames"
            )

        source_probes: dict[str, MediaProbe] = {}
        for source in spec.sources:
            probe = self._media_reader.probe(source_paths[source.id])
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
            source_probes[source.id] = probe

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
            master_probe=master_probe,
            source_probes=source_probes,
        )

    def analyze(self, config_path: Path) -> AnalysisOutcome:
        """Analyze supplied takes and return a complete report without mutating Resolve."""
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
            master_audio = self._media_reader.load_audio(AudioRequest(context.master_path))

        sources_by_id = {source.id: source for source in context.spec.sources}
        loaded_candidates: dict[str, AlignmentCandidate] = {}
        segment_reports: list[SegmentReport] = []
        assignments: dict[str, VideoAssignment] = {}
        unsafe_count = 0

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

            candidates: list[AlignmentCandidate] = []
            for source in sources:
                candidate = loaded_candidates.get(source.id)
                if candidate is None:
                    audio = self._media_reader.load_audio(
                        AudioRequest(
                            context.source_paths[source.id],
                            source_start_seconds=source.source_start,
                            source_end_seconds=source.source_end,
                            sample_rate=settings.sample_rate,
                        )
                    )
                    candidate = AlignmentCandidate(
                        source_id=source.id,
                        audio=audio,
                        source_start_seconds=source.source_start,
                        source_end_seconds=source.source_end,
                        manual_offset_seconds=source.manual_offset_seconds,
                    )
                    loaded_candidates[source.id] = candidate
                candidates.append(candidate)

            assert master_audio is not None
            match = self._matcher.match(
                SegmentRequest(
                    segment_id=segment.id,
                    take=segment.display_take,
                    master_start_seconds=segment.start_seconds,
                    master_end_seconds=segment.end_seconds,
                ),
                master_audio,
                candidates,
                settings,
            )
            status = (
                VideoStatus.MATCHED if match.status is MatchStatus.MATCHED else VideoStatus.UNSAFE
            )
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

        plan: EditPlan | None = None
        if unsafe_count == 0:
            plan = create_edit_plan(_planning_inputs(context, assignments))

        files = [
            InputFileRecord(
                role="master",
                source_id=None,
                fingerprint=fingerprint_file(context.master_path),
            )
        ]
        files.extend(
            InputFileRecord(
                role="source",
                source_id=source.id,
                fingerprint=fingerprint_file(context.source_paths[source.id]),
            )
            for source in context.spec.sources
        )
        report = AlignmentReport(
            tool_version=__version__,
            created_at_utc=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            run_id=str(uuid4()),
            config_path=str(context.spec.config_path),
            configuration_hash=context.configuration_hash,
            cuts_hash=context.cuts_hash,
            alignment_settings=settings.as_dict(),
            project_snapshot=context.snapshot,
            input_files=tuple(files),
            segments=tuple(segment_reports),
            plan=plan,
        )
        return AnalysisOutcome(report=report, unsafe_count=unsafe_count)

    def build(self, config_path: Path, report: AlignmentReport) -> BuildResult:
        """Reject every stale dimension before calling the one mutation gateway."""
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

        current_files = [InputFileRecord("master", None, fingerprint_file(current.master_path))]
        current_files.extend(
            InputFileRecord(
                "source",
                source.id,
                fingerprint_file(current.source_paths[source.id]),
            )
            for source in current.spec.sources
        )
        if tuple(current_files) != report.input_files:
            raise ServiceInputError("an input media file changed after analysis; analyze again")

        current_rate = FrameRate.parse(current.snapshot.timeline_frame_rate)
        expected_settings = AlignmentSettings(
            timeline_frame_rate=Fraction(current_rate.numerator, current_rate.denominator)
        ).as_dict()
        if dict(report.alignment_settings) != expected_settings:
            raise ServiceInputError("alignment settings differ from the report; analyze again")

        reproduced_plan = _recreate_report_plan(current, report)
        if reproduced_plan != report.plan:
            raise ServiceInputError("embedded edit plan differs from current inputs and matches")

        return self._gateway.build_timeline(cast("EditPlanLike", report.plan))
