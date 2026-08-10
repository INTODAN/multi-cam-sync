"""Deterministic generated-media fixtures for offline system verification."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

import numpy as np
import soundfile as sf

from multi_cam_sync.media import CommandResult

SAMPLE_RATE = 22_050
SEGMENT_SECONDS = Decimal("1.5")
TAKES = (
    "Take 1 \N{EN DASH} \N{GREEK SMALL LETTER ALPHA}",
    "Take 2",
    "Take 3",
    "Take 4",
    "Take 5",
    "Take 6",
    "Take 7",
    "Take 8 \N{EN DASH} Étude",
    "Take 9",
)
SEGMENT_TAKES = (*TAKES, TAKES[0])
TAKE_1_SOURCE_OFFSET = Decimal("1")
TAKE_8_SOURCE_OFFSET = Decimal("17")


@dataclass(frozen=True, slots=True)
class GeneratedPerformance:
    """Paths and alignment truth for one ten-segment/nine-take project."""

    config_path: Path
    cuts_path: Path
    master_path: Path
    shared_source_path: Path
    take_1: str
    take_8: str
    take_1_source_offset: Decimal
    take_8_source_offset: Decimal


class SoundFileProbeRunner:
    """Strict ffprobe stand-in deriving metadata from the generated WAV itself."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: Sequence[str]) -> CommandResult:
        call = tuple(arguments)
        self.calls.append(call)
        if len(call) != 8 or call[1:7] != (
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
        ):
            raise AssertionError(f"unexpected media command: {call!r}")
        if call[0] != "test-ffprobe":
            raise AssertionError(f"unexpected ffprobe invocation: {call!r}")
        path = Path(call[7])
        with sf.SoundFile(path) as stream:
            frames = int(stream.frames)
            sample_rate = int(stream.samplerate)
            channels = int(stream.channels)
        duration = Decimal(frames) / Decimal(sample_rate)
        payload = {
            "streams": [
                {
                    "index": 0,
                    "codec_type": "audio",
                    "codec_name": "pcm_f32le",
                    "duration": str(duration),
                    "sample_rate": str(sample_rate),
                    "channels": channels,
                }
            ],
            "format": {"duration": str(duration)},
        }
        return CommandResult(0, json.dumps(payload).encode("utf-8"), b"")


def _score(seconds: Decimal) -> np.ndarray:
    """Generate a non-repeating, music-like full-performance reference."""
    sample_count = int(seconds * SAMPLE_RATE)
    time = np.arange(sample_count, dtype=np.float64) / SAMPLE_RATE
    phase = 2 * np.pi * (105 * time + 19 * time**2 + 2.7 * np.sin(2 * np.pi * 0.11 * time))
    envelope = 0.62 + 0.18 * np.sin(2 * np.pi * 0.31 * time)
    signal = envelope * (
        0.34 * np.sin(phase)
        + 0.23 * np.sin(1.498 * phase + 0.31)
        + 0.15 * np.sin(2.013 * phase + 0.77)
    )
    rng = np.random.default_rng(310_801)
    for event in np.arange(0.23, float(seconds), 0.29):
        center = int(event * SAMPLE_RATE)
        width = 96 + int(rng.integers(0, 96))
        end = min(sample_count, center + width)
        signal[center:end] += (
            rng.uniform(0.2, 0.55)
            * np.hanning((end - center) * 2)[: end - center]
            * rng.choice((-1, 1))
        )
    return np.ascontiguousarray(signal, dtype=np.float32)


def _take_variants(score: np.ndarray) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for index, take in enumerate(TAKES):
        rng = np.random.default_rng(9_100 + index)
        kernel = np.array([0.78 + index * 0.008, 0.16 - index * 0.004, 0.04], dtype=np.float32)
        filtered = np.convolve(score, kernel, mode="same")
        noise = rng.normal(0, 0.0015 + index * 0.0001, score.size).astype(np.float32)
        result[take] = np.ascontiguousarray((0.78 + index * 0.012) * filtered + noise)
    return result


def _stereo_occurrence(mono: np.ndarray) -> np.ndarray:
    delayed = np.concatenate((np.zeros(3, dtype=np.float32), mono[:-3]))
    return np.ascontiguousarray(np.column_stack((mono * 1.04, delayed * 0.96)))


def _composite_master(variants: dict[str, np.ndarray]) -> np.ndarray:
    segment_frames = int(SEGMENT_SECONDS * SAMPLE_RATE)
    master = np.empty(segment_frames * len(SEGMENT_TAKES), dtype=np.float32)
    for index, take in enumerate(SEGMENT_TAKES):
        start = index * segment_frames
        end = start + segment_frames
        master[start:end] = variants[take][start:end]

    # One 100 ms equal-time crossfade straddles the cut into the supplied Take 8.
    incoming_index = SEGMENT_TAKES.index(TAKES[7])
    cut = incoming_index * segment_frames
    half_width = int(Decimal("0.100") * SAMPLE_RATE)
    start = cut - half_width
    end = cut + half_width
    weights = np.linspace(0, 1, end - start, dtype=np.float32)
    outgoing = variants[SEGMENT_TAKES[incoming_index - 1]][start:end]
    incoming = variants[TAKES[7]][start:end]
    master[start:end] = outgoing * (1 - weights) + incoming * weights
    return np.ascontiguousarray(master)


def _write_cut_list(path: Path) -> None:
    blocks: list[str] = []
    for index, (outgoing, incoming) in enumerate(pairwise(SEGMENT_TAKES), start=1):
        timestamp = SEGMENT_SECONDS * index
        hours, remainder = divmod(timestamp, Decimal(3600))
        minutes, seconds = divmod(remainder, Decimal(60))
        blocks.append(
            f"Out: {outgoing}\nIn:  {incoming}\n{int(hours):02d}:{int(minutes):02d}:{seconds:06.3f}"
        )
    path.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")


def generate_performance(root: Path) -> GeneratedPerformance:
    """Create generated WAV, cut, and partial-video TOML inputs under ``root``."""
    media_dir = root / "Média files with spaces"
    media_dir.mkdir(parents=True)
    duration = SEGMENT_SECONDS * len(SEGMENT_TAKES)
    score = _score(duration)
    variants = _take_variants(score)

    take_1_stereo = _stereo_occurrence(variants[TAKES[0]])
    take_8_stereo = _stereo_occurrence(variants[TAKES[7]])
    source_frames = int(Decimal(33) * SAMPLE_RATE)
    shared_source = np.zeros((source_frames, 2), dtype=np.float32)
    first_start = int(TAKE_1_SOURCE_OFFSET * SAMPLE_RATE)
    second_start = int(TAKE_8_SOURCE_OFFSET * SAMPLE_RATE)
    shared_source[first_start : first_start + take_1_stereo.shape[0]] = take_1_stereo
    shared_source[second_start : second_start + take_8_stereo.shape[0]] = take_8_stereo

    # Match the mono channel mix used by the production decoder in supplied regions.
    variants[TAKES[0]] = np.ascontiguousarray(take_1_stereo.mean(axis=1), dtype=np.float32)
    variants[TAKES[7]] = np.ascontiguousarray(take_8_stereo.mean(axis=1), dtype=np.float32)
    master = _composite_master(variants)

    master_path = media_dir / "final master \N{GREEK SMALL LETTER ALPHA}.wav"
    source_path = media_dir / "shared camera takes.wav"
    sf.write(master_path, master, SAMPLE_RATE, subtype="FLOAT")
    sf.write(source_path, shared_source, SAMPLE_RATE, subtype="FLOAT")

    cuts_path = root / "nine takes cuts.txt"
    _write_cut_list(cuts_path)
    config_path = root / "partial video project.toml"
    config_path.write_text(
        f'''schema_version = 1

[project]
timeline_name = "Offline partial — synced"
cuts_file = "{cuts_path.name}"

[master]
media_pool_folder = "Masters"
media_pool_name = "Master.wav"
audio_path = "{master_path.relative_to(root)}"

[[sources]]
id = "take-1-occurrence"
take = "{TAKES[0]}"
media_pool_folder = "Media/Multicam"
media_pool_name = "Take 1 multicam"
audio_reference_path = "{source_path.relative_to(root)}"
source_start = "00:00:00.500"
source_end = "00:00:16.500"

[[sources]]
id = "take-8-occurrence"
take = "{TAKES[7]}"
media_pool_folder = "Media/Multicam"
media_pool_name = "Take 1 multicam"
audio_reference_path = "{source_path.relative_to(root)}"
source_start = "00:00:16.500"
source_end = "00:00:32.500"
''',
        encoding="utf-8",
    )
    return GeneratedPerformance(
        config_path=config_path,
        cuts_path=cuts_path,
        master_path=master_path,
        shared_source_path=source_path,
        take_1=TAKES[0],
        take_8=TAKES[7],
        take_1_source_offset=TAKE_1_SOURCE_OFFSET,
        take_8_source_offset=TAKE_8_SOURCE_OFFSET,
    )
