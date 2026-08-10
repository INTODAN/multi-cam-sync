from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from multi_cam_sync.media import (
    AudioRequest,
    CommandResult,
    FFmpegMediaReader,
    InvalidMediaBoundsError,
    MediaDecodeError,
    MediaExecutableNotFoundError,
    MediaProbeError,
    NoAudioStreamError,
    ffmpeg_arguments,
    normalize_samples,
    parse_ffprobe_json,
    probe_media,
)
from multi_cam_sync.media.decode import validate_audio_request


def ffprobe_payload(*, duration: str = "2.500", with_audio: bool = True) -> bytes:
    streams: list[dict[str, object]] = [
        {
            "index": 0,
            "codec_type": "video",
            "codec_name": "h264",
            "avg_frame_rate": "24000/1001",
            "r_frame_rate": "24/1",
        }
    ]
    if with_audio:
        streams.append(
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "pcm_s16le",
                "sample_rate": "48000",
                "channels": 2,
                "duration": duration,
            }
        )
    return json.dumps({"streams": streams, "format": {"duration": duration}}).encode()


class FakeRunner:
    def __init__(self, result: CommandResult | Exception) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def run(self, arguments: Sequence[str]) -> CommandResult:
        self.calls.append(list(arguments))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class DecodeRunner:
    def __init__(self, *, fail_ffmpeg_with: Exception | None = None) -> None:
        self.fail_ffmpeg_with = fail_ffmpeg_with
        self.calls: list[list[str]] = []

    def run(self, arguments: Sequence[str]) -> CommandResult:
        call = list(arguments)
        self.calls.append(call)
        if call[0] == "ffprobe":
            return CommandResult(0, ffprobe_payload(duration="2.0"), b"")
        if self.fail_ffmpeg_with is not None:
            raise self.fail_ffmpeg_with
        samples = np.linspace(-0.5, 0.5, 22_050, dtype=np.float32)
        sf.write(Path(call[-1]), samples, 22_050, subtype="FLOAT")
        return CommandResult(0, b"", b"")


def test_parse_probe_preserves_decimal_duration_and_rational_rate(tmp_path: Path) -> None:
    path = tmp_path / "camera clip.mov"
    probe = parse_ffprobe_json(path, ffprobe_payload(duration="12.3456789"))

    assert probe.duration_seconds == Decimal("12.3456789")
    assert probe.audio_stream_index == 0
    assert probe.audio_streams[0].index == 2
    assert probe.audio_streams[0].sample_rate == 48_000
    assert probe.video_frame_rate == Fraction(24_000, 1_001)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        (b"not json", MediaProbeError),
        (json.dumps({"streams": []}).encode(), NoAudioStreamError),
        (ffprobe_payload(duration="N/A"), MediaProbeError),
    ],
)
def test_parse_probe_rejects_unsupported_metadata(
    tmp_path: Path, payload: bytes, error: type[Exception]
) -> None:
    with pytest.raises(error):
        parse_ffprobe_json(tmp_path / "bad.mov", payload)


def test_probe_uses_argument_list_and_maps_process_failures(tmp_path: Path) -> None:
    path = tmp_path / "a path with spaces.mov"
    runner = FakeRunner(CommandResult(7, b"", b"unsafe\x00 detail"))
    with pytest.raises(MediaProbeError, match="unsafe detail"):
        probe_media(path, runner=runner)
    assert runner.calls == [
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    ]

    missing = FakeRunner(FileNotFoundError())
    with pytest.raises(MediaExecutableNotFoundError):
        probe_media(path, runner=missing)


def test_ffmpeg_arguments_keep_paths_stream_and_bounds_separate(tmp_path: Path) -> None:
    request = AudioRequest(
        tmp_path / "camera audio ü.mov",
        audio_stream_index=2,
        source_start_seconds=Decimal("1.25"),
        source_end_seconds=Decimal("7.50"),
    )
    output = tmp_path / "analysis output.wav"

    arguments = ffmpeg_arguments(request, output)

    assert arguments[arguments.index("-i") + 1] == str(request.path)
    assert arguments[arguments.index("-map") + 1] == "0:a:2"
    assert arguments[arguments.index("-ss") + 1] == "1.25"
    assert arguments[arguments.index("-to") + 1] == "7.50"
    assert arguments[-1] == str(output)


def test_normalize_samples_converts_stereo_and_rejects_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "audio.wav"
    stereo = np.array([[1.0, -1.0], [0.5, 0.25]], dtype=np.float64)
    result = normalize_samples(stereo, path=path)
    assert result.dtype == np.float32
    assert result.flags.c_contiguous
    np.testing.assert_allclose(result, [0.0, 0.375])

    with pytest.raises(MediaDecodeError, match="NaN"):
        normalize_samples(np.array([0.0, np.nan]), path=path)


def test_direct_wav_decode_resamples_mixes_channels_and_preserves_crop_origin(
    tmp_path: Path,
) -> None:
    path = tmp_path / "tiny stereo.wav"
    native_rate = 8_000
    time = np.arange(native_rate * 2, dtype=np.float32) / native_rate
    stereo = np.column_stack((np.sin(2 * np.pi * 220 * time), np.sin(2 * np.pi * 330 * time)))
    sf.write(path, stereo, native_rate, subtype="FLOAT")
    runner = FakeRunner(CommandResult(0, ffprobe_payload(duration="2.0"), b""))
    reader = FFmpegMediaReader(runner=runner)
    request = AudioRequest(
        path,
        source_start_seconds=Decimal("0.5"),
        source_end_seconds=Decimal("1.5"),
        sample_rate=4_000,
    )

    audio = reader.load_audio(request)

    assert audio.origin_seconds == Decimal("0.5")
    assert audio.sample_rate == 4_000
    assert audio.samples.dtype == np.float32
    assert audio.samples.ndim == 1
    assert abs(audio.samples.size - 4_000) <= 1
    assert runner.calls[0][0] == "ffprobe"
    assert len(runner.calls) == 1


def test_unsupported_direct_input_falls_back_to_bounded_ffmpeg(tmp_path: Path) -> None:
    path = tmp_path / "camera clip.mov"
    path.write_bytes(b"not directly readable")
    runner = DecodeRunner()
    request = AudioRequest(
        path,
        source_start_seconds=Decimal("0.25"),
        source_end_seconds=Decimal("1.25"),
    )

    audio = FFmpegMediaReader(runner=runner).load_audio(request)

    assert audio.origin_seconds == Decimal("0.25")
    assert audio.samples.size == 22_050
    ffmpeg_call = runner.calls[1]
    assert ffmpeg_call[0] == "ffmpeg"
    assert ffmpeg_call[ffmpeg_call.index("-ss") + 1] == "0.25"
    assert ffmpeg_call[ffmpeg_call.index("-to") + 1] == "1.25"
    assert ffmpeg_call[ffmpeg_call.index("-map") + 1] == "0:a:0"


def test_missing_ffmpeg_is_a_typed_decode_error(tmp_path: Path) -> None:
    path = tmp_path / "camera.mov"
    path.write_bytes(b"not audio")
    runner = DecodeRunner(fail_ffmpeg_with=FileNotFoundError())

    with pytest.raises(MediaExecutableNotFoundError, match="ffmpeg"):
        FFmpegMediaReader(runner=runner).load_audio(AudioRequest(path))


def test_bounds_allow_one_output_sample_rounding_but_reject_real_overflow(tmp_path: Path) -> None:
    probe = parse_ffprobe_json(tmp_path / "a.wav", ffprobe_payload(duration="2"))
    within_rounding = AudioRequest(
        probe.path,
        source_end_seconds=Decimal(2) + Decimal(1) / Decimal(22_050),
    )
    assert validate_audio_request(within_rounding, probe) == Decimal(2)

    overflow = AudioRequest(probe.path, source_end_seconds=Decimal("2.001"))
    with pytest.raises(InvalidMediaBoundsError, match="exceeds"):
        validate_audio_request(overflow, probe)

    missing_stream = AudioRequest(probe.path, audio_stream_index=1)
    with pytest.raises(InvalidMediaBoundsError, match="does not exist"):
        validate_audio_request(missing_stream, probe)
