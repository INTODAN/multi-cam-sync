"""Immutable public domain types and project-owned errors."""

from multi_cam_sync.domain.errors import ConfigError, CutListError, DomainError, TimeValueError
from multi_cam_sync.domain.models import (
    CutTransition,
    MasterSegment,
    MasterSpec,
    ProjectSettings,
    ProjectSpec,
    SegmentManualOffset,
    SegmentSearchRange,
    SourceSpec,
)

__all__ = [
    "ConfigError",
    "CutListError",
    "CutTransition",
    "DomainError",
    "MasterSegment",
    "MasterSpec",
    "ProjectSettings",
    "ProjectSpec",
    "SegmentManualOffset",
    "SegmentSearchRange",
    "SourceSpec",
    "TimeValueError",
]
