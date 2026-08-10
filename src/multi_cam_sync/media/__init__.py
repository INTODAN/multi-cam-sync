"""Media probing, decoding, fingerprints, and cache."""

from .cache import CACHE_SCHEMA_VERSION, AnalysisCache, CachingMediaReader
from .decode import DECODER_VERSION, FFmpegMediaReader, ffmpeg_arguments, normalize_samples
from .fingerprint import FINGERPRINT_SCHEMA_VERSION, analysis_cache_key, fingerprint_file
from .models import (
    AnalysisAudio,
    AudioRequest,
    ContentFingerprint,
    InvalidMediaBoundsError,
    MediaDecodeError,
    MediaError,
    MediaExecutableNotFoundError,
    MediaProbe,
    MediaProbeError,
    MediaReader,
    MediaStream,
    NoAudioStreamError,
)
from .probe import CommandResult, CommandRunner, SubprocessRunner, parse_ffprobe_json, probe_media

__all__ = [
    "CACHE_SCHEMA_VERSION",
    "DECODER_VERSION",
    "FINGERPRINT_SCHEMA_VERSION",
    "AnalysisAudio",
    "AnalysisCache",
    "AudioRequest",
    "CachingMediaReader",
    "CommandResult",
    "CommandRunner",
    "ContentFingerprint",
    "FFmpegMediaReader",
    "InvalidMediaBoundsError",
    "MediaDecodeError",
    "MediaError",
    "MediaExecutableNotFoundError",
    "MediaProbe",
    "MediaProbeError",
    "MediaReader",
    "MediaStream",
    "NoAudioStreamError",
    "SubprocessRunner",
    "analysis_cache_key",
    "ffmpeg_arguments",
    "fingerprint_file",
    "normalize_samples",
    "parse_ffprobe_json",
    "probe_media",
]
