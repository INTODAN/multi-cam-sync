from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from multi_cam_sync.media import ContentFingerprint
from multi_cam_sync.planning import (
    FrameRate,
    MediaDescriptor,
    PlanningInputs,
    SegmentInput,
    VideoAssignment,
    VideoStatus,
    create_edit_plan,
)
from multi_cam_sync.reporting import (
    AlignmentReport,
    InputFileRecord,
    ReportError,
    SegmentReport,
    read_report,
    write_report,
)
from multi_cam_sync.reporting.io import canonical_payload
from multi_cam_sync.resolve import MediaSelector, ResolvedMediaItem, ResolveProjectSnapshot


def _snapshot() -> ResolveProjectSnapshot:
    master_selector = MediaSelector.from_folder("Masters", "master.wav", "master")
    video_selector = MediaSelector.from_folder("Multicam", "take-a", "video")
    return ResolveProjectSnapshot(
        project_id="project-id",
        project_name="Project",
        timeline_frame_rate=Decimal(24),
        timeline_start_frame=86400,
        timeline_start_timecode="01:00:00:00",
        timeline_names=("Existing",),
        media=(
            ResolvedMediaItem(
                "master-id",
                master_selector,
                "master.wav",
                Path("/media/master.wav"),
                240,
                Decimal(24),
                {"File Path": "/media/master.wav"},
            ),
            ResolvedMediaItem(
                "video-id",
                video_selector,
                "take-a",
                Path("/media/take-a.mov"),
                480,
                Decimal(24),
                {"File Path": "/media/take-a.mov"},
            ),
        ),
    )


def _report(*, run_id: str = "run-1", created: str = "2026-01-01T00:00:00Z") -> AlignmentReport:
    snapshot = _snapshot()
    segments = (
        SegmentInput("segment-0001", 0, "Take A", "Take A", Decimal(0), Decimal(5)),
        SegmentInput("segment-0002", 1, "Take B", "Take B", Decimal(5), Decimal(10)),
    )
    source = MediaDescriptor("video-id", "take-a", Decimal(20), FrameRate(24))
    plan = create_edit_plan(
        PlanningInputs(
            timeline_name="Synced",
            timeline_rate=FrameRate(24),
            timeline_start_frame=86400,
            master_media=MediaDescriptor("master-id", "master", Decimal(10), FrameRate(24)),
            segments=segments,
            enabled_take_keys=frozenset({"Take A"}),
            assignments={
                "segment-0001": VideoAssignment(
                    status=VideoStatus.MATCHED,
                    source_id="source-a",
                    media=source,
                    source_in_seconds=Decimal(2),
                    predicted_source_out_seconds=Decimal(7),
                    method="automatic",
                )
            },
            expected_snapshot=snapshot,
        )
    )
    fingerprint = ContentFingerprint("/media/master.wav", 123, 456, "abc")
    return AlignmentReport(
        tool_version="0.1.0",
        created_at_utc=created,
        run_id=run_id,
        config_path="/project/project.toml",
        configuration_hash="config-hash",
        cuts_hash="cuts-hash",
        alignment_settings={"sample_rate": 22050, "edge": Decimal("0.15")},
        project_snapshot=snapshot,
        input_files=(InputFileRecord("master", None, fingerprint),),
        segments=(
            SegmentReport(
                "segment-0001",
                0,
                "Take A",
                "Take A",
                Decimal(0),
                Decimal(5),
                VideoStatus.MATCHED,
                source_id="source-a",
                source_in_seconds=Decimal(2),
                source_out_seconds=Decimal(7),
                method="automatic",
                diagnostics={"coverage": 1.0},
            ),
            SegmentReport(
                "segment-0002",
                1,
                "Take B",
                "Take B",
                Decimal(5),
                Decimal(10),
                VideoStatus.NOT_PROVIDED,
            ),
        ),
        plan=plan,
    )


def test_report_round_trip_is_stable_and_revalidates_plan(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "report.json"
    report = _report()
    write_report(path, report)
    loaded = read_report(path)
    assert loaded.plan is not None
    loaded.plan.validate()
    assert canonical_payload(loaded) == canonical_payload(report)
    assert path.read_bytes().endswith(b"\n")
    assert not list(path.parent.glob("*.tmp"))


def test_canonical_payload_excludes_only_volatile_fields() -> None:
    first = _report()
    second = _report(run_id="run-2", created="2026-01-02T00:00:00Z")
    assert canonical_payload(first) == canonical_payload(second)


def test_report_rejects_unknown_schema_and_invalid_json(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    path.write_text('{"report_schema_version": 999}', encoding="utf-8")
    with pytest.raises(ReportError, match="unsupported"):
        read_report(path)
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ReportError, match="invalid JSON"):
        read_report(path)
    path.write_text('{"alignment_settings": {"cost": NaN}}', encoding="utf-8")
    with pytest.raises(ReportError, match="numeric constant"):
        read_report(path)


def test_report_rejects_nan(tmp_path: Path) -> None:
    report = _report()
    bad = replace(report, alignment_settings={"cost": float("nan")})
    with pytest.raises(ReportError, match="NaN"):
        write_report(tmp_path / "bad.json", bad)
