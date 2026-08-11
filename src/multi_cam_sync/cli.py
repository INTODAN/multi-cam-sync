"""Command-line interface for safe validation, analysis, and Resolve builds."""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol, TextIO

from multi_cam_sync import __version__

# This side-effect import rejects unsafe sub-interpreters before the native imports below.
from multi_cam_sync._runtime import MAIN_INTERPRETER_RUNTIME  # noqa: F401
from multi_cam_sync.alignment import AlignmentError
from multi_cam_sync.domain import DomainError
from multi_cam_sync.media import MediaError
from multi_cam_sync.progress import (
    ANALYZE_STEP_COUNT,
    BUILD_STEP_COUNT,
    ProgressCallback,
    ProgressDisplay,
    ProgressEvent,
)
from multi_cam_sync.reporting import AlignmentReport, ReportError, read_report, write_report
from multi_cam_sync.resolve import (
    BuildResult,
    ResolveBuildError,
    ResolveError,
    ResolveVerificationError,
)
from multi_cam_sync.services import (
    AnalysisOutcome,
    MultiCamSyncService,
    ServiceInputError,
    ValidationContext,
)


class ServiceLike(Protocol):
    def validate(self, config_path: Path) -> ValidationContext: ...

    def analyze(
        self, config_path: Path, *, progress: ProgressCallback | None = None
    ) -> AnalysisOutcome: ...

    def build(
        self,
        config_path: Path,
        report: AlignmentReport,
        *,
        progress: ProgressCallback | None = None,
    ) -> BuildResult: ...


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="multi-cam-sync",
        description="Synchronize selected multicam takes to a composite master in DaVinci Resolve.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--verbose", action="store_true", help="show tracebacks for failures")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate inputs without changing Resolve")
    validate.add_argument("config", type=Path, help="version-1 project TOML")

    analyze = commands.add_parser("analyze", help="align supplied video takes and write a report")
    analyze.add_argument("config", type=Path, help="version-1 project TOML")
    analyze.add_argument("--report", type=Path, required=True, help="output JSON report")

    build = commands.add_parser("build", help="build a verified timeline from a fresh report")
    build.add_argument("config", type=Path, help="version-1 project TOML")
    build.add_argument("--report", type=Path, required=True, help="existing JSON report")
    return parser


def _validation_summary(context, stream: TextIO) -> None:  # type: ignore[no-untyped-def]
    enabled = context.enabled_take_keys
    matched_segments = sum(segment.take_key in enabled for segment in context.segments)
    print(
        f"Valid: {len(context.segments)} master segments, "
        f"{matched_segments} video-enabled, {len(context.segments) - matched_segments} audio-only",
        file=stream,
    )
    print(
        f"Resolve project: {context.snapshot.project_name}; "
        f"target timeline: {context.spec.project.timeline_name}",
        file=stream,
    )


def _analysis_summary(outcome, report_path: Path, stream: TextIO) -> None:  # type: ignore[no-untyped-def]
    counts = {"matched": 0, "not_provided": 0, "unsafe": 0}
    for segment in outcome.report.segments:
        counts[segment.video_status.value] += 1
    print(
        "Analysis: "
        f"{counts['matched']} matched, {counts['not_provided']} audio-only, "
        f"{counts['unsafe']} unsafe",
        file=stream,
    )
    print(f"Report: {report_path}", file=stream)
    for segment in outcome.report.segments:
        if segment.video_status.value == "unsafe":
            reason = ", ".join(segment.blockers) or "unknown blocker"
            print(f"  {segment.segment_id} ({segment.take}): {reason}", file=stream)


def main(
    argv: Sequence[str] | None = None,
    *,
    service: ServiceLike | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Run one command and return its stable process exit code."""
    output = stdout or sys.stdout
    errors = stderr or sys.stderr
    parser = build_parser()
    args = parser.parse_args(argv)
    active_service = service or MultiCamSyncService.production()
    active_progress: ProgressDisplay | None = None

    try:
        if args.command == "validate":
            context = active_service.validate(args.config)
            _validation_summary(context, output)
            return 0
        if args.command == "analyze":
            active_progress = ProgressDisplay("Analyze", errors)
            outcome = active_service.analyze(args.config, progress=active_progress.update)
            active_progress.update(
                ProgressEvent(
                    ANALYZE_STEP_COUNT - 1, ANALYZE_STEP_COUNT, "Writing alignment report"
                )
            )
            write_report(args.report, outcome.report)
            active_progress.finish("Analysis complete")
            _analysis_summary(outcome, args.report, output)
            return 4 if outcome.unsafe_count else 0
        if args.command == "build":
            active_progress = ProgressDisplay("Build", errors)
            active_progress.update(ProgressEvent(0, BUILD_STEP_COUNT, "Reading alignment report"))
            report = read_report(args.report)
            result = active_service.build(
                args.config,
                report,
                progress=active_progress.update,
            )
            active_progress.finish("Build complete")
            print(
                f"Built and verified timeline {result.timeline_name!r}: "
                f"{result.audio_item_count} audio clips, {result.video_item_count} video clips, "
                f"{result.marker_count} markers",
                file=output,
            )
            return 0
        parser.error(f"unknown command: {args.command}")
    except (DomainError, ServiceInputError, MediaError, AlignmentError, ReportError) as error:
        if active_progress is not None:
            active_progress.fail()
        if args.verbose:
            traceback.print_exc(file=errors)
        else:
            print(f"Error: {error}", file=errors)
        return 2
    except ResolveError as error:
        if active_progress is not None:
            active_progress.fail()
        if args.verbose:
            traceback.print_exc(file=errors)
        else:
            print(f"Resolve error: {error}", file=errors)
        if args.command == "build" or isinstance(
            error, (ResolveBuildError, ResolveVerificationError)
        ):
            return 5
        return 3
    except Exception as error:  # pragma: no cover - defensive top-level boundary
        if active_progress is not None:
            active_progress.fail()
        if args.verbose:
            traceback.print_exc(file=errors)
        else:
            print(f"Internal error: {type(error).__name__}: {error}", file=errors)
        return 1
    return 2
