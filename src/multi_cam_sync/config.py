"""Version-1 TOML project configuration loader."""

from __future__ import annotations

import tomllib
from fractions import Fraction
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from multi_cam_sync.cuts import build_master_segments, parse_cut_list
from multi_cam_sync.domain.errors import ConfigError, CutListError, format_validation_errors
from multi_cam_sync.domain.models import (
    MasterSegment,
    MasterSpec,
    ProjectSettings,
    ProjectSpec,
    SourceSpec,
)


def _resolved_path(value: object, *, base: Path, key: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a nonblank filesystem path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve(strict=False)


def _validation_messages(error: ValidationError) -> tuple[str, ...]:
    messages: list[str] = []
    for item in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(part) for part in item["loc"])
        prefix = f"{location}: " if location else ""
        messages.append(f"{prefix}{item['msg']}")
    return tuple(messages)


def _table(value: object, key: str, errors: list[str]) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    errors.append(f"{key} must be a TOML table")
    return {}


def validate_project_segments(spec: ProjectSpec, segments: tuple[MasterSegment, ...]) -> None:
    """Cross-validate configured source controls against parsed master segments."""
    used_take_keys = {segment.take_key for segment in segments}
    unused = [source for source in spec.sources if source.take_key not in used_take_keys]
    cross_errors: list[str] = []
    if unused:
        details = ", ".join(f"{source.id} ({source.take})" for source in unused)
        cross_errors.append(
            f"configured sources must reference takes used by project.cuts_file; unused: {details}"
        )
    segments_by_id = {segment.id: segment for segment in segments}
    for source in spec.sources:
        for search_range in source.segment_search_ranges:
            segment = segments_by_id.get(search_range.segment_id)
            if segment is None:
                cross_errors.append(
                    f"source {source.id!r} segment_search_ranges references unknown segment "
                    f"{search_range.segment_id!r}"
                )
            elif segment.take_key != source.take_key:
                cross_errors.append(
                    f"source {source.id!r} segment_search_ranges references "
                    f"{search_range.segment_id!r} ({segment.display_take}), which does not "
                    f"use source take {source.take!r}"
                )
        for override in source.segment_manual_offsets:
            segment = segments_by_id.get(override.segment_id)
            if segment is None:
                cross_errors.append(
                    f"source {source.id!r} segment_manual_offsets references unknown segment "
                    f"{override.segment_id!r}"
                )
            elif segment.take_key != source.take_key:
                cross_errors.append(
                    f"source {source.id!r} segment_manual_offsets references "
                    f"{override.segment_id!r} ({segment.display_take}), which does not "
                    f"use source take {source.take!r}"
                )
    if cross_errors:
        raise ConfigError(
            format_validation_errors(f"invalid configuration {spec.config_path}", cross_errors)
        )


def load_project_spec(
    path: Path,
    *,
    cut_frame_rate: Fraction | None = None,
    defer_cut_validation: bool = False,
) -> ProjectSpec:
    """Load and cross-validate a project, optionally deferring cuts until Resolve is read."""
    config_path = path.expanduser().resolve(strict=False)
    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
    except OSError as error:
        raise ConfigError(
            f"cannot read configuration {config_path}: {error.strerror or error}"
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {config_path}: {error}") from error

    errors: list[str] = []
    allowed_root = {"schema_version", "project", "master", "sources"}
    for extra in sorted(set(raw) - allowed_root):
        errors.append(f"{extra}: unexpected top-level key")

    schema_version = raw.get("schema_version")
    validated_schema_version = 1
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != 1
    ):
        errors.append("schema_version must be the integer 1")

    project_raw = _table(raw.get("project"), "project", errors)
    master_raw = _table(raw.get("master"), "master", errors)
    source_values = raw.get("sources", [])
    if not isinstance(source_values, list):
        errors.append("sources must be an array of TOML tables")
        source_values = []

    try:
        cuts_file = _resolved_path(
            project_raw.get("cuts_file"), base=config_path.parent, key="project.cuts_file"
        )
    except ConfigError as error:
        errors.append(str(error))
        cuts_file = config_path.parent / "invalid-cuts-file"
    project_data = dict(project_raw)
    project_data["cuts_file"] = cuts_file

    master_data = dict(master_raw)
    if "audio_path" in master_data:
        try:
            master_data["audio_path"] = _resolved_path(
                master_data["audio_path"], base=config_path.parent, key="master.audio_path"
            )
        except ConfigError as error:
            errors.append(str(error))
            master_data.pop("audio_path", None)

    sources: list[SourceSpec] = []
    allowed_source_keys = {
        "id",
        "take",
        "media_pool_folder",
        "media_pool_name",
        "audio_reference_path",
        "additional_audio_reference_paths",
        "source_start",
        "source_end",
        "manual_offset_seconds",
        "segment_search_ranges",
        "segment_manual_offsets",
    }
    for index, source_value in enumerate(source_values):
        if not isinstance(source_value, dict):
            errors.append(f"sources.{index} must be a TOML table")
            continue
        source_data = dict(source_value)
        for extra in sorted(set(source_data) - allowed_source_keys):
            errors.append(f"sources.{index}.{extra}: unexpected key")
            source_data.pop(extra)
        if "audio_reference_path" in source_data:
            try:
                source_data["audio_reference_path"] = _resolved_path(
                    source_data["audio_reference_path"],
                    base=config_path.parent,
                    key=f"sources.{index}.audio_reference_path",
                )
            except ConfigError as error:
                errors.append(str(error))
                source_data.pop("audio_reference_path", None)
        if "additional_audio_reference_paths" in source_data:
            additional_values = source_data["additional_audio_reference_paths"]
            if not isinstance(additional_values, list):
                errors.append(
                    f"sources.{index}.additional_audio_reference_paths must be a TOML array"
                )
                source_data.pop("additional_audio_reference_paths", None)
            else:
                additional_paths: list[Path] = []
                for reference_index, additional_value in enumerate(additional_values):
                    try:
                        additional_paths.append(
                            _resolved_path(
                                additional_value,
                                base=config_path.parent,
                                key=(
                                    f"sources.{index}.additional_audio_reference_paths."
                                    f"{reference_index}"
                                ),
                            )
                        )
                    except ConfigError as error:
                        errors.append(str(error))
                source_data["additional_audio_reference_paths"] = tuple(additional_paths)
        try:
            sources.append(SourceSpec.model_validate(source_data))
        except ValidationError as error:
            errors.extend(f"sources.{index}.{message}" for message in _validation_messages(error))

    project: ProjectSettings | None = None
    master: MasterSpec | None = None
    try:
        project = ProjectSettings.model_validate(project_data)
    except ValidationError as error:
        errors.extend(f"project.{message}" for message in _validation_messages(error))
    try:
        master = MasterSpec.model_validate(master_data)
    except ValidationError as error:
        errors.extend(f"master.{message}" for message in _validation_messages(error))

    if errors or project is None or master is None:
        raise ConfigError(format_validation_errors(f"invalid configuration {config_path}", errors))

    try:
        spec = ProjectSpec(
            schema_version=validated_schema_version,
            config_path=config_path,
            project=project,
            master=master,
            sources=tuple(sources),
        )
    except ValidationError as error:
        raise ConfigError(
            format_validation_errors(
                f"invalid configuration {config_path}", _validation_messages(error)
            )
        ) from error

    if defer_cut_validation:
        return spec

    try:
        cut_text = spec.project.cuts_file.read_text(encoding="utf-8-sig")
    except OSError as error:
        raise ConfigError(
            f"cannot read project.cuts_file {spec.project.cuts_file}: {error.strerror or error}"
        ) from error
    try:
        segments = build_master_segments(parse_cut_list(cut_text, frame_rate=cut_frame_rate))
    except CutListError as error:
        raise ConfigError(f"project.cuts_file {spec.project.cuts_file}: {error}") from error
    validate_project_segments(spec, segments)
    return spec
