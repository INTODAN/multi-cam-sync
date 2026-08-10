"""Versioned alignment reports and deterministic JSON I/O."""

from multi_cam_sync.reporting.io import canonical_payload, read_report, write_report
from multi_cam_sync.reporting.models import (
    REPORT_SCHEMA_VERSION,
    AlignmentReport,
    InputFileRecord,
    ReportError,
    SegmentReport,
)

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "AlignmentReport",
    "InputFileRecord",
    "ReportError",
    "SegmentReport",
    "canonical_payload",
    "read_report",
    "write_report",
]
