"""Validated, non-pickle, atomic analysis-audio cache."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

import numpy as np
from platformdirs import user_cache_path

from .decode import DECODER_VERSION
from .fingerprint import analysis_cache_key, fingerprint_file
from .models import AnalysisAudio, AudioRequest, ContentFingerprint, MediaProbe, MediaReader

CACHE_SCHEMA_VERSION = 1


def _array_checksum(samples: np.ndarray) -> str:
    return hashlib.sha256(memoryview(samples).cast("B")).hexdigest()


class _SyncableFile(Protocol):
    def flush(self) -> None: ...

    def fileno(self) -> int: ...


def _fsync(handle: _SyncableFile) -> None:
    handle.flush()
    with suppress(OSError):
        os.fsync(handle.fileno())


class AnalysisCache:
    """Best-effort decoded audio cache; corruption is always treated as a miss."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or user_cache_path("multi-cam-sync", appauthor=False) / "analysis-audio"

    def key_for(self, request: AudioRequest, fingerprint: ContentFingerprint) -> str:
        return analysis_cache_key(
            request,
            fingerprint,
            decoder_version=DECODER_VERSION,
            cache_schema_version=CACHE_SCHEMA_VERSION,
        )

    def load(self, request: AudioRequest, fingerprint: ContentFingerprint) -> AnalysisAudio | None:
        key = self.key_for(request, fingerprint)
        metadata_path = self.root / f"{key}.json"
        array_path = self.root / f"{key}.npy"
        if not metadata_path.exists() or not array_path.exists():
            return None
        try:
            raw = json.loads(metadata_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError
            if raw.get("schema_version") != CACHE_SCHEMA_VERSION or raw.get("key") != key:
                raise ValueError
            with array_path.open("rb") as handle:
                samples = np.load(handle, allow_pickle=False)
            if samples.dtype != np.float32 or samples.ndim != 1 or not samples.flags.c_contiguous:
                raise ValueError
            if list(samples.shape) != raw.get("shape") or not np.isfinite(samples).all():
                raise ValueError
            if _array_checksum(samples) != raw.get("sha256"):
                raise ValueError
            origin = Decimal(str(raw["origin_seconds"]))
            if not origin.is_finite() or origin < 0:
                raise ValueError
            if raw.get("sample_rate") != request.sample_rate:
                raise ValueError
            return AnalysisAudio(
                samples=np.ascontiguousarray(samples),
                sample_rate=request.sample_rate,
                origin_seconds=origin,
                fingerprint=fingerprint,
            )
        except (
            EOFError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
            InvalidOperation,
        ):
            self._discard(metadata_path, array_path)
            return None

    def store(self, request: AudioRequest, audio: AnalysisAudio) -> str:
        key = self.key_for(request, audio.fingerprint)
        self.root.mkdir(parents=True, exist_ok=True)
        metadata_path = self.root / f"{key}.json"
        array_path = self.root / f"{key}.npy"
        array_tmp: Path | None = None
        metadata_tmp: Path | None = None
        metadata = {
            "schema_version": CACHE_SCHEMA_VERSION,
            "key": key,
            "sample_rate": audio.sample_rate,
            "origin_seconds": str(audio.origin_seconds),
            "shape": list(audio.samples.shape),
            "dtype": "float32",
            "sha256": _array_checksum(audio.samples),
        }
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.root, prefix=f".{key}.", suffix=".npy", delete=False
            ) as handle:
                array_tmp = Path(handle.name)
                np.save(handle, audio.samples, allow_pickle=False)
                _fsync(handle)
            with tempfile.NamedTemporaryFile(
                dir=self.root,
                prefix=f".{key}.",
                suffix=".json",
                mode="w+b",
                delete=False,
            ) as handle:
                metadata_tmp = Path(handle.name)
                handle.write(json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode())
                _fsync(handle)
            os.replace(array_tmp, array_path)
            array_tmp = None
            os.replace(metadata_tmp, metadata_path)
            metadata_tmp = None
        finally:
            for temporary in (array_tmp, metadata_tmp):
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return key

    @staticmethod
    def _discard(*paths: Path) -> None:
        for path in paths:
            with suppress(OSError):
                path.unlink(missing_ok=True)


class CachingMediaReader:
    """Decorator that fingerprints before delegating cache misses."""

    def __init__(self, reader: MediaReader, cache: AnalysisCache) -> None:
        self._reader = reader
        self._cache = cache

    def probe(self, path: Path) -> MediaProbe:
        return self._reader.probe(path)

    def load_audio(self, request: AudioRequest) -> AnalysisAudio:
        fingerprint = fingerprint_file(request.path)
        cached = self._cache.load(request, fingerprint)
        if cached is not None:
            return cached
        decoded = self._reader.load_audio(request)
        # A read-only or temporarily unavailable cache must not hide readable media.
        with suppress(OSError):
            self._cache.store(request, decoded)
        return decoded
