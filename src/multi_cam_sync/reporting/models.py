"""Stable public report models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from multi_cam_sync.media import ContentFingerprint
from multi_cam_sync.planning import EditPlan, VideoStatus
from multi_cam_sync.resolve import ResolveProjectSnapshot

REPORT_SCHEMA_VERSION = 1


class ReportError(RuntimeError):
    """A report cannot be read, validated, or written safely."""


@dataclass(frozen=True, slots=True)
class InputFileRecord:
    """A fingerprinted file used during analysis."""

    role: str
    source_id: str | None
    fingerprint: ContentFingerprint


@dataclass(frozen=True, slots=True)
class SegmentReport:
    """Review data for one master segment."""

    segment_id: str
    index: int
    take: str
    take_key: str
    master_start_seconds: Decimal
    master_end_seconds: Decimal
    video_status: VideoStatus
    source_id: str | None = None
    source_in_seconds: Decimal | None = None
    source_out_seconds: Decimal | None = None
    method: str | None = None
    blockers: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    diagnostics: Mapping[str, object] | None = None
    candidates: tuple[Mapping[str, object], ...] = ()
    suggested_manual_offset_seconds: Decimal | None = None


@dataclass(frozen=True, slots=True)
class AlignmentReport:
    """A deterministic analysis result plus volatile audit metadata."""

    tool_version: str
    created_at_utc: str
    run_id: str
    config_path: str
    configuration_hash: str
    cuts_hash: str
    alignment_settings: Mapping[str, object]
    project_snapshot: ResolveProjectSnapshot
    input_files: tuple[InputFileRecord, ...]
    segments: tuple[SegmentReport, ...]
    plan: EditPlan | None
    report_schema_version: int = REPORT_SCHEMA_VERSION

    @property
    def safe_to_build(self) -> bool:
        return self.plan is not None and all(
            segment.video_status is not VideoStatus.UNSAFE for segment in self.segments
        )
