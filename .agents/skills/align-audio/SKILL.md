---
name: align-audio
description: Implement, diagnose, test, or review master-to-camera audio matching for multi-cam-sync, including partial video-take coverage, librosa MFCC/delta features, open-ended asymmetric DTW, bounded take occurrences, coordinate mapping, confidence blockers, caching inputs, drift, ambiguity, and manual offsets. Use whenever a task touches analysis audio, omitted versus supplied takes, warping paths, segment matching, source in/out times, or synchronization accuracy.
---

# Align Audio

## Ground the work

Read the audio sections of `specifications.md` and the assigned task. For proven behavior, inspect these files rather than relying on memory:

- `/home/itaielidan/PycharmProjects/elidan-take-picker-workspace/main/elidan_take_picker/warping_path.py`
- `/home/itaielidan/PycharmProjects/elidan-take-picker-workspace/main/elidan_take_picker/waveform.py`
- `/home/itaielidan/PycharmProjects/elidan-take-picker-workspace/main/elidan_take_picker/measure.py`
- the cached warping-path handling in that project's `main.py` and time interpolation in `server.py`.

Adapt the small techniques behind project-owned interfaces. Do not add Elidan Take Picker or `.etp` files as runtime dependencies.

## Preserve coordinate conventions

- Treat cut timestamps as Decimal seconds from master start.
- Treat cropped `AnalysisAudio` samples as local arrays carrying an absolute `origin_seconds` in the physical source.
- Represent a warping path explicitly as master-local time mapped to source-absolute time; name columns and assert monotonicity.
- Return source boundaries in seconds. Leave all Resolve frame conversion to the planning layer.

## Follow the matching pipeline

Apply this pipeline only when the segment's normalized take has one or more configured sources. For an omitted take, assign `video_status = "not_provided"` in orchestration and perform no media decode, feature extraction, DTW, or confidence scoring. Treat it as a valid intentional audio-only segment, not as an unsafe match.

1. Decode mono analysis audio at 22,050 Hz.
2. Guard up to 150 ms or 10% at each master edit edge to reduce crossfade contamination.
3. Compute 80 MFCCs at hop 256, append first/second deltas, and z-score each feature dimension with an epsilon.
4. Run cosine-distance `dtw-python` with the asymmetric step pattern and open begin/end, using the master segment as query and the explicitly bounded source occurrence as reference.
5. Convert the path using the actual sample rate/hop, fit a robust affine mapping to interior points, and extrapolate to the exact unguarded master cuts.
6. Compare every eligible candidate by normalized path cost and stable ID. Never infer take identity from a filename or widen supplied bounds silently.
7. Record coverage, cost, runner-up margin, slope/drift, outliers, edge stability, bounds, settings, cache/manual status, and blocker codes.
8. Use the match only as a locator/confidence check. Plan unity-speed video; block excess drift instead of implementing hidden retiming.

## Reject unsafe matches

For a supplied take, mark a result unsafe when path coverage is below 95%, mapped time leaves its occurrence, the runner-up is within 5%, an edge perturbation moves a boundary over two timeline frames, predicted unity-speed drift exceeds two frames, or the segment cannot produce valid feature windows. Return diagnostics even on rejection. Never convert an unsafe supplied match into `not_provided`.

Honor `manual_offset_seconds` without calling DTW, validate the resulting boundaries, and label it visibly as a manual method.

## Test numerically

Use seeded, generated music-like fixtures with multiple tones/chords/transients. Exercise omitted, partially supplied, and fully supplied take sets; prove omitted segments perform no alignment work; then exercise gain, filtering, noise, channel mixing, leading silence, resampling, crossfades, repeated phrases, multiple bounded occurrences, ambiguity, crop origins, short/silent input, clock drift, and manual overrides. Assert accepted ground-truth boundaries within two frames at representative integer and fractional rates. Keep ordinary tests offline and deterministic.

Run focused pytest plus Ruff and ty through `uv`, then report coordinate orientation, settings, accuracy, unsafe cases, and any opt-in private-media benchmark separately.
