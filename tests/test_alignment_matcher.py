from __future__ import annotations

from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest

from multi_cam_sync.alignment import (
    AlignmentCandidate,
    AlignmentSettings,
    BlockerCode,
    DtwPath,
    EmptyCandidatesError,
    FeatureSequence,
    MatchMethod,
    MatchStatus,
    SegmentMatcher,
    SegmentRequest,
)
from multi_cam_sync.media import AnalysisAudio, ContentFingerprint


def fp(name: str) -> ContentFingerprint:
    return ContentFingerprint(f"/media/{name}.wav", 1_000, 1, name.ljust(64, "0"))


def analysis(samples: np.ndarray, *, origin: str = "0", name: str = "audio") -> AnalysisAudio:
    return AnalysisAudio(
        np.ascontiguousarray(samples, dtype=np.float32),
        100,
        Decimal(origin),
        fp(name),
    )


def settings() -> AlignmentSettings:
    return AlignmentSettings(
        sample_rate=100,
        n_mfcc=1,
        n_mels=1,
        n_fft=8,
        hop_length=1,
        delta_width=3,
    )


def identity_features(
    samples: np.ndarray, sample_rate: int, active: AlignmentSettings
) -> FeatureSequence:
    del active
    return FeatureSequence(np.ascontiguousarray(samples[:, None]), sample_rate, 1)


class ExactSubsequenceAligner:
    def __init__(self, *, cost: float = 1.0, slope: float = 1.0, coverage: float = 1.0) -> None:
        self.cost = cost
        self.slope = slope
        self.coverage = coverage
        self.calls = 0

    def __call__(
        self, query: np.ndarray, reference: np.ndarray, active: AlignmentSettings
    ) -> DtwPath:
        del active
        self.calls += 1
        matches = np.flatnonzero(np.isclose(reference[:, 0], query[0, 0]))
        if matches.size == 0:
            raise ValueError("query not found")
        start = int(matches[0])
        count = max(2, round(query.shape[0] * self.coverage))
        master = np.arange(count, dtype=np.int64)
        source = start + np.rint(master * self.slope).astype(np.int64)
        return DtwPath(master, source, self.cost)


def fixture_audio(*, source_origin: str = "0") -> tuple[AnalysisAudio, AnalysisAudio]:
    master_values = np.arange(400, dtype=np.float32) + 1
    prefix = np.full(200, -100, dtype=np.float32)
    suffix = np.full(100, -200, dtype=np.float32)
    source_values = np.concatenate((prefix, master_values, suffix))
    return analysis(master_values, name="master"), analysis(
        source_values, origin=source_origin, name="source"
    )


def test_match_returns_absolute_cropped_coordinates_and_stable_settings() -> None:
    master, source = fixture_audio(source_origin="10")
    matcher = SegmentMatcher(
        feature_extractor=identity_features, path_aligner=ExactSubsequenceAligner()
    )
    segment = SegmentRequest("seg-1", "Take 1", Decimal(1), Decimal(3))
    candidate = AlignmentCandidate("camera-a", source)

    result = matcher.match(segment, master, [candidate], settings())

    assert result.status is MatchStatus.MATCHED
    assert result.method is MatchMethod.AUTOMATIC
    assert result.source_id == "camera-a"
    assert result.source_in_seconds is not None
    assert result.source_out_seconds is not None
    assert abs(result.source_in_seconds - Decimal(13)) < Decimal("0.000001")
    assert abs(result.source_out_seconds - Decimal(15)) < Decimal("0.000001")
    assert result.diagnostics.predicted_drift_seconds == pytest.approx(
        Decimal(0), abs=Decimal("1e-9")
    )
    assert result.diagnostics.settings["distance"] == "cosine"
    assert result.diagnostics.settings["open_begin"] is True
    assert result.safe_for_planning


def test_empty_candidates_fail_before_feature_or_dtw_work() -> None:
    master, _ = fixture_audio()
    calls = 0

    def forbidden(*args: object) -> FeatureSequence:
        nonlocal calls
        calls += 1
        raise AssertionError(args)

    matcher = SegmentMatcher(feature_extractor=forbidden)
    with pytest.raises(EmptyCandidatesError, match="bypass"):
        matcher.match(
            SegmentRequest("seg", "Take 9", Decimal(0), Decimal(1)), master, [], settings()
        )
    assert calls == 0


def test_manual_offset_bypasses_features_and_validates_occurrence_bounds() -> None:
    master, source = fixture_audio()

    def forbidden(*args: object) -> FeatureSequence:
        raise AssertionError(args)

    matcher = SegmentMatcher(feature_extractor=forbidden)
    segment = SegmentRequest("seg", "Take 2", Decimal(1), Decimal(3))
    accepted = matcher.match(
        segment,
        master,
        [AlignmentCandidate("manual", source, manual_offset_seconds=Decimal(2))],
        settings(),
    )
    assert accepted.status is MatchStatus.MATCHED
    assert accepted.source_in_seconds == Decimal(3)
    assert accepted.source_out_seconds == Decimal(5)
    assert accepted.method is MatchMethod.MANUAL
    assert "bypassed" in accepted.warnings[0]
    assert accepted.diagnostics.normalized_cost is None

    rejected = matcher.match(
        segment,
        master,
        [AlignmentCandidate("manual", source, manual_offset_seconds=Decimal(20))],
        settings(),
    )
    assert rejected.status is MatchStatus.UNSAFE
    assert BlockerCode.INVALID_MANUAL_OFFSET in rejected.blockers
    assert BlockerCode.OUT_OF_BOUNDS in rejected.blockers


def test_incomplete_path_and_excess_drift_are_specific_unsafe_results() -> None:
    master, source = fixture_audio()
    segment = SegmentRequest("seg", "Take 3", Decimal(1), Decimal(3))
    candidate = AlignmentCandidate("camera", source)

    incomplete = SegmentMatcher(
        feature_extractor=identity_features,
        path_aligner=ExactSubsequenceAligner(coverage=0.8),
    ).match(segment, master, [candidate], settings())
    assert incomplete.status is MatchStatus.UNSAFE
    assert BlockerCode.INCOMPLETE_COVERAGE in incomplete.blockers

    drifting = SegmentMatcher(
        feature_extractor=identity_features,
        path_aligner=ExactSubsequenceAligner(slope=1.1),
    ).match(segment, master, [candidate], settings())
    assert drifting.status is MatchStatus.UNSAFE
    assert BlockerCode.EXCESS_DRIFT in drifting.blockers


def test_multiple_candidates_use_cost_then_stable_id_and_block_close_runner_up() -> None:
    master, source = fixture_audio()
    segment = SegmentRequest("seg", "Take 4", Decimal(1), Decimal(3))
    candidates = [AlignmentCandidate("z-source", source), AlignmentCandidate("a-source", source)]

    ambiguous = SegmentMatcher(
        feature_extractor=identity_features,
        path_aligner=ExactSubsequenceAligner(cost=1.0),
    ).match(segment, master, candidates, settings())

    assert ambiguous.source_id == "a-source"
    assert ambiguous.status is MatchStatus.UNSAFE
    assert BlockerCode.AMBIGUOUS_RUNNER_UP in ambiguous.blockers
    assert ambiguous.diagnostics.runner_up_margin_fraction == 0.0


def test_explicit_bounds_select_two_logical_occurrences_in_one_physical_recording() -> None:
    master_values = np.arange(400, dtype=np.float32) + 1
    source_values = np.concatenate(
        (
            np.full(100, -10, dtype=np.float32),
            master_values,
            np.full(100, -20, dtype=np.float32),
            master_values,
        )
    )
    master = analysis(master_values, name="bounded-master")
    source = analysis(source_values, name="shared-physical-source")
    segment = SegmentRequest("seg", "Take 4", Decimal(1), Decimal(3))
    matcher = SegmentMatcher(
        feature_extractor=identity_features,
        path_aligner=ExactSubsequenceAligner(),
    )
    occurrence_a = AlignmentCandidate(
        "occurrence-a",
        source,
        source_start_seconds=Decimal(1),
        source_end_seconds=Decimal(5),
    )
    occurrence_b = AlignmentCandidate(
        "occurrence-b",
        source,
        source_start_seconds=Decimal(6),
        source_end_seconds=Decimal(10),
    )

    result_a = matcher.match(segment, master, [occurrence_a], settings())
    result_b = matcher.match(segment, master, [occurrence_b], settings())

    assert result_a.status is MatchStatus.MATCHED
    assert result_b.status is MatchStatus.MATCHED
    assert result_a.source_in_seconds is not None
    assert result_b.source_in_seconds is not None
    assert abs(result_a.source_in_seconds - Decimal(2)) < Decimal("0.000001")
    assert abs(result_b.source_in_seconds - Decimal(7)) < Decimal("0.000001")


def test_failure_keeps_candidate_diagnostics_without_inventing_not_provided() -> None:
    master, source = fixture_audio()
    candidate = AlignmentCandidate(
        "camera",
        source,
        source_start_seconds=Decimal(1),
        source_end_seconds=Decimal(4),
        audio_reference_id="additional-2",
    )

    def failure(*args: object) -> DtwPath:
        raise ValueError(args)

    result = SegmentMatcher(feature_extractor=identity_features, path_aligner=failure).match(
        SegmentRequest("seg", "Take 5", Decimal(1), Decimal(3)),
        master,
        [candidate],
        settings(),
    )

    assert result.status is MatchStatus.UNSAFE
    assert result.source_id == "camera"
    assert result.source_in_seconds is None
    assert BlockerCode.DTW_FAILED in result.blockers
    assert BlockerCode.NO_VALID_CANDIDATE in result.blockers
    assert len(result.candidates) == 1
    assert result.candidates[0].search_start_seconds == candidate.start_seconds
    assert result.candidates[0].search_end_seconds == candidate.end_seconds
    assert result.candidates[0].audio_reference_id == "additional-2"
    assert not hasattr(MatchStatus, "NOT_PROVIDED")


def test_default_settings_are_exactly_serialized() -> None:
    serialized = AlignmentSettings().as_dict()
    assert serialized["sample_rate"] == 22_050
    assert serialized["n_mfcc"] == 80
    assert serialized["hop_length"] == 256
    assert serialized["delta_orders"] == [1, 2]
    assert serialized["step_pattern"] == "asymmetric"
    assert serialized["edge_guard_seconds"] == "0.150"
    assert serialized["minimum_coverage"] == 0.95
    assert serialized["ambiguity_fraction"] == 0.05


def test_real_mfcc_dtw_matches_filtered_noisy_music_within_two_frames() -> None:
    sample_rate = 22_050
    time = np.arange(sample_rate * 6, dtype=np.float32) / sample_rate
    chirp_phase = 2 * np.pi * (100 * time + 65 * time**2)
    performance = (
        0.30 * np.sin(2 * np.pi * (180 + 8 * time) * time)
        + 0.20 * np.sin(2 * np.pi * 330 * time)
        + 0.15 * np.sin(chirp_phase)
    ).astype(np.float32)
    for position in (0.37, 1.19, 2.71, 4.22, 5.51):
        index = round(position * sample_rate)
        performance[index : index + 80] += np.hanning(80).astype(np.float32)

    rng = np.random.default_rng(42)
    filtered = np.convolve(performance, np.array([0.8, 0.15], dtype=np.float32), mode="same")
    master_values = filtered + rng.normal(0, 0.003, performance.size).astype(np.float32)
    leading_seconds = Decimal("1.4")
    source_values = np.concatenate(
        (
            np.zeros(round(float(leading_seconds) * sample_rate), dtype=np.float32),
            performance,
            np.zeros(sample_rate, dtype=np.float32),
        )
    )
    master = AnalysisAudio(
        np.ascontiguousarray(master_values, dtype=np.float32),
        sample_rate,
        Decimal(0),
        fp("real-master"),
    )
    source = AnalysisAudio(
        np.ascontiguousarray(source_values, dtype=np.float32),
        sample_rate,
        Decimal(0),
        fp("real-source"),
    )
    segment = SegmentRequest("numeric", "Take 6", Decimal("0.5"), Decimal("5.5"))

    result = SegmentMatcher().match(
        segment,
        master,
        [AlignmentCandidate("camera", source)],
        AlignmentSettings(timeline_frame_rate=Fraction(30, 1)),
    )

    expected_in = leading_seconds + segment.master_start_seconds
    assert result.status is MatchStatus.MATCHED
    assert result.source_in_seconds is not None
    for rate in (Fraction(24_000, 1_001), Fraction(24), Fraction(25), Fraction(30)):
        two_frames = Decimal(2 * rate.denominator) / Decimal(rate.numerator)
        assert abs(result.source_in_seconds - expected_in) <= two_frames
    assert result.diagnostics.coverage == 1.0
    assert result.diagnostics.predicted_drift_seconds is not None
