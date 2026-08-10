"""Immutable public values shared by configuration, analysis, and planning."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, computed_field, field_validator, model_validator

from multi_cam_sync.time_values import clean_take_name, normalize_take_name, parse_decimal_seconds


def _nonblank(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be text")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must not be blank")
    return stripped


class FrozenModel(BaseModel):
    """Shared strict, immutable model configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, validate_default=True)


class ProjectSettings(FrozenModel):
    timeline_name: str
    cuts_file: Path

    @field_validator("timeline_name")
    @classmethod
    def validate_timeline_name(cls, value: str) -> str:
        return _nonblank(value, "project.timeline_name")


class MasterSpec(FrozenModel):
    media_pool_folder: str
    media_pool_name: str
    audio_path: Path | None = None

    @field_validator("media_pool_folder", "media_pool_name")
    @classmethod
    def validate_selector(cls, value: str, info: Any) -> str:
        return _nonblank(value, f"master.{info.field_name}")


class SourceSpec(FrozenModel):
    id: str
    take: str
    take_key: str = ""
    media_pool_folder: str
    media_pool_name: str
    audio_reference_path: Path | None = None
    source_start: Decimal = Decimal(0)
    source_end: Decimal | None = None
    manual_offset_seconds: Decimal | None = None

    @field_validator("id", "media_pool_folder", "media_pool_name")
    @classmethod
    def validate_nonblank_fields(cls, value: str, info: Any) -> str:
        return _nonblank(value, f"sources.{info.field_name}")

    @field_validator("take")
    @classmethod
    def validate_take(cls, value: str) -> str:
        return clean_take_name(value)

    @field_validator("take_key", mode="before")
    @classmethod
    def derive_take_key(cls, value: object, info: Any) -> str:
        take = info.data.get("take")
        if not isinstance(take, str):
            return ""
        expected = normalize_take_name(take)
        if value in (None, ""):
            return expected
        if value != expected:
            raise ValueError(f"take_key must equal normalized take name {expected!r}")
        return expected

    @field_validator("source_start", "source_end", "manual_offset_seconds", mode="before")
    @classmethod
    def validate_decimal_fields(cls, value: object, info: Any) -> Decimal | None:
        if value is None:
            return None
        if info.field_name == "manual_offset_seconds" and isinstance(value, str):
            raise ValueError("sources.manual_offset_seconds must be a finite numeric TOML value")
        return parse_decimal_seconds(value, field_name=f"sources.{info.field_name}")

    @model_validator(mode="after")
    def validate_bounds(self) -> Self:
        if self.source_start < 0:
            raise ValueError("sources.source_start must be nonnegative")
        if self.source_end is not None:
            if self.source_end < 0:
                raise ValueError("sources.source_end must be nonnegative")
            if self.source_end <= self.source_start:
                raise ValueError("sources.source_end must be greater than sources.source_start")
        return self


class CutTransition(FrozenModel):
    outgoing_take: str
    incoming_take: str
    master_time: Decimal

    @field_validator("outgoing_take", "incoming_take")
    @classmethod
    def validate_take(cls, value: str) -> str:
        return clean_take_name(value)

    @field_validator("master_time", mode="before")
    @classmethod
    def validate_master_time(cls, value: object) -> Decimal:
        result = parse_decimal_seconds(value, field_name="cut master_time")
        if result < 0:
            raise ValueError("cut master_time must be nonnegative")
        return result

    @computed_field
    @property
    def outgoing_take_key(self) -> str:
        return normalize_take_name(self.outgoing_take)

    @computed_field
    @property
    def incoming_take_key(self) -> str:
        return normalize_take_name(self.incoming_take)


class MasterSegment(FrozenModel):
    id: str
    index: int
    display_take: str
    take_key: str = ""
    start_seconds: Decimal
    end_seconds: Decimal | None = None

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        return _nonblank(value, "segment.id")

    @field_validator("display_take")
    @classmethod
    def validate_take(cls, value: str) -> str:
        return clean_take_name(value)

    @field_validator("take_key", mode="before")
    @classmethod
    def derive_take_key(cls, value: object, info: Any) -> str:
        display_take = info.data.get("display_take")
        if not isinstance(display_take, str):
            return ""
        expected = normalize_take_name(display_take)
        if value in (None, ""):
            return expected
        if value != expected:
            raise ValueError(f"take_key must equal normalized display_take {expected!r}")
        return expected

    @field_validator("start_seconds", "end_seconds", mode="before")
    @classmethod
    def validate_seconds(cls, value: object, info: Any) -> Decimal | None:
        if value is None:
            return None
        return parse_decimal_seconds(value, field_name=f"segment.{info.field_name}")

    @model_validator(mode="after")
    def validate_interval(self) -> Self:
        if self.index < 0:
            raise ValueError("segment.index must be nonnegative")
        if self.start_seconds < 0:
            raise ValueError("segment.start_seconds must be nonnegative")
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("segment.end_seconds must be greater than segment.start_seconds")
        return self


class ProjectSpec(FrozenModel):
    schema_version: int
    config_path: Path
    project: ProjectSettings
    master: MasterSpec
    sources: tuple[SourceSpec, ...] = ()

    @model_validator(mode="after")
    def validate_schema_and_ids(self) -> Self:
        if isinstance(self.schema_version, bool) or self.schema_version != 1:
            raise ValueError("schema_version must be integer 1")
        seen: set[str] = set()
        duplicate_ids: list[str] = []
        for source in self.sources:
            if source.id in seen:
                duplicate_ids.append(source.id)
            seen.add(source.id)
        if duplicate_ids:
            duplicates = ", ".join(sorted(set(duplicate_ids)))
            raise ValueError(f"sources.id values must be unique; duplicates: {duplicates}")
        return self

    @computed_field
    @property
    def sources_by_take(self) -> Mapping[str, tuple[SourceSpec, ...]]:
        grouped: dict[str, list[SourceSpec]] = {}
        for source in self.sources:
            grouped.setdefault(source.take_key, []).append(source)
        return {take_key: tuple(candidates) for take_key, candidates in grouped.items()}
