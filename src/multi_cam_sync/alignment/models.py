"""Public alignment requests, results, diagnostics, and confidence policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Any

from multi_cam_sync.media import AnalysisAudio


class AlignmentError(RuntimeError):
    """Base class for alignment contract and processing errors."""


class EmptyCandidatesError(AlignmentError):
    """The matcher was invoked for a take without supplied video."""


class MatchStatus(StrEnum):
    MATCHED = "matched"
    UNSAFE = "unsafe"


class MatchMethod(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    NONE = "none"


class BlockerCode(StrEnum):
    NO_VALID_CANDIDATE = "no_valid_candidate"
    INVALID_AUDIO = "invalid_audio"
    TOO_SHORT = "too_short"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    OUT_OF_BOUNDS = "out_of_bounds"
    NON_MONOTONIC_MAPPING = "non_monotonic_mapping"
    EXCESS_DRIFT = "excess_drift"
    UNSTABLE_EDGES = "unstable_edges"
    EXCESS_OUTLIERS = "excess_outliers"
    AMBIGUOUS_RUNNER_UP = "ambiguous_runner_up"
    DTW_FAILED = "dtw_failed"
    INVALID_MANUAL_OFFSET = "invalid_manual_offset"


@dataclass(frozen=True, slots=True)
class AlignmentSettings:
    """Fixed, serializable analysis and confidence settings."""

    sample_rate: int = 22_050
    n_mfcc: int = 80
    n_mels: int = 128
    n_fft: int = 2_048
    hop_length: int = 256
    distance: str = "cosine"
    step_pattern: str = "asymmetric"
    open_begin: bool = True
    open_end: bool = True
    delta_orders: tuple[int, int] = (1, 2)
    delta_width: int = 9
    zscore_epsilon: float = 1e-8
    edge_guard_seconds: Decimal = Decimal("0.150")
    edge_guard_fraction: Decimal = Decimal("0.10")
    minimum_coverage: float = 0.95
    ambiguity_fraction: float = 0.05
    maximum_outlier_fraction: float = 0.25
    maximum_error_frames: int = 2
    timeline_frame_rate: Fraction = Fraction(24, 1)
    robust_fit_iterations: int = 5
    robust_mad_scale: float = 3.5

    def __post_init__(self) -> None:
        if self.sample_rate <= 0 or self.n_mfcc <= 0 or self.hop_length <= 0:
            raise ValueError("analysis sizes must be positive")
        if self.delta_width < 3 or self.delta_width % 2 == 0:
            raise ValueError("delta_width must be odd and at least 3")
        if not 0 < self.minimum_coverage <= 1:
            raise ValueError("minimum_coverage must be in (0, 1]")
        if self.timeline_frame_rate <= 0:
            raise ValueError("timeline_frame_rate must be positive")

    @property
    def maximum_error_seconds(self) -> Decimal:
        return Decimal(self.maximum_error_frames * self.timeline_frame_rate.denominator) / Decimal(
            self.timeline_frame_rate.numerator
        )

    def as_dict(self) -> dict[str, Any]:
        """Stable report representation; included in every result."""
        return {
            "sample_rate": self.sample_rate,
            "n_mfcc": self.n_mfcc,
            "n_mels": self.n_mels,
            "n_fft": self.n_fft,
            "hop_length": self.hop_length,
            "distance": self.distance,
            "step_pattern": self.step_pattern,
            "open_begin": self.open_begin,
            "open_end": self.open_end,
            "delta_orders": list(self.delta_orders),
            "delta_width": self.delta_width,
            "zscore_epsilon": self.zscore_epsilon,
            "edge_guard_seconds": str(self.edge_guard_seconds),
            "edge_guard_fraction": str(self.edge_guard_fraction),
            "minimum_coverage": self.minimum_coverage,
            "ambiguity_fraction": self.ambiguity_fraction,
            "maximum_outlier_fraction": self.maximum_outlier_fraction,
            "maximum_error_frames": self.maximum_error_frames,
            "timeline_frame_rate": (
                f"{self.timeline_frame_rate.numerator}/{self.timeline_frame_rate.denominator}"
            ),
            "robust_fit_iterations": self.robust_fit_iterations,
            "robust_mad_scale": self.robust_mad_scale,
        }


@dataclass(frozen=True, slots=True)
class SegmentRequest:
    """One exact master interval whose take has configured source candidates."""

    segment_id: str
    take: str
    master_start_seconds: Decimal
    master_end_seconds: Decimal

    def __post_init__(self) -> None:
        if not self.segment_id or not self.take:
            raise ValueError("segment_id and take are required")
        if self.master_start_seconds < 0 or self.master_end_seconds <= self.master_start_seconds:
            raise ValueError("segment master bounds must be positive and increasing")

    @property
    def duration_seconds(self) -> Decimal:
        return self.master_end_seconds - self.master_start_seconds


@dataclass(frozen=True, slots=True)
class AlignmentCandidate:
    """One explicitly eligible, physically bounded camera-audio occurrence."""

    source_id: str
    audio: AnalysisAudio
    source_start_seconds: Decimal | None = None
    source_end_seconds: Decimal | None = None
    manual_offset_seconds: Decimal | None = None

    def __post_init__(self) -> None:
        start = self.start_seconds
        end = self.end_seconds
        if not self.source_id:
            raise ValueError("source_id is required")
        if start < self.audio.origin_seconds or end > self.audio.end_seconds or end <= start:
            raise ValueError("candidate bounds must fit its decoded AnalysisAudio")

    @property
    def start_seconds(self) -> Decimal:
        return (
            self.source_start_seconds
            if self.source_start_seconds is not None
            else self.audio.origin_seconds
        )

    @property
    def end_seconds(self) -> Decimal:
        return (
            self.source_end_seconds
            if self.source_end_seconds is not None
            else self.audio.end_seconds
        )


@dataclass(frozen=True, slots=True)
class MatchDiagnostics:
    """Serializable evidence for a candidate or final segment decision."""

    settings: dict[str, Any]
    normalized_cost: float | None = None
    coverage: float | None = None
    path_master_start_seconds: Decimal | None = None
    path_master_end_seconds: Decimal | None = None
    path_source_start_seconds: Decimal | None = None
    path_source_end_seconds: Decimal | None = None
    fitted_slope: float | None = None
    fitted_intercept_seconds: Decimal | None = None
    mapped_source_end_seconds: Decimal | None = None
    predicted_drift_seconds: Decimal | None = None
    outlier_fraction: float | None = None
    edge_stability_seconds: Decimal | None = None
    runner_up_cost: float | None = None
    runner_up_margin_fraction: float | None = None
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    source_id: str
    method: MatchMethod
    source_in_seconds: Decimal | None
    source_out_seconds: Decimal | None
    diagnostics: MatchDiagnostics
    blockers: tuple[BlockerCode, ...] = ()
    warnings: tuple[str, ...] = ()

    @property
    def safe(self) -> bool:
        return (
            not self.blockers
            and self.source_in_seconds is not None
            and self.source_out_seconds is not None
        )


@dataclass(frozen=True, slots=True)
class SegmentMatch:
    """Planner-ready result; no raw librosa or dtw-python objects escape."""

    segment_id: str
    take: str
    status: MatchStatus
    method: MatchMethod
    source_id: str | None
    source_in_seconds: Decimal | None
    source_out_seconds: Decimal | None
    diagnostics: MatchDiagnostics
    candidates: tuple[CandidateMatch, ...] = ()
    blockers: tuple[BlockerCode, ...] = ()
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def safe_for_planning(self) -> bool:
        return self.status is MatchStatus.MATCHED and not self.blockers
