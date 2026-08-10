from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import pytest

from multi_cam_sync.planning import VideoStatus
from multi_cam_sync.reporting import AlignmentReport, read_report, write_report
from multi_cam_sync.services import AnalysisOutcome, MultiCamSyncService, ValidationContext

REPOSITORY_ROOT = Path(__file__).parents[1]
ARABESQUES_CUTS = REPOSITORY_ROOT / "examples" / "Arabesques_composite_cuts.txt"
ALLOW_MUTATION = "MULTI_CAM_SYNC_ALLOW_MUTATION"


class LiveAuthorizationError(RuntimeError):
    """A live workflow was configured without all safety acknowledgements."""


@dataclass(frozen=True, slots=True)
class AcceptanceEnvironment:
    config: Path
    report: Path
    project_name: str
    timeline_name: str


def _required_value(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise LiveAuthorizationError(f"set {name} explicitly before running this workflow")
    return value


def _acceptance_environment(prefix: str, *, require_disposable: bool) -> AcceptanceEnvironment:
    config_variable = f"MULTI_CAM_SYNC_{prefix}_CONFIG"
    configured_path = os.environ.get(config_variable, "").strip()
    if not configured_path:
        pytest.skip(f"set {config_variable} to opt in")
    if os.environ.get(ALLOW_MUTATION) != "1":
        raise LiveAuthorizationError(
            f"refusing Resolve mutation: set {ALLOW_MUTATION}=1 only for an authorized run"
        )
    if require_disposable and os.environ.get("MULTI_CAM_SYNC_LIVE_CONFIRM_DISPOSABLE") != "1":
        raise LiveAuthorizationError(
            "refusing live smoke build: set MULTI_CAM_SYNC_LIVE_CONFIRM_DISPOSABLE=1 "
            "after opening a disposable Resolve project"
        )

    config = Path(configured_path).expanduser()
    report = Path(_required_value(f"MULTI_CAM_SYNC_{prefix}_REPORT")).expanduser()
    if not config.is_absolute() or not report.is_absolute():
        raise LiveAuthorizationError("live configuration and report paths must be absolute")
    if not config.is_file():
        raise LiveAuthorizationError(f"configured TOML does not exist: {config}")

    return AcceptanceEnvironment(
        config=config.resolve(),
        report=report.resolve(strict=False),
        project_name=_required_value(f"MULTI_CAM_SYNC_{prefix}_PROJECT"),
        timeline_name=_required_value(f"MULTI_CAM_SYNC_{prefix}_TIMELINE"),
    )


def _assert_expected_target(context: ValidationContext, environment: AcceptanceEnvironment) -> None:
    assert context.snapshot.project_name == environment.project_name, (
        "Resolve has the wrong current project; no mutation was attempted"
    )
    assert context.spec.project.timeline_name == environment.timeline_name, (
        "configuration timeline_name does not match the explicitly authorized timeline"
    )
    assert environment.timeline_name not in context.snapshot.timeline_names


def _review_partial_report(
    context: ValidationContext, outcome: AnalysisOutcome, report: AlignmentReport
) -> None:
    enabled = context.enabled_take_keys
    all_takes = {segment.take_key for segment in context.segments}
    assert 1 <= len(enabled) <= 2, "acceptance config must supply only one or two logical takes"
    assert enabled < all_takes, "acceptance config must retain at least one audio-only take"
    assert outcome.unsafe_count == 0
    assert report.safe_to_build
    assert report.plan is not None
    assert len(report.segments) == len(context.segments)

    matched_count = 0
    gap_count = 0
    for master_segment, report_segment, planned_segment in zip(
        context.segments, report.segments, report.plan.segments, strict=True
    ):
        assert report_segment.segment_id == master_segment.id
        assert planned_segment.segment_id == master_segment.id
        if master_segment.take_key in enabled:
            assert report_segment.video_status is VideoStatus.MATCHED
            assert planned_segment.video_clip is not None
            assert planned_segment.video_gap is None
            matched_count += 1
        else:
            assert report_segment.video_status is VideoStatus.NOT_PROVIDED
            assert planned_segment.video_clip is None
            assert planned_segment.video_gap is not None
            gap_count += 1

    assert matched_count == len(report.plan.video_clips) > 0
    assert gap_count == len(report.plan.video_gaps) > 0
    for left, right in pairwise(report.plan.audio_clips):
        assert left.record_end_frame == right.record_start_frame
    report.plan.validate()


def _validated_analyze_build(
    environment: AcceptanceEnvironment,
    *,
    context_check: Callable[[ValidationContext], None] | None = None,
) -> tuple[ValidationContext, AlignmentReport]:
    service = MultiCamSyncService.production()

    # Everything through report review is read-only. Mutation happens only at the final call.
    context = service.validate(environment.config)
    _assert_expected_target(context, environment)
    if context_check is not None:
        context_check(context)
    outcome = service.analyze(environment.config)
    write_report(environment.report, outcome.report)
    report = read_report(environment.report)
    _review_partial_report(context, outcome, report)

    result = service.build(environment.config, report)
    assert result.verified
    assert result.timeline_name == environment.timeline_name
    assert report.plan is not None
    assert result.audio_item_count == len(report.plan.audio_clips)
    assert result.video_item_count == len(report.plan.video_clips)
    assert result.marker_count == len(report.plan.markers)
    return context, report


def _assert_arabesques_context(context: ValidationContext) -> None:
    assert context.spec.project.cuts_file.samefile(ARABESQUES_CUTS)
    assert len(context.segments) == 29
    sources_by_take = context.spec.sources_by_take
    if "Take 8 A" in sources_by_take and "Take 8 B" in sources_by_take:
        first = sources_by_take["Take 8 A"][0]
        second = sources_by_take["Take 8 B"][0]
        assert (first.media_pool_folder, first.media_pool_name) == (
            second.media_pool_folder,
            second.media_pool_name,
        )
        assert first.audio_reference_path == second.audio_reference_path


def test_live_guard_refuses_mutation_without_explicit_authorization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = tmp_path / "live.toml"
    config.write_text("schema_version = 1\n", encoding="utf-8")
    monkeypatch.setenv("MULTI_CAM_SYNC_LIVE_CONFIG", str(config))
    monkeypatch.setenv("MULTI_CAM_SYNC_LIVE_REPORT", str(tmp_path / "report.json"))
    monkeypatch.setenv("MULTI_CAM_SYNC_LIVE_PROJECT", "Disposable project")
    monkeypatch.setenv("MULTI_CAM_SYNC_LIVE_TIMELINE", "Unique smoke timeline")
    monkeypatch.setenv("MULTI_CAM_SYNC_LIVE_CONFIRM_DISPOSABLE", "1")
    monkeypatch.delenv(ALLOW_MUTATION, raising=False)

    with pytest.raises(LiveAuthorizationError, match="refusing Resolve mutation"):
        _acceptance_environment("LIVE", require_disposable=True)


@pytest.mark.resolve_live
def test_disposable_resolve_partial_video_build_is_verified_and_left_for_review() -> None:
    environment = _acceptance_environment("LIVE", require_disposable=True)

    _validated_analyze_build(environment)


@pytest.mark.arabesques_acceptance
def test_arabesques_partial_video_workflow_builds_all_29_segments() -> None:
    environment = _acceptance_environment("ARABESQUES", require_disposable=False)

    context, report = _validated_analyze_build(
        environment, context_check=_assert_arabesques_context
    )

    assert len(context.segments) == 29
    assert report.plan is not None
    assert len(report.plan.markers) == 28
