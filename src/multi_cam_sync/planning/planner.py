"""Create and validate deterministic edit plans."""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import pairwise

from multi_cam_sync.planning.colors import RESOLVE_COLORS, assign_take_colors
from multi_cam_sync.planning.frame_math import frame_error, seconds_to_frame
from multi_cam_sync.planning.models import (
    EditPlan,
    PlannedClip,
    PlannedGap,
    PlannedMarker,
    PlannedSegment,
    PlanningInputs,
    SegmentInput,
    VideoAssignment,
    VideoStatus,
)


class PlanningError(ValueError):
    """Raised when an edit cannot be planned safely."""


def _require_segments(segments: tuple[SegmentInput, ...]) -> None:
    if not segments:
        raise PlanningError("at least one master segment is required")
    if segments[0].start_seconds != 0:
        raise PlanningError("the first master segment must start at 0")
    seen: set[str] = set()
    for expected_index, segment in enumerate(segments):
        if segment.id in seen:
            raise PlanningError(f"duplicate segment id: {segment.id}")
        seen.add(segment.id)
        if segment.index != expected_index:
            raise PlanningError("segment indices must be contiguous from zero")
        if not segment.display_take.strip() or not segment.take_key:
            raise PlanningError(f"segment {segment.id} has an empty take")
        if segment.end_seconds <= segment.start_seconds:
            raise PlanningError(f"segment {segment.id} has non-positive duration")
        if expected_index and segments[expected_index - 1].end_seconds != segment.start_seconds:
            raise PlanningError("master segments must be contiguous and ordered")


def _assignment_for(inputs: PlanningInputs, segment: SegmentInput) -> VideoAssignment:
    assignment = inputs.assignments.get(segment.id)
    enabled = segment.take_key in inputs.enabled_take_keys
    if not enabled:
        if assignment is not None and assignment.status is not VideoStatus.NOT_PROVIDED:
            raise PlanningError(
                f"segment {segment.id} has video but take {segment.take_key} is not enabled"
            )
        return assignment or VideoAssignment.not_provided()
    if assignment is None:
        raise PlanningError(f"video-enabled segment {segment.id} has no match")
    if assignment.status is VideoStatus.NOT_PROVIDED:
        raise PlanningError(f"video-enabled segment {segment.id} cannot be not_provided")
    if assignment.status is VideoStatus.UNSAFE:
        details = ", ".join(assignment.blockers) or "unknown alignment blocker"
        raise PlanningError(f"video-enabled segment {segment.id} is unsafe: {details}")
    if assignment.media is None or assignment.source_in_seconds is None or not assignment.source_id:
        raise PlanningError(f"matched segment {segment.id} lacks source media or in-point")
    return assignment


def _plan_audio_clip(
    inputs: PlanningInputs,
    segment: SegmentInput,
    record_start: int,
    record_end: int,
    color: str,
) -> PlannedClip:
    master = inputs.master_media
    source_start = seconds_to_frame(segment.start_seconds, master.frame_rate)
    source_end = seconds_to_frame(segment.end_seconds, master.frame_rate)
    total_frames = seconds_to_frame(master.duration_seconds, master.frame_rate)
    if source_end > total_frames:
        raise PlanningError(f"segment {segment.id} exceeds master media duration")
    return PlannedClip(
        id=f"audio-{segment.id}",
        segment_id=segment.id,
        take_key=segment.take_key,
        media_id=master.media_id,
        media_type="audio",
        track_index=1,
        source_start_frame=source_start,
        source_end_frame=source_end,
        record_start_frame=record_start,
        record_end_frame=record_end,
        name=f"{segment.display_take} — segment {segment.index + 1:03d}",
        color=color,
    )


def _plan_video_clip(
    inputs: PlanningInputs,
    segment: SegmentInput,
    assignment: VideoAssignment,
    record_start: int,
    record_end: int,
    color: str,
) -> PlannedClip:
    media = assignment.media
    source_in = assignment.source_in_seconds
    if media is None or source_in is None or assignment.source_id is None:
        raise PlanningError(f"matched segment {segment.id} lacks source values")
    duration = segment.end_seconds - segment.start_seconds
    expected_out = source_in + duration
    source_start = seconds_to_frame(source_in, media.frame_rate)
    record_duration = record_end - record_start
    record_duration_seconds = (
        Decimal(record_duration)
        * Decimal(inputs.timeline_rate.denominator)
        / Decimal(inputs.timeline_rate.numerator)
    )
    source_duration = seconds_to_frame(record_duration_seconds, media.frame_rate)
    source_end = source_start + source_duration
    if source_start < 0 or source_end <= source_start:
        raise PlanningError(f"segment {segment.id} has invalid source frame range")
    if source_end > seconds_to_frame(media.duration_seconds, media.frame_rate):
        raise PlanningError(f"segment {segment.id} exceeds source media duration")
    if assignment.predicted_source_out_seconds is not None:
        drift = assignment.predicted_source_out_seconds - expected_out
        if frame_error(drift, inputs.timeline_rate) > Decimal(2):
            raise PlanningError(f"segment {segment.id} exceeds the two-frame drift tolerance")
    return PlannedClip(
        id=f"video-{segment.id}",
        segment_id=segment.id,
        take_key=segment.take_key,
        media_id=media.media_id,
        media_type="video",
        track_index=1,
        source_start_frame=source_start,
        source_end_frame=source_end,
        record_start_frame=record_start,
        record_end_frame=record_end,
        name=f"{segment.display_take} — segment {segment.index + 1:03d}",
        color=color,
    )


def create_edit_plan(inputs: PlanningInputs) -> EditPlan:
    """Create a complete edit plan without touching Resolve."""
    if not inputs.timeline_name.strip():
        raise PlanningError("timeline name cannot be empty")
    if inputs.timeline_start_frame < 0:
        raise PlanningError("timeline start frame cannot be negative")
    _require_segments(inputs.segments)
    if inputs.segments[-1].end_seconds > inputs.master_media.duration_seconds:
        raise PlanningError("master segments exceed master media duration")

    color_by_take = assign_take_colors([segment.take_key for segment in inputs.segments])
    planned_segments: list[PlannedSegment] = []
    for segment in inputs.segments:
        assignment = _assignment_for(inputs, segment)
        record_start = inputs.timeline_start_frame + seconds_to_frame(
            segment.start_seconds, inputs.timeline_rate
        )
        record_end = inputs.timeline_start_frame + seconds_to_frame(
            segment.end_seconds, inputs.timeline_rate
        )
        if record_end <= record_start:
            raise PlanningError(f"segment {segment.id} rounds to zero timeline frames")
        color = color_by_take[segment.take_key]
        audio_clip = _plan_audio_clip(inputs, segment, record_start, record_end, color)
        if assignment.status is VideoStatus.MATCHED:
            video_clip = _plan_video_clip(
                inputs, segment, assignment, record_start, record_end, color
            )
            gap = None
        else:
            video_clip = None
            gap = PlannedGap(
                id=f"gap-{segment.id}",
                segment_id=segment.id,
                take_key=segment.take_key,
                record_start_frame=record_start,
                record_end_frame=record_end,
            )
        planned_segments.append(
            PlannedSegment(
                segment_id=segment.id,
                index=segment.index,
                display_take=segment.display_take,
                take_key=segment.take_key,
                video_status=assignment.status,
                audio_clip=audio_clip,
                video_clip=video_clip,
                video_gap=gap,
                warnings=assignment.warnings,
            )
        )

    markers: list[PlannedMarker] = []
    for index in range(1, len(planned_segments)):
        outgoing = planned_segments[index - 1]
        incoming = planned_segments[index]
        frame = incoming.audio_clip.record_start_frame
        payload = {
            "id": f"cut-{index:04d}",
            "out_segment": outgoing.segment_id,
            "in_segment": incoming.segment_id,
            "out_video": outgoing.video_status.value,
            "in_video": incoming.video_status.value,
        }
        markers.append(
            PlannedMarker(
                id=payload["id"],
                frame=frame,
                color="Cyan",
                name=f"Cut {index:03d}: {outgoing.display_take} → {incoming.display_take}",
                note=(
                    f"Out: {outgoing.display_take} ({outgoing.video_status.value}) | "
                    f"In: {incoming.display_take} ({incoming.video_status.value})"
                ),
                duration=1,
                custom_data=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            )
        )

    plan = EditPlan(
        timeline_name=inputs.timeline_name.strip(),
        timeline_rate=inputs.timeline_rate,
        timeline_start_frame=inputs.timeline_start_frame,
        segments=tuple(planned_segments),
        markers=tuple(markers),
        color_map=tuple(color_by_take.items()),
        expected_snapshot=inputs.expected_snapshot,
    )
    validate_edit_plan(plan)
    return plan


def validate_edit_plan(plan: EditPlan) -> None:
    """Enforce the invariants Resolve is allowed to assume."""
    if not plan.timeline_name.strip() or not plan.segments:
        raise PlanningError("plan needs a timeline name and at least one segment")
    colors = dict(plan.color_map)
    if len(colors) != len(plan.color_map) or any(
        color not in RESOLVE_COLORS for color in colors.values()
    ):
        raise PlanningError("plan contains an invalid or duplicate color mapping")

    ids: set[str] = set()
    previous_end: int | None = None
    take_policy: dict[str, bool] = {}
    for expected_index, segment in enumerate(plan.segments):
        if segment.index != expected_index:
            raise PlanningError("planned segment indices are not contiguous")
        audio = segment.audio_clip
        for item_id in (segment.segment_id, audio.id):
            if item_id in ids:
                raise PlanningError(f"duplicate plan id: {item_id}")
            ids.add(item_id)
        if audio.media_type != "audio" or audio.track_index != 1:
            raise PlanningError("master clips must be audio-only on track 1")
        if audio.record_end_frame <= audio.record_start_frame:
            raise PlanningError("audio clip has non-positive duration")
        if previous_end is not None and audio.record_start_frame != previous_end:
            raise PlanningError("master audio clips are not contiguous")
        previous_end = audio.record_end_frame
        has_video = segment.video_status is VideoStatus.MATCHED
        existing_policy = take_policy.setdefault(segment.take_key, has_video)
        if existing_policy != has_video:
            raise PlanningError(f"take {segment.take_key} mixes supplied and omitted segments")

        if has_video:
            if segment.video_clip is None or segment.video_gap is not None:
                raise PlanningError("matched segment must have one video clip and no gap")
            video = segment.video_clip
            if video.id in ids:
                raise PlanningError(f"duplicate plan id: {video.id}")
            ids.add(video.id)
            if video.media_type != "video" or video.track_index != 1:
                raise PlanningError("video clips must be video-only on track 1")
            if (video.record_start_frame, video.record_end_frame) != (
                audio.record_start_frame,
                audio.record_end_frame,
            ):
                raise PlanningError("video clip does not cover its exact master segment")
        else:
            if segment.video_status is not VideoStatus.NOT_PROVIDED:
                raise PlanningError("unsafe segments cannot appear in an edit plan")
            if segment.video_clip is not None or segment.video_gap is None:
                raise PlanningError("not_provided segment must have one gap and no video clip")
            gap = segment.video_gap
            if gap.id in ids:
                raise PlanningError(f"duplicate plan id: {gap.id}")
            ids.add(gap.id)
            if (gap.record_start_frame, gap.record_end_frame) != (
                audio.record_start_frame,
                audio.record_end_frame,
            ):
                raise PlanningError("video gap does not cover its exact master segment")

    if len(plan.markers) != len(plan.segments) - 1:
        raise PlanningError("plan must have one marker at each interior boundary")
    for index, marker in enumerate(plan.markers, start=1):
        if marker.id in ids:
            raise PlanningError(f"duplicate plan id: {marker.id}")
        ids.add(marker.id)
        if marker.frame != plan.segments[index].audio_clip.record_start_frame:
            raise PlanningError("marker is not on its planned cut boundary")

    video_clips = sorted(plan.video_clips, key=lambda clip: clip.record_start_frame)
    for left, right in pairwise(video_clips):
        if right.record_start_frame < left.record_end_frame:
            raise PlanningError("video clips overlap")
