"""MFCC plus delta feature extraction adapted from Elidan Take Picker."""

from __future__ import annotations

from dataclasses import dataclass

import librosa
import numpy as np
from numpy.typing import NDArray

from .models import AlignmentSettings


class FeatureError(ValueError):
    """Input cannot produce meaningful alignment features."""


@dataclass(frozen=True, slots=True)
class FeatureSequence:
    """Time-major, normalized feature frames."""

    values: NDArray[np.float32]
    sample_rate: int
    hop_length: int

    @property
    def frame_count(self) -> int:
        return self.values.shape[0]


def extract_features(
    samples: NDArray[np.float32],
    sample_rate: int,
    settings: AlignmentSettings,
) -> FeatureSequence:
    """Compute normalized MFCC, delta, and delta-delta time frames."""
    values = np.asarray(samples, dtype=np.float32)
    if values.ndim != 1 or values.size == 0 or not np.isfinite(values).all():
        raise FeatureError("audio samples must be non-empty, finite, and one-dimensional")
    if sample_rate != settings.sample_rate:
        raise FeatureError(f"analysis audio must be {settings.sample_rate} Hz, got {sample_rate}")
    if float(np.max(np.abs(values))) <= settings.zscore_epsilon:
        raise FeatureError("audio is silent")

    mfcc = librosa.feature.mfcc(
        y=values,
        sr=sample_rate,
        n_mfcc=settings.n_mfcc,
        n_mels=settings.n_mels,
        n_fft=settings.n_fft,
        hop_length=settings.hop_length,
    )
    if mfcc.shape[1] < settings.delta_width:
        raise FeatureError(
            f"audio produces {mfcc.shape[1]} feature frames; "
            f"at least {settings.delta_width} are required"
        )
    derivatives = [
        librosa.feature.delta(mfcc, order=order, width=settings.delta_width, mode="interp")
        for order in settings.delta_orders
    ]
    combined = np.concatenate([mfcc, *derivatives], axis=0)
    means = np.mean(combined, axis=1, keepdims=True)
    deviations = np.std(combined, axis=1, keepdims=True)
    normalized = (combined - means) / (deviations + settings.zscore_epsilon)
    time_major = np.ascontiguousarray(normalized.T, dtype=np.float32)
    if not np.isfinite(time_major).all():
        raise FeatureError("feature extraction produced non-finite values")
    return FeatureSequence(time_major, sample_rate, settings.hop_length)
