"""Deterministic, atomic JSON representation of reports."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, cast

from multi_cam_sync.media import ContentFingerprint
from multi_cam_sync.planning import (
    EditPlan,
    FrameRate,
    PlannedClip,
    PlannedGap,
    PlannedMarker,
    PlannedSegment,
    VideoStatus,
)
from multi_cam_sync.reporting.models import (
    REPORT_SCHEMA_VERSION,
    AlignmentReport,
    InputFileRecord,
    ReportError,
    SegmentReport,
)
from multi_cam_sync.resolve import MediaSelector, ResolvedMediaItem, ResolveProjectSnapshot


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if value != value or value in {float("inf"), float("-inf")}:
            raise ReportError("reports cannot contain NaN or Infinity")
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Fraction):
        return f"{value.numerator}/{value.denominator}"
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(cast("Any", value)))
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    raise ReportError(f"unsupported report value: {type(value).__name__}")


def _selector_dict(selector: MediaSelector) -> dict[str, object]:
    return {"folder": list(selector.folder), "name": selector.name, "kind": selector.kind}


def _media_dict(item: ResolvedMediaItem) -> dict[str, object]:
    return {
        "media_id": item.media_id,
        "selector": _selector_dict(item.selector),
        "name": item.name,
        "file_path": str(item.file_path) if item.file_path is not None else None,
        "duration_frames": item.duration_frames,
        "frame_rate": str(item.frame_rate),
        "raw_properties": dict(sorted(item.raw_properties.items())),
    }


def _snapshot_dict(snapshot: ResolveProjectSnapshot) -> dict[str, object]:
    return {
        "project_id": snapshot.project_id,
        "project_name": snapshot.project_name,
        "timeline_frame_rate": str(snapshot.timeline_frame_rate),
        "timeline_start_frame": snapshot.timeline_start_frame,
        "timeline_start_timecode": snapshot.timeline_start_timecode,
        "timeline_names": list(snapshot.timeline_names),
        "media": [_media_dict(item) for item in snapshot.media],
    }


def _clip_dict(clip: PlannedClip) -> dict[str, object]:
    return {
        "id": clip.id,
        "segment_id": clip.segment_id,
        "take_key": clip.take_key,
        "media_id": clip.media_id,
        "media_type": clip.media_type,
        "track_index": clip.track_index,
        "source_start_frame": clip.source_start_frame,
        "source_end_frame": clip.source_end_frame,
        "record_start_frame": clip.record_start_frame,
        "record_end_frame": clip.record_end_frame,
        "name": clip.name,
        "color": clip.color,
    }


def _gap_dict(gap: PlannedGap) -> dict[str, object]:
    return {
        "id": gap.id,
        "segment_id": gap.segment_id,
        "take_key": gap.take_key,
        "record_start_frame": gap.record_start_frame,
        "record_end_frame": gap.record_end_frame,
    }


def _marker_dict(marker: PlannedMarker) -> dict[str, object]:
    return {
        "id": marker.id,
        "frame": marker.frame,
        "color": marker.color,
        "name": marker.name,
        "note": marker.note,
        "duration": marker.duration,
        "custom_data": marker.custom_data,
    }


def _plan_dict(plan: EditPlan) -> dict[str, object]:
    return {
        "timeline_name": plan.timeline_name,
        "timeline_rate": str(plan.timeline_rate),
        "timeline_start_frame": plan.timeline_start_frame,
        "segments": [
            {
                "segment_id": segment.segment_id,
                "index": segment.index,
                "display_take": segment.display_take,
                "take_key": segment.take_key,
                "video_status": segment.video_status.value,
                "audio_clip": _clip_dict(segment.audio_clip),
                "video_clip": _clip_dict(segment.video_clip) if segment.video_clip else None,
                "video_gap": _gap_dict(segment.video_gap) if segment.video_gap else None,
                "warnings": list(segment.warnings),
            }
            for segment in plan.segments
        ],
        "markers": [_marker_dict(marker) for marker in plan.markers],
        "color_map": [list(pair) for pair in plan.color_map],
    }


def report_to_dict(report: AlignmentReport) -> dict[str, object]:
    """Return the complete stable JSON object for a report."""
    return {
        "report_schema_version": report.report_schema_version,
        "tool_version": report.tool_version,
        "created_at_utc": report.created_at_utc,
        "run_id": report.run_id,
        "config_path": report.config_path,
        "configuration_hash": report.configuration_hash,
        "cuts_hash": report.cuts_hash,
        "alignment_settings": _jsonable(report.alignment_settings),
        "project_snapshot": _snapshot_dict(report.project_snapshot),
        "input_files": [
            {
                "role": item.role,
                "source_id": item.source_id,
                "fingerprint": item.fingerprint.as_dict(),
            }
            for item in report.input_files
        ],
        "segments": [
            {
                "segment_id": segment.segment_id,
                "index": segment.index,
                "take": segment.take,
                "take_key": segment.take_key,
                "master_start_seconds": str(segment.master_start_seconds),
                "master_end_seconds": str(segment.master_end_seconds),
                "video_status": segment.video_status.value,
                "source_id": segment.source_id,
                "source_in_seconds": (
                    str(segment.source_in_seconds)
                    if segment.source_in_seconds is not None
                    else None
                ),
                "source_out_seconds": (
                    str(segment.source_out_seconds)
                    if segment.source_out_seconds is not None
                    else None
                ),
                "suggested_manual_offset_seconds": (
                    str(segment.suggested_manual_offset_seconds)
                    if segment.suggested_manual_offset_seconds is not None
                    else None
                ),
                "method": segment.method,
                "blockers": list(segment.blockers),
                "warnings": list(segment.warnings),
                "diagnostics": _jsonable(segment.diagnostics),
                "candidates": _jsonable(segment.candidates),
            }
            for segment in report.segments
        ],
        "plan": _plan_dict(report.plan) if report.plan is not None else None,
    }


def canonical_payload(report: AlignmentReport) -> dict[str, object]:
    """Return deterministic semantic content without volatile audit fields."""
    payload = report_to_dict(report)
    payload.pop("created_at_utc", None)
    payload.pop("run_id", None)
    return payload


def write_report(path: Path, report: AlignmentReport) -> None:
    """Atomically write a report with stable formatting and a final newline."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            json.dumps(
                report_to_dict(report),
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                with __import__("contextlib").suppress(OSError):
                    os.fsync(stream.fileno())
            os.replace(temporary, path)
            temporary = None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError) as error:
        raise ReportError(f"cannot write report {path}: {error}") from error


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ReportError(f"{name} must be an object")
    return cast("Mapping[str, object]", value)


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise ReportError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ReportError(f"{name} must be non-empty text")
    return value


def _optional_text(value: object, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _integer(value: object, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ReportError(f"{name} must be an integer")
    return value


def _decimal(value: object, name: str) -> Decimal:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        raise ReportError(f"{name} must be a decimal string")
    try:
        result = Decimal(str(value))
    except InvalidOperation as error:
        raise ReportError(f"{name} must be finite decimal text") from error
    if not result.is_finite():
        raise ReportError(f"{name} must be finite")
    return result


def _optional_decimal(value: object, name: str) -> Decimal | None:
    return None if value is None else _decimal(value, name)


def _reject_json_constant(value: str) -> object:
    raise ReportError(f"invalid JSON numeric constant {value!r}")


def _selector(value: object) -> MediaSelector:
    raw = _mapping(value, "selector")
    folder = tuple(
        _text(item, "selector.folder item") for item in _list(raw.get("folder"), "selector.folder")
    )
    return MediaSelector(
        folder=folder,
        name=_text(raw.get("name"), "selector.name"),
        kind=_text(raw.get("kind"), "selector.kind"),
    )


def _snapshot(value: object) -> ResolveProjectSnapshot:
    raw = _mapping(value, "project_snapshot")
    media: list[ResolvedMediaItem] = []
    for index, item_value in enumerate(_list(raw.get("media"), "project_snapshot.media")):
        item = _mapping(item_value, f"project_snapshot.media[{index}]")
        properties = _mapping(item.get("raw_properties", {}), "raw_properties")
        media.append(
            ResolvedMediaItem(
                media_id=_text(item.get("media_id"), "media_id"),
                selector=_selector(item.get("selector")),
                name=_text(item.get("name"), "media.name"),
                file_path=(
                    Path(str(item["file_path"])) if item.get("file_path") is not None else None
                ),
                duration_frames=_integer(item.get("duration_frames"), "duration_frames"),
                frame_rate=_decimal(item.get("frame_rate"), "media.frame_rate"),
                raw_properties={str(key): str(entry) for key, entry in properties.items()},
            )
        )
    start_value = raw.get("timeline_start_frame")
    return ResolveProjectSnapshot(
        project_id=_text(raw.get("project_id"), "project_id"),
        project_name=_text(raw.get("project_name"), "project_name"),
        timeline_frame_rate=_decimal(raw.get("timeline_frame_rate"), "timeline_frame_rate"),
        timeline_start_frame=None
        if start_value is None
        else _integer(start_value, "timeline_start_frame"),
        timeline_start_timecode=_text(
            raw.get("timeline_start_timecode"), "timeline_start_timecode"
        ),
        timeline_names=tuple(
            _text(item, "timeline name")
            for item in _list(raw.get("timeline_names"), "timeline_names")
        ),
        media=tuple(media),
    )


def _clip(value: object) -> PlannedClip:
    raw = _mapping(value, "planned clip")
    return PlannedClip(
        id=_text(raw.get("id"), "clip.id"),
        segment_id=_text(raw.get("segment_id"), "clip.segment_id"),
        take_key=_text(raw.get("take_key"), "clip.take_key"),
        media_id=_text(raw.get("media_id"), "clip.media_id"),
        media_type=_text(raw.get("media_type"), "clip.media_type"),
        track_index=_integer(raw.get("track_index"), "clip.track_index"),
        source_start_frame=_integer(raw.get("source_start_frame"), "clip.source_start_frame"),
        source_end_frame=_integer(raw.get("source_end_frame"), "clip.source_end_frame"),
        record_start_frame=_integer(raw.get("record_start_frame"), "clip.record_start_frame"),
        record_end_frame=_integer(raw.get("record_end_frame"), "clip.record_end_frame"),
        name=_text(raw.get("name"), "clip.name"),
        color=_text(raw.get("color"), "clip.color"),
    )


def _gap(value: object) -> PlannedGap:
    raw = _mapping(value, "planned gap")
    return PlannedGap(
        id=_text(raw.get("id"), "gap.id"),
        segment_id=_text(raw.get("segment_id"), "gap.segment_id"),
        take_key=_text(raw.get("take_key"), "gap.take_key"),
        record_start_frame=_integer(raw.get("record_start_frame"), "gap.record_start_frame"),
        record_end_frame=_integer(raw.get("record_end_frame"), "gap.record_end_frame"),
    )


def _marker(value: object) -> PlannedMarker:
    raw = _mapping(value, "planned marker")
    return PlannedMarker(
        id=_text(raw.get("id"), "marker.id"),
        frame=_integer(raw.get("frame"), "marker.frame"),
        color=_text(raw.get("color"), "marker.color"),
        name=_text(raw.get("name"), "marker.name"),
        note=str(raw.get("note", "")),
        duration=_integer(raw.get("duration"), "marker.duration"),
        custom_data=str(raw.get("custom_data", "")),
    )


def _plan(value: object, snapshot: ResolveProjectSnapshot) -> EditPlan:
    raw = _mapping(value, "plan")
    segments: list[PlannedSegment] = []
    for item_value in _list(raw.get("segments"), "plan.segments"):
        item = _mapping(item_value, "planned segment")
        video_value = item.get("video_clip")
        gap_value = item.get("video_gap")
        segments.append(
            PlannedSegment(
                segment_id=_text(item.get("segment_id"), "segment_id"),
                index=_integer(item.get("index"), "segment.index"),
                display_take=_text(item.get("display_take"), "segment.display_take"),
                take_key=_text(item.get("take_key"), "segment.take_key"),
                video_status=VideoStatus(_text(item.get("video_status"), "segment.video_status")),
                audio_clip=_clip(item.get("audio_clip")),
                video_clip=None if video_value is None else _clip(video_value),
                video_gap=None if gap_value is None else _gap(gap_value),
                warnings=tuple(str(entry) for entry in _list(item.get("warnings", []), "warnings")),
            )
        )
    color_pairs: list[tuple[str, str]] = []
    for index, value_pair in enumerate(_list(raw.get("color_map"), "plan.color_map")):
        pair = _list(value_pair, f"plan.color_map[{index}]")
        if len(pair) != 2:
            raise ReportError(f"plan.color_map[{index}] must contain exactly two strings")
        color_pairs.append((_text(pair[0], "color take"), _text(pair[1], "color")))
    plan = EditPlan(
        timeline_name=_text(raw.get("timeline_name"), "plan.timeline_name"),
        timeline_rate=FrameRate.parse(_text(raw.get("timeline_rate"), "plan.timeline_rate")),
        timeline_start_frame=_integer(raw.get("timeline_start_frame"), "plan.timeline_start_frame"),
        segments=tuple(segments),
        markers=tuple(_marker(item) for item in _list(raw.get("markers"), "plan.markers")),
        color_map=tuple(color_pairs),
        expected_snapshot=snapshot,
    )
    plan.validate()
    return plan


def report_from_dict(value: object) -> AlignmentReport:
    raw = _mapping(value, "report")
    schema = _integer(raw.get("report_schema_version"), "report_schema_version")
    if schema != REPORT_SCHEMA_VERSION:
        raise ReportError(
            f"unsupported report_schema_version {schema}; expected {REPORT_SCHEMA_VERSION}"
        )
    snapshot = _snapshot(raw.get("project_snapshot"))
    files: list[InputFileRecord] = []
    for item_value in _list(raw.get("input_files"), "input_files"):
        item = _mapping(item_value, "input file")
        fingerprint = _mapping(item.get("fingerprint"), "input fingerprint")
        files.append(
            InputFileRecord(
                role=_text(item.get("role"), "input role"),
                source_id=_optional_text(item.get("source_id"), "input source_id"),
                fingerprint=ContentFingerprint(
                    canonical_path=_text(fingerprint.get("canonical_path"), "canonical_path"),
                    size_bytes=_integer(fingerprint.get("size_bytes"), "size_bytes"),
                    modified_ns=_integer(fingerprint.get("modified_ns"), "modified_ns"),
                    sampled_sha256=_text(fingerprint.get("sampled_sha256"), "sampled_sha256"),
                ),
            )
        )
    segments: list[SegmentReport] = []
    for item_value in _list(raw.get("segments"), "segments"):
        item = _mapping(item_value, "segment report")
        diagnostics_value = item.get("diagnostics")
        candidate_values = _list(item.get("candidates", []), "segment.candidates")
        segments.append(
            SegmentReport(
                segment_id=_text(item.get("segment_id"), "segment_id"),
                index=_integer(item.get("index"), "segment.index"),
                take=_text(item.get("take"), "segment.take"),
                take_key=_text(item.get("take_key"), "segment.take_key"),
                master_start_seconds=_decimal(item.get("master_start_seconds"), "master_start"),
                master_end_seconds=_decimal(item.get("master_end_seconds"), "master_end"),
                video_status=VideoStatus(_text(item.get("video_status"), "video_status")),
                source_id=_optional_text(item.get("source_id"), "source_id"),
                source_in_seconds=_optional_decimal(item.get("source_in_seconds"), "source_in"),
                source_out_seconds=_optional_decimal(item.get("source_out_seconds"), "source_out"),
                suggested_manual_offset_seconds=_optional_decimal(
                    item.get("suggested_manual_offset_seconds"),
                    "suggested_manual_offset_seconds",
                ),
                method=_optional_text(item.get("method"), "method"),
                blockers=tuple(str(entry) for entry in _list(item.get("blockers", []), "blockers")),
                warnings=tuple(str(entry) for entry in _list(item.get("warnings", []), "warnings")),
                diagnostics=None
                if diagnostics_value is None
                else _mapping(diagnostics_value, "diagnostics"),
                candidates=tuple(_mapping(entry, "candidate") for entry in candidate_values),
            )
        )
    plan_value = raw.get("plan")
    settings = _mapping(raw.get("alignment_settings"), "alignment_settings")
    return AlignmentReport(
        report_schema_version=schema,
        tool_version=_text(raw.get("tool_version"), "tool_version"),
        created_at_utc=_text(raw.get("created_at_utc"), "created_at_utc"),
        run_id=_text(raw.get("run_id"), "run_id"),
        config_path=_text(raw.get("config_path"), "config_path"),
        configuration_hash=_text(raw.get("configuration_hash"), "configuration_hash"),
        cuts_hash=_text(raw.get("cuts_hash"), "cuts_hash"),
        alignment_settings=settings,
        project_snapshot=snapshot,
        input_files=tuple(files),
        segments=tuple(segments),
        plan=None if plan_value is None else _plan(plan_value, snapshot),
    )


def read_report(path: Path) -> AlignmentReport:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant)
    except OSError as error:
        raise ReportError(f"cannot read report {path}: {error}") from error
    except json.JSONDecodeError as error:
        raise ReportError(f"invalid JSON report {path}: {error}") from error
    try:
        return report_from_dict(value)
    except (ReportError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, ReportError):
            raise
        raise ReportError(f"invalid report {path}: {error}") from error
