"""Direct and ffmpeg-backed analysis-audio decoding."""

from __future__ import annotations

import tempfile
from decimal import Decimal
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

from .fingerprint import fingerprint_file
from .models import (
    AnalysisAudio,
    AudioRequest,
    InvalidMediaBoundsError,
    MediaDecodeError,
    MediaExecutableNotFoundError,
    MediaProbe,
)
from .probe import CommandRunner, SubprocessRunner, _safe_stderr, probe_media

DECODER_VERSION = "analysis-audio-v1"
_ROUNDING_SAMPLE_TOLERANCE = 1


def normalize_samples(samples: np.ndarray, *, path: Path) -> np.ndarray:
    """Convert decoded mono/stereo samples to contiguous finite mono float32."""
    values = np.asarray(samples)
    if values.ndim == 2:
        values = values.mean(axis=1)
    if values.ndim != 1 or values.size == 0:
        raise MediaDecodeError("decoder returned empty or unsupported sample shape", path=path)
    result = np.ascontiguousarray(values, dtype=np.float32)
    if not np.isfinite(result).all():
        raise MediaDecodeError("decoder returned NaN or infinite samples", path=path)
    return result


def validate_audio_request(request: AudioRequest, probe: MediaProbe) -> Decimal:
    """Validate stream and crop bounds; return the exact requested end."""
    if request.audio_stream_index >= len(probe.audio_streams):
        raise InvalidMediaBoundsError(
            f"audio stream {request.audio_stream_index} does not exist",
            path=request.path,
        )
    end = (
        request.source_end_seconds
        if request.source_end_seconds is not None
        else probe.duration_seconds
    )
    if request.source_start_seconds >= probe.duration_seconds:
        raise InvalidMediaBoundsError("source start is outside media duration", path=request.path)
    overflow = end - probe.duration_seconds
    overflow_samples = overflow * Decimal(request.sample_rate)
    if overflow_samples > Decimal(_ROUNDING_SAMPLE_TOLERANCE) + Decimal("0.000001"):
        raise InvalidMediaBoundsError(
            f"source end {end} exceeds media duration {probe.duration_seconds}",
            path=request.path,
        )
    if overflow > 0:
        end = probe.duration_seconds
    if end <= request.source_start_seconds:
        raise InvalidMediaBoundsError("source bounds produce an empty interval", path=request.path)
    return end


def ffmpeg_arguments(
    request: AudioRequest, output_path: Path, *, executable: str = "ffmpeg"
) -> list[str]:
    """Build the exact shell-free ffmpeg extraction invocation."""
    arguments = [executable, "-v", "error", "-nostdin", "-y", "-i", str(request.path)]
    if request.source_start_seconds:
        arguments.extend(["-ss", str(request.source_start_seconds)])
    if request.source_end_seconds is not None:
        arguments.extend(["-to", str(request.source_end_seconds)])
    arguments.extend(
        [
            "-map",
            f"0:a:{request.audio_stream_index}",
            "-vn",
            "-ac",
            str(request.channels),
            "-ar",
            str(request.sample_rate),
            "-c:a",
            "pcm_f32le",
            str(output_path),
        ]
    )
    return arguments


def _load_soundfile(request: AudioRequest, end: Decimal) -> np.ndarray:
    with sf.SoundFile(request.path) as handle:
        start_frame = int(request.source_start_seconds * handle.samplerate)
        end_frame = int(end * handle.samplerate)
        handle.seek(start_frame)
        values = handle.read(frames=end_frame - start_frame, dtype="float32", always_2d=True)
        native_rate = handle.samplerate
    mono = normalize_samples(values, path=request.path)
    if native_rate != request.sample_rate:
        mono = normalize_samples(
            librosa.resample(mono, orig_sr=native_rate, target_sr=request.sample_rate),
            path=request.path,
        )
    return mono


def _load_ffmpeg(
    request: AudioRequest,
    *,
    runner: CommandRunner,
    executable: str,
) -> np.ndarray:
    try:
        with tempfile.TemporaryDirectory(prefix="multi-cam-sync-audio-") as temp_dir:
            output_path = Path(temp_dir) / "analysis.wav"
            try:
                result = runner.run(ffmpeg_arguments(request, output_path, executable=executable))
            except FileNotFoundError as exc:
                raise MediaExecutableNotFoundError(
                    f"required executable not found ({executable})", path=request.path
                ) from exc
            if result.returncode != 0:
                raise MediaDecodeError(
                    f"ffmpeg decode failed: {_safe_stderr(result.stderr)}", path=request.path
                )
            values, native_rate = sf.read(output_path, dtype="float32", always_2d=True)
    except (MediaDecodeError, MediaExecutableNotFoundError):
        raise
    except (OSError, RuntimeError, sf.LibsndfileError) as exc:
        raise MediaDecodeError(
            "ffmpeg output was missing or unreadable", path=request.path
        ) from exc
    mono = normalize_samples(values, path=request.path)
    if native_rate != request.sample_rate:
        mono = normalize_samples(
            librosa.resample(mono, orig_sr=native_rate, target_sr=request.sample_rate),
            path=request.path,
        )
    return mono


class FFmpegMediaReader:
    """Media reader preferring direct soundfile access, with ffmpeg fallback."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        ffprobe_executable: str = "ffprobe",
        ffmpeg_executable: str = "ffmpeg",
    ) -> None:
        self._runner = runner or SubprocessRunner()
        self._ffprobe_executable = ffprobe_executable
        self._ffmpeg_executable = ffmpeg_executable

    def probe(self, path: Path) -> MediaProbe:
        return probe_media(path, runner=self._runner, executable=self._ffprobe_executable)

    def load_audio(self, request: AudioRequest) -> AnalysisAudio:
        probe = self.probe(request.path)
        end = validate_audio_request(request, probe)
        try:
            samples = _load_soundfile(request, end)
        except (OSError, RuntimeError, sf.LibsndfileError):
            samples = _load_ffmpeg(request, runner=self._runner, executable=self._ffmpeg_executable)
        return AnalysisAudio(
            samples=samples,
            sample_rate=request.sample_rate,
            origin_seconds=request.source_start_seconds,
            fingerprint=fingerprint_file(request.path),
        )
