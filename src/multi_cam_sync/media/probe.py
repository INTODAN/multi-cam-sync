"""Validated ffprobe JSON access."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from pathlib import Path
from typing import Protocol

from .models import (
    MediaExecutableNotFoundError,
    MediaProbe,
    MediaProbeError,
    MediaStream,
    NoAudioStreamError,
)


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandRunner(Protocol):
    def run(self, arguments: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    """Shell-free production subprocess boundary."""

    def run(self, arguments: Sequence[str]) -> CommandResult:
        result = subprocess.run(arguments, capture_output=True, check=False)
        return CommandResult(result.returncode, result.stdout, result.stderr)


def _safe_stderr(stderr: bytes, *, limit: int = 800) -> str:
    text = stderr.decode(errors="replace").replace("\x00", "").strip()
    return text[:limit] if text else "no diagnostic output"


def _decimal(value: object) -> Decimal | None:
    if value in (None, "", "N/A"):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _fraction(value: object) -> Fraction | None:
    if value in (None, "", "N/A", "0/0"):
        return None
    try:
        result = Fraction(str(value))
    except (ValueError, ZeroDivisionError):
        return None
    return result if result > 0 else None


def parse_ffprobe_json(path: Path, output: bytes) -> MediaProbe:
    """Parse the small, validated ffprobe schema used by this application."""
    try:
        root = json.loads(output)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MediaProbeError("ffprobe returned malformed JSON", path=path) from exc
    if not isinstance(root, dict) or not isinstance(root.get("streams"), list):
        raise MediaProbeError("ffprobe JSON has no streams array", path=path)

    streams: list[MediaStream] = []
    for raw in root["streams"]:
        if (
            not isinstance(raw, dict)
            or not isinstance(raw.get("index"), int)
            or not isinstance(raw.get("codec_type"), str)
        ):
            raise MediaProbeError("ffprobe returned an invalid stream entry", path=path)
        stream = MediaStream(
            index=raw["index"],
            codec_type=raw["codec_type"],
            codec_name=raw.get("codec_name") if isinstance(raw.get("codec_name"), str) else None,
            duration_seconds=_decimal(raw.get("duration")),
            sample_rate=int(raw["sample_rate"])
            if isinstance(raw.get("sample_rate"), str) and raw["sample_rate"].isdigit()
            else None,
            channels=raw.get("channels") if isinstance(raw.get("channels"), int) else None,
            average_frame_rate=_fraction(raw.get("avg_frame_rate")),
            real_frame_rate=_fraction(raw.get("r_frame_rate")),
        )
        streams.append(stream)

    audio_streams = [stream for stream in streams if stream.codec_type == "audio"]
    if not audio_streams:
        raise NoAudioStreamError("media has no audio stream", path=path)
    if any(
        stream.sample_rate is None
        or stream.sample_rate <= 0
        or stream.channels is None
        or stream.channels <= 0
        for stream in audio_streams
    ):
        raise MediaProbeError("ffprobe returned invalid native audio properties", path=path)

    raw_format = root.get("format")
    format_duration = _decimal(raw_format.get("duration")) if isinstance(raw_format, dict) else None
    durations = [
        stream.duration_seconds for stream in streams if stream.duration_seconds is not None
    ]
    duration = (
        format_duration if format_duration is not None else (max(durations) if durations else None)
    )
    if duration is None or duration <= 0:
        raise MediaProbeError("ffprobe returned no positive media duration", path=path)

    video_rate = next(
        (
            stream.average_frame_rate or stream.real_frame_rate
            for stream in streams
            if stream.codec_type == "video"
            and (stream.average_frame_rate or stream.real_frame_rate)
        ),
        None,
    )
    return MediaProbe(
        path=path,
        duration_seconds=duration,
        streams=tuple(streams),
        audio_stream_index=0,
        video_frame_rate=video_rate,
    )


def probe_media(
    path: Path, *, runner: CommandRunner | None = None, executable: str = "ffprobe"
) -> MediaProbe:
    """Probe a media file without ever invoking a shell."""
    arguments = [
        executable,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    try:
        result = (runner or SubprocessRunner()).run(arguments)
    except FileNotFoundError as exc:
        raise MediaExecutableNotFoundError(
            f"required executable not found ({executable})", path=path
        ) from exc
    except OSError as exc:
        raise MediaProbeError("could not start ffprobe", path=path) from exc
    if result.returncode != 0:
        raise MediaProbeError(f"ffprobe failed: {_safe_stderr(result.stderr)}", path=path)
    return parse_ffprobe_json(path, result.stdout)
