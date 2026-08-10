"""Pure edit planning for DaVinci Resolve timelines."""

from multi_cam_sync.planning.frame_math import FrameRate, seconds_to_frame
from multi_cam_sync.planning.models import (
    EditPlan,
    MediaDescriptor,
    PlannedClip,
    PlannedGap,
    PlannedMarker,
    PlannedSegment,
    PlanningInputs,
    SegmentInput,
    VideoAssignment,
    VideoStatus,
)
from multi_cam_sync.planning.planner import PlanningError, create_edit_plan, validate_edit_plan

__all__ = [
    "EditPlan",
    "FrameRate",
    "MediaDescriptor",
    "PlannedClip",
    "PlannedGap",
    "PlannedMarker",
    "PlannedSegment",
    "PlanningError",
    "PlanningInputs",
    "SegmentInput",
    "VideoAssignment",
    "VideoStatus",
    "create_edit_plan",
    "seconds_to_frame",
    "validate_edit_plan",
]
