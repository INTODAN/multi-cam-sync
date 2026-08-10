from __future__ import annotations

import numpy as np
import pytest

from multi_cam_sync.alignment import (
    AlignmentSettings,
    FeatureError,
    align_feature_sequences,
    extract_features,
)


def musical_signal(sample_rate: int, seconds: float) -> np.ndarray:
    time = np.arange(round(sample_rate * seconds), dtype=np.float32) / sample_rate
    signal = (
        0.45 * np.sin(2 * np.pi * (170 + 40 * time) * time)
        + 0.25 * np.sin(2 * np.pi * 311 * time)
        + 0.15 * np.sin(2 * np.pi * 487 * time)
    )
    signal[:: max(1, sample_rate // 5)] += 0.7
    return np.ascontiguousarray(signal, dtype=np.float32)


def test_mfcc_delta_features_are_time_major_finite_and_normalized() -> None:
    settings = AlignmentSettings()
    features = extract_features(
        musical_signal(settings.sample_rate, 1.0), settings.sample_rate, settings
    )

    assert features.values.shape[1] == settings.n_mfcc * 3
    assert features.values.dtype == np.float32
    assert features.values.flags.c_contiguous
    assert np.isfinite(features.values).all()
    np.testing.assert_allclose(features.values.mean(axis=0), 0.0, atol=2e-4)


def test_features_reject_silence_nonfinite_wrong_rate_and_too_short() -> None:
    settings = AlignmentSettings()
    with pytest.raises(FeatureError, match="silent"):
        extract_features(
            np.zeros(settings.sample_rate, dtype=np.float32), settings.sample_rate, settings
        )
    with pytest.raises(FeatureError, match="finite"):
        extract_features(np.array([np.nan], dtype=np.float32), settings.sample_rate, settings)
    with pytest.raises(FeatureError, match="22050"):
        extract_features(np.ones(10_000, dtype=np.float32), 48_000, settings)
    with pytest.raises(FeatureError, match="at least"):
        extract_features(np.ones(100, dtype=np.float32), settings.sample_rate, settings)


def test_dtw_wrapper_locates_query_inside_reference_and_returns_monotonic_path() -> None:
    rng = np.random.default_rng(12)
    reference = rng.normal(size=(80, 6)).astype(np.float32)
    query = reference[23:51].copy()
    path = align_feature_sequences(query, reference, AlignmentSettings())

    assert path.master_indices[0] == 0
    assert path.master_indices[-1] == query.shape[0] - 1
    assert 20 <= path.source_indices[0] <= 25
    assert 48 <= path.source_indices[-1] <= 52
    assert np.all(np.diff(path.master_indices) >= 0)
    assert np.all(np.diff(path.source_indices) >= 0)
    assert np.isfinite(path.normalized_cost)
