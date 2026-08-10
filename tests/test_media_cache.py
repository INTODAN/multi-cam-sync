from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path

import numpy as np

from multi_cam_sync.media import (
    AnalysisAudio,
    AnalysisCache,
    AudioRequest,
    CachingMediaReader,
    ContentFingerprint,
    MediaProbe,
    fingerprint_file,
)


def fingerprint(name: str = "/media/a.wav") -> ContentFingerprint:
    return ContentFingerprint(name, 100, 123, "a" * 64)


def audio(fp: ContentFingerprint | None = None) -> AnalysisAudio:
    return AnalysisAudio(
        np.ascontiguousarray(np.linspace(-1, 1, 100, dtype=np.float32)),
        100,
        Decimal("1.25"),
        fp or fingerprint(),
    )


def test_fingerprint_is_stable_and_invalidates_on_stat_and_sampled_content(tmp_path: Path) -> None:
    path = tmp_path / "physical recording.bin"
    path.write_bytes(b"a" * 200_000)
    first = fingerprint_file(path)
    assert fingerprint_file(path) == first

    path.write_bytes(b"b" + b"a" * 199_999)
    content_changed = fingerprint_file(path)
    assert content_changed.sampled_sha256 != first.sampled_sha256
    assert content_changed.size_bytes == first.size_bytes

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    mtime_changed = fingerprint_file(path)
    assert mtime_changed.modified_ns != content_changed.modified_ns

    path.write_bytes(path.read_bytes() + b"tail")
    assert fingerprint_file(path).size_bytes != mtime_changed.size_bytes


def test_cache_hit_setting_separation_and_corruption_recovery(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path / "outside-repository-cache")
    request = AudioRequest(
        Path("/not/read/by/cache.wav"), source_start_seconds=Decimal("1.25"), sample_rate=100
    )
    value = audio()
    key = cache.store(request, value)

    loaded = cache.load(request, value.fingerprint)
    assert loaded is not None
    np.testing.assert_array_equal(loaded.samples, value.samples)
    assert loaded.origin_seconds == Decimal("1.25")
    assert (
        cache.load(
            AudioRequest(request.path, source_start_seconds=Decimal("1.5"), sample_rate=100),
            value.fingerprint,
        )
        is None
    )

    (cache.root / f"{key}.npy").write_bytes(b"truncated")
    assert cache.load(request, value.fingerprint) is None
    assert not (cache.root / f"{key}.json").exists()
    assert not (cache.root / f"{key}.npy").exists()


def test_cache_rejects_old_schema_bad_checksum_and_nonfinite_array(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path / "cache")
    request = AudioRequest(Path("/a.wav"), source_start_seconds=Decimal("1.25"), sample_rate=100)
    value = audio()

    key = cache.store(request, value)
    metadata_path = cache.root / f"{key}.json"
    metadata_path.write_text(
        metadata_path.read_text().replace('"schema_version":1', '"schema_version":0')
    )
    assert cache.load(request, value.fingerprint) is None

    key = cache.store(request, value)
    metadata_path = cache.root / f"{key}.json"
    metadata_path.write_text(metadata_path.read_text().replace('"sha256":"', '"sha256":"bad'))
    assert cache.load(request, value.fingerprint) is None

    bad = AnalysisAudio(np.array([1.0], dtype=np.float32), 100, Decimal("1.25"), value.fingerprint)
    key = cache.store(request, bad)
    with (cache.root / f"{key}.npy").open("wb") as handle:
        np.save(handle, np.array([np.inf], dtype=np.float32), allow_pickle=False)
    assert cache.load(request, value.fingerprint) is None


def test_two_atomic_writers_leave_one_valid_complete_entry(tmp_path: Path) -> None:
    cache = AnalysisCache(tmp_path / "cache")
    request = AudioRequest(Path("/a.wav"), source_start_seconds=Decimal("1.25"), sample_rate=100)
    value = audio()
    with ThreadPoolExecutor(max_workers=2) as executor:
        keys = list(executor.map(lambda _: cache.store(request, value), range(2)))
    assert keys[0] == keys[1]
    loaded = cache.load(request, value.fingerprint)
    assert loaded is not None
    np.testing.assert_array_equal(loaded.samples, value.samples)


class CountingReader:
    def __init__(self, value: AnalysisAudio) -> None:
        self.value = value
        self.loads = 0

    def probe(self, path: Path) -> MediaProbe:
        raise AssertionError("probe not expected")

    def load_audio(self, request: AudioRequest) -> AnalysisAudio:
        self.loads += 1
        return self.value


def test_caching_reader_decodes_only_on_miss(tmp_path: Path) -> None:
    media_path = tmp_path / "source.wav"
    media_path.write_bytes(b"content")
    fp = fingerprint_file(media_path)
    value = audio(fp)
    backend = CountingReader(value)
    reader = CachingMediaReader(backend, AnalysisCache(tmp_path / "cache"))
    request = AudioRequest(media_path, source_start_seconds=Decimal("1.25"), sample_rate=100)

    first = reader.load_audio(request)
    second = reader.load_audio(request)

    assert backend.loads == 1
    np.testing.assert_array_equal(first.samples, second.samples)


def test_unwritable_cache_does_not_hide_readable_media(tmp_path: Path) -> None:
    media_path = tmp_path / "source.wav"
    media_path.write_bytes(b"content")
    value = audio(fingerprint_file(media_path))
    backend = CountingReader(value)

    class UnwritableCache(AnalysisCache):
        def store(self, request: AudioRequest, audio: AnalysisAudio) -> str:
            del request, audio
            raise PermissionError("read only")

    reader = CachingMediaReader(backend, UnwritableCache(tmp_path / "cache"))

    result = reader.load_audio(
        AudioRequest(media_path, source_start_seconds=Decimal("1.25"), sample_rate=100)
    )

    assert result is value
    assert backend.loads == 1
