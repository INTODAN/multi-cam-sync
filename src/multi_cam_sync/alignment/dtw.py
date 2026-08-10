"""Small project-owned wrapper around dtw-python subsequence alignment."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from dtw import dtw
from numpy.typing import NDArray

from .models import AlignmentSettings


class DtwError(RuntimeError):
    """dtw-python failed or returned a malformed path."""


@dataclass(frozen=True, slots=True)
class DtwPath:
    master_indices: NDArray[np.int64]
    source_indices: NDArray[np.int64]
    normalized_cost: float


def align_feature_sequences(
    query: NDArray[np.float32],
    reference: NDArray[np.float32],
    settings: AlignmentSettings,
) -> DtwPath:
    """Locate the complete query within the reference with asymmetric open DTW."""
    if query.ndim != 2 or reference.ndim != 2 or query.shape[1] != reference.shape[1]:
        raise DtwError("query and reference feature matrices are incompatible")
    try:
        result = dtw(
            query,
            reference,
            dist_method=settings.distance,
            step_pattern=settings.step_pattern,
            open_begin=settings.open_begin,
            open_end=settings.open_end,
            keep_internals=False,
        )
        master = np.asarray(result.index1, dtype=np.int64)
        source = np.asarray(result.index2, dtype=np.int64)
        cost = float(result.normalizedDistance)
    except Exception as exc:  # dtw-python exposes several backend exception types
        raise DtwError(f"subsequence DTW failed: {exc}") from exc
    if master.ndim != 1 or source.ndim != 1 or master.size != source.size or master.size < 2:
        raise DtwError("subsequence DTW returned an invalid path")
    if not np.isfinite(cost):
        raise DtwError("subsequence DTW returned a non-finite normalized cost")
    order = np.lexsort((source, master))
    master = np.ascontiguousarray(master[order])
    source = np.ascontiguousarray(source[order])
    if np.any(np.diff(master) < 0) or np.any(np.diff(source) < 0):
        raise DtwError("subsequence DTW path is not monotonic")
    return DtwPath(master, source, cost)
