"""Candidate evaluation, robust time mapping, and confidence decisions."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace
from decimal import Decimal

import numpy as np
from numpy.typing import NDArray

from multi_cam_sync.media import AnalysisAudio

from .dtw import DtwError, DtwPath, align_feature_sequences
from .features import FeatureError, FeatureSequence, extract_features
from .models import (
    AlignmentCandidate,
    AlignmentSettings,
    BlockerCode,
    CandidateMatch,
    EmptyCandidatesError,
    MatchDiagnostics,
    MatchMethod,
    MatchStatus,
    SegmentMatch,
    SegmentRequest,
)

FeatureExtractor = Callable[[NDArray[np.float32], int, AlignmentSettings], FeatureSequence]
PathAligner = Callable[[NDArray[np.float32], NDArray[np.float32], AlignmentSettings], DtwPath]


def _decimal(value: float) -> Decimal:
    return Decimal(str(float(value)))


def _ordered_unique(values: Sequence[BlockerCode]) -> tuple[BlockerCode, ...]:
    return tuple(dict.fromkeys(values))


def _slice_absolute(audio: AnalysisAudio, start: Decimal, end: Decimal) -> NDArray[np.float32]:
    local_start = start - audio.origin_seconds
    local_end = end - audio.origin_seconds
    if local_start < 0 or local_end > audio.duration_seconds:
        raise FeatureError("requested interval lies outside decoded analysis audio")
    start_index = int(local_start * audio.sample_rate)
    end_index = int(local_end * audio.sample_rate)
    if end_index <= start_index:
        raise FeatureError("requested interval has no analysis samples")
    return np.ascontiguousarray(audio.samples[start_index:end_index])


def _robust_affine(
    master_seconds: NDArray[np.float64],
    source_seconds: NDArray[np.float64],
    settings: AlignmentSettings,
) -> tuple[float, float, float]:
    if master_seconds.size < 2 or np.ptp(master_seconds) <= 0:
        raise ValueError("warping path has no usable master-time span")
    mask = np.ones(master_seconds.size, dtype=np.bool_)
    for _ in range(settings.robust_fit_iterations):
        if np.count_nonzero(mask) < 2:
            raise ValueError("too few inlier warping-path points")
        slope, intercept = np.polyfit(master_seconds[mask], source_seconds[mask], 1)
        residuals = source_seconds - (slope * master_seconds + intercept)
        center = np.median(residuals[mask])
        mad = np.median(np.abs(residuals[mask] - center))
        if mad <= np.finfo(np.float64).eps:
            break
        threshold = settings.robust_mad_scale * 1.4826 * mad
        next_mask = np.abs(residuals - center) <= threshold
        if np.array_equal(next_mask, mask):
            break
        mask = next_mask
    slope, intercept = np.polyfit(master_seconds[mask], source_seconds[mask], 1)
    return float(slope), float(intercept), 1.0 - float(np.count_nonzero(mask) / mask.size)


def _feature_blocker(error: FeatureError) -> BlockerCode:
    message = str(error)
    if (
        "feature frames" in message
        or "guard leaves" in message
        or "has no analysis samples" in message
    ):
        return BlockerCode.TOO_SHORT
    return BlockerCode.INVALID_AUDIO


class SegmentMatcher:
    """Match one video-enabled master segment against explicit occurrences only."""

    def __init__(
        self,
        *,
        feature_extractor: FeatureExtractor = extract_features,
        path_aligner: PathAligner = align_feature_sequences,
    ) -> None:
        self._extract_features = feature_extractor
        self._align_path = path_aligner

    def match(
        self,
        segment: SegmentRequest,
        master_audio: AnalysisAudio,
        candidates: Sequence[AlignmentCandidate],
        settings: AlignmentSettings | None = None,
    ) -> SegmentMatch:
        """Return a safe match or detailed unsafe result; reject accidental bypass calls."""
        active_settings = settings or AlignmentSettings()
        if not candidates:
            raise EmptyCandidatesError(
                "audio-only takes must bypass SegmentMatcher instead of passing "
                "an empty candidate list"
            )

        manual = sorted(
            (candidate for candidate in candidates if candidate.manual_offset_seconds is not None),
            key=lambda candidate: candidate.source_id,
        )
        automatic = sorted(
            (candidate for candidate in candidates if candidate.manual_offset_seconds is None),
            key=lambda candidate: candidate.source_id,
        )
        evaluated = [
            self._evaluate_manual(segment, candidate, active_settings) for candidate in manual
        ]
        evaluated.extend(
            self._evaluate_automatic(segment, master_audio, candidate, active_settings)
            for candidate in automatic
        )

        safe_manual = [
            candidate
            for candidate in evaluated
            if candidate.safe and candidate.method is MatchMethod.MANUAL
        ]
        if safe_manual:
            winner = safe_manual[0]
            blockers: tuple[BlockerCode, ...] = ()
            if len(safe_manual) > 1:
                blockers = (BlockerCode.AMBIGUOUS_RUNNER_UP,)
            return self._finish(segment, winner, evaluated, blockers)

        safe_automatic = sorted(
            (
                candidate
                for candidate in evaluated
                if candidate.safe
                and candidate.method is MatchMethod.AUTOMATIC
                and candidate.diagnostics.normalized_cost is not None
            ),
            key=lambda candidate: (candidate.diagnostics.normalized_cost, candidate.source_id),
        )
        if safe_automatic:
            winner = safe_automatic[0]
            blockers_list: list[BlockerCode] = []
            diagnostics = winner.diagnostics
            if len(safe_automatic) > 1:
                runner_cost = safe_automatic[1].diagnostics.normalized_cost
                assert diagnostics.normalized_cost is not None and runner_cost is not None
                denominator = max(abs(diagnostics.normalized_cost), np.finfo(float).eps)
                margin = (runner_cost - diagnostics.normalized_cost) / denominator
                diagnostics = replace(
                    diagnostics,
                    runner_up_cost=runner_cost,
                    runner_up_margin_fraction=margin,
                )
                winner = replace(winner, diagnostics=diagnostics)
                if margin <= active_settings.ambiguity_fraction:
                    blockers_list.append(BlockerCode.AMBIGUOUS_RUNNER_UP)
            return self._finish(segment, winner, evaluated, tuple(blockers_list))

        fallback = min(
            evaluated,
            key=lambda candidate: (
                candidate.diagnostics.normalized_cost
                if candidate.diagnostics.normalized_cost is not None
                else float("inf"),
                candidate.source_id,
            ),
        )
        return self._finish(segment, fallback, evaluated, (BlockerCode.NO_VALID_CANDIDATE,))

    @staticmethod
    def _finish(
        segment: SegmentRequest,
        winner: CandidateMatch,
        evaluated: Sequence[CandidateMatch],
        result_blockers: tuple[BlockerCode, ...],
    ) -> SegmentMatch:
        blockers = _ordered_unique((*winner.blockers, *result_blockers))
        status = MatchStatus.MATCHED if not blockers else MatchStatus.UNSAFE
        return SegmentMatch(
            segment_id=segment.segment_id,
            take=segment.take,
            status=status,
            method=winner.method,
            source_id=winner.source_id,
            source_in_seconds=winner.source_in_seconds,
            source_out_seconds=winner.source_out_seconds,
            diagnostics=winner.diagnostics,
            candidates=tuple(evaluated),
            blockers=blockers,
            warnings=winner.warnings,
        )

    @staticmethod
    def _evaluate_manual(
        segment: SegmentRequest,
        candidate: AlignmentCandidate,
        settings: AlignmentSettings,
    ) -> CandidateMatch:
        assert candidate.manual_offset_seconds is not None
        source_in = segment.master_start_seconds + candidate.manual_offset_seconds
        source_out = source_in + segment.duration_seconds
        blockers: list[BlockerCode] = []
        if source_in < candidate.start_seconds or source_out > candidate.end_seconds:
            blockers.extend((BlockerCode.INVALID_MANUAL_OFFSET, BlockerCode.OUT_OF_BOUNDS))
        return CandidateMatch(
            source_id=candidate.source_id,
            method=MatchMethod.MANUAL,
            source_in_seconds=source_in,
            source_out_seconds=source_out,
            diagnostics=MatchDiagnostics(
                settings=settings.as_dict(),
                fitted_slope=1.0,
                fitted_intercept_seconds=candidate.manual_offset_seconds,
                mapped_source_end_seconds=source_out,
                predicted_drift_seconds=Decimal(0),
                outlier_fraction=0.0,
                edge_stability_seconds=Decimal(0),
            ),
            blockers=tuple(blockers),
            warnings=("manual_offset_seconds bypassed feature extraction and DTW",),
        )

    def _evaluate_automatic(
        self,
        segment: SegmentRequest,
        master_audio: AnalysisAudio,
        candidate: AlignmentCandidate,
        settings: AlignmentSettings,
    ) -> CandidateMatch:
        guard = min(
            settings.edge_guard_seconds,
            segment.duration_seconds * settings.edge_guard_fraction,
        )
        try:
            base = self._align_with_guard(segment, master_audio, candidate, settings, guard)
        except FeatureError as exc:
            return self._failed_candidate(candidate, settings, _feature_blocker(exc))
        except (DtwError, ValueError, FloatingPointError):
            return self._failed_candidate(candidate, settings, BlockerCode.DTW_FAILED)

        diagnostics, source_in, source_out = base
        blockers: list[BlockerCode] = []
        if diagnostics.coverage is None or diagnostics.coverage < settings.minimum_coverage:
            blockers.append(BlockerCode.INCOMPLETE_COVERAGE)
        if (
            diagnostics.fitted_slope is None
            or diagnostics.fitted_slope <= 0
            or source_out <= source_in
        ):
            blockers.append(BlockerCode.NON_MONOTONIC_MAPPING)
        if (
            source_in < candidate.start_seconds
            or source_out > candidate.end_seconds
            or diagnostics.mapped_source_end_seconds is None
            or diagnostics.mapped_source_end_seconds > candidate.end_seconds
        ):
            blockers.append(BlockerCode.OUT_OF_BOUNDS)
        if (
            diagnostics.predicted_drift_seconds is None
            or abs(diagnostics.predicted_drift_seconds) > settings.maximum_error_seconds
        ):
            blockers.append(BlockerCode.EXCESS_DRIFT)
        if (
            diagnostics.outlier_fraction is None
            or diagnostics.outlier_fraction > settings.maximum_outlier_fraction
        ):
            blockers.append(BlockerCode.EXCESS_OUTLIERS)

        stability = self._edge_stability(
            segment, master_audio, candidate, settings, guard, source_in, source_out
        )
        diagnostics = replace(diagnostics, edge_stability_seconds=stability)
        if stability is None or stability > settings.maximum_error_seconds:
            blockers.append(BlockerCode.UNSTABLE_EDGES)
        return CandidateMatch(
            source_id=candidate.source_id,
            method=MatchMethod.AUTOMATIC,
            source_in_seconds=source_in,
            source_out_seconds=source_out,
            diagnostics=diagnostics,
            blockers=_ordered_unique(blockers),
        )

    def _align_with_guard(
        self,
        segment: SegmentRequest,
        master_audio: AnalysisAudio,
        candidate: AlignmentCandidate,
        settings: AlignmentSettings,
        guard: Decimal,
    ) -> tuple[MatchDiagnostics, Decimal, Decimal]:
        score_start = segment.master_start_seconds + guard
        score_end = segment.master_end_seconds - guard
        if score_end <= score_start:
            raise FeatureError("edge guard leaves no scored interval")
        query_samples = _slice_absolute(master_audio, score_start, score_end)
        reference_samples = _slice_absolute(
            candidate.audio,
            candidate.start_seconds,
            candidate.end_seconds,
        )
        query = self._extract_features(query_samples, master_audio.sample_rate, settings)
        reference = self._extract_features(reference_samples, candidate.audio.sample_rate, settings)
        path = self._align_path(query.values, reference.values, settings)

        coverage = float(np.unique(path.master_indices).size / query.frame_count)
        hop_seconds = settings.hop_length / settings.sample_rate
        master_local = guard.__float__() + path.master_indices.astype(np.float64) * hop_seconds
        source_absolute = (
            float(candidate.start_seconds) + path.source_indices.astype(np.float64) * hop_seconds
        )
        low, high = np.quantile(master_local, (0.05, 0.95))
        interior = (master_local >= low) & (master_local <= high)
        if np.count_nonzero(interior) >= 2:
            fit_master = master_local[interior]
            fit_source = source_absolute[interior]
        else:
            fit_master = master_local
            fit_source = source_absolute
        slope, intercept, outlier_fraction = _robust_affine(fit_master, fit_source, settings)
        source_in = _decimal(intercept)
        mapped_source_end = _decimal(slope * float(segment.duration_seconds) + intercept)
        unity_source_out = source_in + segment.duration_seconds
        drift = mapped_source_end - unity_source_out
        diagnostics = MatchDiagnostics(
            settings=settings.as_dict(),
            normalized_cost=path.normalized_cost,
            coverage=coverage,
            path_master_start_seconds=_decimal(master_local[0]),
            path_master_end_seconds=_decimal(master_local[-1]),
            path_source_start_seconds=_decimal(source_absolute[0]),
            path_source_end_seconds=_decimal(source_absolute[-1]),
            fitted_slope=slope,
            fitted_intercept_seconds=source_in,
            mapped_source_end_seconds=mapped_source_end,
            predicted_drift_seconds=drift,
            outlier_fraction=outlier_fraction,
        )
        return diagnostics, source_in, unity_source_out

    def _edge_stability(
        self,
        segment: SegmentRequest,
        master_audio: AnalysisAudio,
        candidate: AlignmentCandidate,
        settings: AlignmentSettings,
        guard: Decimal,
        source_in: Decimal,
        source_out: Decimal,
    ) -> Decimal | None:
        hop = Decimal(settings.hop_length) / Decimal(settings.sample_rate)
        perturbations = {max(Decimal(0), guard - hop), guard + hop}
        movements: list[Decimal] = []
        for perturbed_guard in sorted(perturbations):
            if perturbed_guard == guard:
                continue
            try:
                _, perturbed_in, perturbed_out = self._align_with_guard(
                    segment,
                    master_audio,
                    candidate,
                    settings,
                    perturbed_guard,
                )
            except (FeatureError, DtwError, ValueError, FloatingPointError):
                return None
            movements.extend((abs(perturbed_in - source_in), abs(perturbed_out - source_out)))
        return max(movements, default=Decimal(0))

    @staticmethod
    def _failed_candidate(
        candidate: AlignmentCandidate,
        settings: AlignmentSettings,
        blocker: BlockerCode,
    ) -> CandidateMatch:
        return CandidateMatch(
            source_id=candidate.source_id,
            method=MatchMethod.AUTOMATIC,
            source_in_seconds=None,
            source_out_seconds=None,
            diagnostics=MatchDiagnostics(settings=settings.as_dict()),
            blockers=(blocker,),
        )
