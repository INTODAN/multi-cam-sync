"""Content fingerprints and derived analysis keys."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .models import AudioRequest, ContentFingerprint, MediaError

FINGERPRINT_SAMPLE_BYTES = 65_536
FINGERPRINT_SCHEMA_VERSION = 1


class MediaFingerprintError(MediaError):
    """A physical media item could not be fingerprinted."""


def fingerprint_file(path: Path) -> ContentFingerprint:
    """Fingerprint stat data plus file size and the first/last 64 KiB."""
    try:
        canonical = path.expanduser().resolve(strict=True)
        stat = canonical.stat()
        digest = hashlib.sha256()
        digest.update(stat.st_size.to_bytes(16, byteorder="big", signed=False))
        with canonical.open("rb") as handle:
            digest.update(handle.read(FINGERPRINT_SAMPLE_BYTES))
            if stat.st_size > FINGERPRINT_SAMPLE_BYTES:
                handle.seek(max(0, stat.st_size - FINGERPRINT_SAMPLE_BYTES))
                digest.update(handle.read(FINGERPRINT_SAMPLE_BYTES))
    except (OSError, ValueError) as exc:
        raise MediaFingerprintError("media file is missing or unreadable", path=path) from exc

    return ContentFingerprint(
        canonical_path=str(canonical),
        size_bytes=stat.st_size,
        modified_ns=stat.st_mtime_ns,
        sampled_sha256=digest.hexdigest(),
    )


def analysis_cache_key(
    request: AudioRequest,
    fingerprint: ContentFingerprint,
    *,
    decoder_version: str,
    cache_schema_version: int,
) -> str:
    """Hash every input capable of changing decoded analysis audio."""
    payload = {
        "cache_schema_version": cache_schema_version,
        "decoder_version": decoder_version,
        "fingerprint_schema_version": FINGERPRINT_SCHEMA_VERSION,
        "fingerprint": fingerprint.as_dict(),
        "audio_stream_index": request.audio_stream_index,
        "source_start_seconds": str(request.source_start_seconds),
        "source_end_seconds": None
        if request.source_end_seconds is None
        else str(request.source_end_seconds),
        "sample_rate": request.sample_rate,
        "channels": request.channels,
        "decoder_settings": {"dtype": "float32", "layout": "mono"},
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
