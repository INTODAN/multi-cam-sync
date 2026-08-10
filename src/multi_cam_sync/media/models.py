"""Typed media-analysis boundaries and project-owned errors."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Protocol

import numpy as np
from numpy.typing import NDArray


class MediaError(RuntimeError):
    """Base class for actionable media failures."""

    def __init__(self, message: str, *, path: Path) -> None:
        self.path = path
        super().__init__(f"{message}: {path}")


class MediaExecutableNotFoundError(MediaError):
    """A required ffmpeg-family executable is not installed."""


class MediaProbeError(MediaError):
    """ffprobe failed or returned unsupported metadata."""


class NoAudioStreamError(MediaProbeError):
    """A media item has no usable audio stream."""


class InvalidMediaBoundsError(MediaError):
    """Requested source bounds do not fit the physical media."""


class MediaDecodeError(MediaError):
    """Audio could not be decoded into valid analysis samples."""


@dataclass(frozen=True, slots=True)
class MediaStream:
    """Relevant, losslessly parsed ffprobe stream metadata."""

    index: int
    codec_type: str
    codec_name: str | None = None
    duration_seconds: Decimal | None = None
    sample_rate: int | None = None
    channels: int | None = None
    average_frame_rate: Fraction | None = None
    real_frame_rate: Fraction | None = None


@dataclass(frozen=True, slots=True)
class MediaProbe:
    """Metadata needed to validate an analysis request."""

    path: Path
    duration_seconds: Decimal
    streams: tuple[MediaStream, ...]
    audio_stream_index: int | None
    video_frame_rate: Fraction | None

    @property
    def audio_streams(self) -> tuple[MediaStream, ...]:
        """Return audio streams in ffmpeg's audio-stream ordinal order."""
        return tuple(stream for stream in self.streams if stream.codec_type == "audio")


@dataclass(frozen=True, slots=True)
class ContentFingerprint:
    """Fast fingerprint that invalidates on path, stat, or sampled content changes."""

    canonical_path: str
    size_bytes: int
    modified_ns: int
    sampled_sha256: str

    def as_dict(self) -> dict[str, int | str]:
        """Return the stable public representation used in reports and cache keys."""
        return {
            "canonical_path": self.canonical_path,
            "size_bytes": self.size_bytes,
            "modified_ns": self.modified_ns,
            "sampled_sha256": self.sampled_sha256,
        }


@dataclass(frozen=True, slots=True)
class AudioRequest:
    """A bounded mono analysis decode request."""

    path: Path
    audio_stream_index: int = 0
    source_start_seconds: Decimal = Decimal(0)
    source_end_seconds: Decimal | None = None
    sample_rate: int = 22_050
    channels: int = 1

    def __post_init__(self) -> None:
        if self.audio_stream_index < 0:
            raise InvalidMediaBoundsError("audio stream index must be non-negative", path=self.path)
        if self.source_start_seconds < 0:
            raise InvalidMediaBoundsError("source start must be non-negative", path=self.path)
        if (
            self.source_end_seconds is not None
            and self.source_end_seconds <= self.source_start_seconds
        ):
            raise InvalidMediaBoundsError(
                "source end must be greater than source start", path=self.path
            )
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.channels != 1:
            raise ValueError("analysis audio must be mono (channels=1)")


@dataclass(frozen=True, slots=True)
class AnalysisAudio:
    """Contiguous mono samples whose origin is absolute within the physical file."""

    samples: NDArray[np.float32]
    sample_rate: int
    origin_seconds: Decimal
    fingerprint: ContentFingerprint

    def __post_init__(self) -> None:
        if self.sample_rate <= 0:
            raise ValueError("sample_rate must be positive")
        if self.origin_seconds < 0:
            raise ValueError("origin_seconds must be non-negative")
        if self.samples.dtype != np.float32:
            raise ValueError("analysis samples must have dtype float32")
        if self.samples.ndim != 1 or not self.samples.flags.c_contiguous:
            raise ValueError("analysis samples must be one-dimensional and contiguous")
        if self.samples.size == 0:
            raise ValueError("analysis samples must not be empty")
        if not np.isfinite(self.samples).all():
            raise ValueError("analysis samples must all be finite")

    @property
    def duration_seconds(self) -> Decimal:
        return Decimal(self.samples.size) / Decimal(self.sample_rate)

    @property
    def end_seconds(self) -> Decimal:
        return self.origin_seconds + self.duration_seconds


class MediaReader(Protocol):
    """Media operations consumed by orchestration and alignment."""

    def probe(self, path: Path) -> MediaProbe: ...

    def load_audio(self, request: AudioRequest) -> AnalysisAudio: ...
