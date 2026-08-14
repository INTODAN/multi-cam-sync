# Task 02 — Media Probing, Audio Decoding, Fingerprints, and Cache

## Objective

Provide deterministic analysis audio and metadata for the master and source occurrences. Hide ffmpeg/librosa/filesystem details behind typed interfaces and make repeat analysis fast without trusting stale or corrupt cache entries.

## Dependencies and ownership

- Depends on: Tasks 00 and 01.
- Owns: `media/models.py`, `media/probe.py`, `media/decode.py`, `media/fingerprint.py`, `media/cache.py`, and their tests.
- Does not discover Resolve Media Pool items; Task 05 supplies resolved physical paths/IDs.
- Use `$develop-python`, `$align-audio`, and `$test-multi-cam-sync`.

## Public interfaces

Provide typed equivalents of:

```python
class MediaProbe: ...  # path, duration, streams, native rate/channels, optional video fps


class AudioRequest: ...  # path, audio stream, bounds, analysis rate/channels


class AnalysisAudio: ...  # float32 mono samples, rate, absolute origin, duration, fingerprint


class ContentFingerprint: ...


class MediaReader(Protocol):
    def probe(self, path: Path) -> MediaProbe: ...
    def load_audio(self, request: AudioRequest) -> AnalysisAudio: ...


class AnalysisCache: ...
```

`AnalysisAudio.origin_seconds` is the absolute start of the cropped occurrence within the physical source. This prevents Task 03 from returning crop-relative positions by mistake.

## Implementation details

1. Invoke `ffprobe` with JSON output through an injectable subprocess runner. Validate exit status and schema; choose audio stream 0 by default and report when no audio exists. Parse duration/sample rate/frame-rate strings without lossy early rounding.
2. Decode directly readable audio through `soundfile`/librosa where reliable. Otherwise run `ffmpeg` to an analysis WAV with explicit stream mapping, mono channel count, 22,050 Hz, and configured source bounds. Never build a shell command string; pass an argument list.
3. Normalize decoded sample shape to one-dimensional contiguous `float32`, reject empty/NaN/Inf data, and preserve the origin/duration metadata. Do not loudness-normalize samples here; feature normalization belongs to Task 03.
4. Validate source bounds against probed duration before decoding. Permit `source_end` absent and clamp only the last sub-sample rounding difference; larger overflow is an error. Probe each additional source reference up front and require its whole-file duration to equal the primary reference exactly.
5. Fingerprint every configured primary and additional reference by canonical path, size, modification nanoseconds, and SHA-256 of file size plus first/last 64 KiB. Include stream, crop bounds, output rate, decoder settings, and cache schema/tool version in derived keys.
6. Store cache beneath the `platformdirs` user cache directory, never in the repository. Write metadata and arrays to a temporary sibling, fsync where supported, then `os.replace`. Use no pickle. Validate schema, key, dtype, shape, finite values, and checksum when loading; delete/ignore only the bad entry and recompute.
7. Concurrent processes may compute the same value; the final atomic replace must remain valid. A cache miss or corruption is informational, not fatal when the source is readable.
8. Convert missing executables, unreadable files, probe failures, unsupported media, no-audio streams, invalid bounds, and decode failures into typed media errors containing the path and safe stderr summary.

## Tests

Add generated tiny WAV fixtures and an injected fake subprocess runner to cover:

- mono/stereo input, resampling, crop origin, dtype/shape, silence, and invalid numeric samples;
- ffprobe JSON parsing, rational video rates, stream selection, missing audio/duration, malformed JSON, nonzero status, and missing executable;
- exact ffmpeg argument construction for paths containing spaces and stream/bound settings;
- content fingerprint stability and invalidation after size/content/mtime changes;
- cache hit/miss, setting-key separation, atomic replacement, corrupt JSON/array/checksum, old schema, truncated file, and two writers;
- a source bound just inside duration and a real overflow;
- assurance that tests and normal decode never write into the repository.

Mark no test live; ffmpeg availability may have one separately skipped integration check, but core coverage must use fakes and generated WAV.

## Acceptance criteria

- The same request and unchanged media return identical samples/metadata and a cache hit.
- Any relevant content, crop, stream, analysis setting, or cache-version change causes a miss.
- All errors are typed/actionable and no subprocess is invoked through a shell.
- Ruff, ty, and focused tests pass.

## Handoff

Document the `AnalysisAudio` coordinate convention, fingerprint/cache schema versions, decoder executable discovery, and the exceptions Task 06 should map to user exit codes.
