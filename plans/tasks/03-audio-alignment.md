# Task 03 — Audio Alignment Engine

## Objective

For each video-enabled master segment, locate it inside its explicitly eligible camera-audio occurrence, choose an unambiguous candidate, and return source-time boundaries plus evidence strong enough to decide whether timeline construction is safe. Audio-only segments bypass this subsystem entirely.

## Dependencies and ownership

- Depends on: Tasks 01 and 02.
- Owns: `alignment/models.py`, `alignment/features.py`, `alignment/dtw.py`, `alignment/matcher.py`, and all alignment tests/fixtures.
- Does not convert to Resolve frames or call Resolve.
- Use `$align-audio`, `$develop-python`, and `$test-multi-cam-sync`.

## Public interfaces

Implement typed equivalents of:

```python
class AlignmentSettings: ...


class MatchDiagnostics: ...


class CandidateMatch: ...


class SegmentMatch: ...  # matched/unsafe, source ID, absolute source in/out


class SegmentMatcher:
    def match(segment, master_audio, candidates, settings) -> SegmentMatch: ...
```

Default settings are fixed and serialized into every result: 22,050 Hz, 80 MFCCs, hop 256, cosine distance, asymmetric step pattern, open begin/end, first/second deltas, per-feature z-score epsilon, edge guard, and confidence tolerances from the specification.

## Algorithm

1. Slice the exact master segment. Exclude `min(150 ms, 10% of segment duration)` from each scoring edge; retain the excluded duration so the final mapping extrapolates to the real cuts. Reject a scored interval too short for librosa's MFCC/delta window requirements.
2. Compute MFCCs, first and second deltas, concatenate them on the feature axis, and z-score each feature with an epsilon for silent dimensions. This deliberately follows Elidan Take Picker's proven `warping_path.py` approach.
3. Use `dtw-python` subsequence alignment with the master feature frames as query and a bounded source occurrence as reference, cosine distance, asymmetric steps, and open begin/end. Convert the returned monotonic path to seconds with its actual analysis sample rate/hop and then to absolute physical-source seconds using `AnalysisAudio.origin_seconds`.
4. Fit `source_time = slope * master_local_time + intercept` to interior path points using an iterative median-absolute-deviation outlier rejection. Require positive slope and monotonic boundaries. Compute source in/out at the exact, unguarded master edges.
5. Record normalized path cost, scored-frame coverage, path endpoints, slope, predicted unity-speed end drift, outlier fraction, and stability under a one-hop inward/outward guard perturbation.
6. Require at least one configured candidate as an API precondition. Evaluate every configured candidate for the enabled take, reject invalid candidates, sort valid candidates by normalized cost then stable source ID, and choose the best. Mark it unsafe if no candidate produces a valid match or any blocker in `specifications.md` applies, including a runner-up within 5%.
7. For `manual_offset_seconds`, skip feature/DTW work and return `source = master absolute time + offset`, constrained to occurrence bounds. Mark the result accepted with `method = "manual"`, a mandatory warning, no invented DTW cost, and the same drift/duration checks.
8. Return diagnostics even for failure. Do not create a `not_provided` result here: orchestration assigns that status without decoding or DTW when the take has no configured source. Do not silently widen user bounds, swap candidates based on filenames, or accept the least-bad match.

## Tests

Generate deterministic audio with seeded NumPy code. Include tonal/chord/chirp and transient structure rather than pure sine waves alone. Test:

- known leading offsets under gain, EQ-like filtering, channel mix, background noise, leading silence, and resampling;
- correct absolute coordinates for a cropped occurrence;
- two logical occurrences in one file, with the configured bound selecting A versus B;
- repeated musical phrases producing a close runner-up and therefore low confidence;
- a clearly winning candidate, deterministic tie ordering, and the 5% ambiguity boundary;
- edge crossfade contamination and stability perturbation;
- excess clock drift, incomplete path coverage, path out of bounds, silence, very short input, NaN rejection, and rejection of an accidental empty-candidate call without running feature extraction;
- manual offsets inside/outside bounds and proof that DTW is not called for an override;
- exact settings serialization and stable diagnostics;
- accepted boundary error no greater than two frames at representative 23.976, 24, 25, and 30 fps tolerances.

Add characterization tests against a small derived fixture or invariants from Elidan Take Picker; do not copy private media into the repository. An opt-in benchmark may read user media but cannot be part of ordinary pytest.

## Acceptance criteria

- All accepted synthetic matches meet the two-frame boundary tolerance.
- Ambiguous, unstable, under-covered, drifting, out-of-range, or undersized requested matches are rejected with a specific blocker.
- A missing take source is not an alignment failure and causes no decode/feature/DTW call.
- Results are deterministic across runs and do not depend on filesystem names.
- Ruff, ty, and focused tests pass within a practical pre-commit runtime; mark only genuinely expensive parameter sweeps as slow and keep a representative fast case.

## Handoff

Publish coordinate orientation, settings defaults, normalized-cost definition, diagnostic/blocker enum, and whether each `SegmentMatch` is safe for planning. Task 04 must never inspect raw DTW objects.
