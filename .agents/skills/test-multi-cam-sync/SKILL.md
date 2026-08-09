---
name: test-multi-cam-sync
description: Design, implement, run, or review tests for any multi-cam-sync task, including partial video-take coverage, intentional video gaps, parsers, Decimal/frame math, generated audio, alignment accuracy, cache/subprocess behavior, deterministic reports, strict DaVinci Resolve fakes, CLI side effects, rollback, and opt-in live acceptance. Use whenever production behavior changes or a task's acceptance criteria must be verified.
---

# Test Multi-Cam Sync

## Start with the task's risks

Read the assigned task's Tests and Acceptance criteria plus the cross-project requirements in `specifications.md`. Add tests in the same change as production code. Map each documented validation rule, edge case, and side-effect boundary to at least one assertion; avoid tests that merely repeat implementation structure.

## Choose the correct layer

- **Pure unit tests:** configuration/cut parsing, normalization, Decimal timestamps, frame conversion, colors, plan invariants, and report canonicalization.
- **Numerical tests:** seeded generated music-like signals with known source/master coordinates and explicit frame-accuracy assertions.
- **Boundary tests:** injected subprocess runners, temporary caches/files, corrupt data, atomic writes, and strict Resolve fakes.
- **Offline system tests:** real parsers/media/alignment/planning/reporting with a fake Resolve gateway, including zero/partial/full video-source configurations.
- **Opt-in acceptance:** real Resolve or private Arabesques media only under their registered pytest markers and explicit environment guards.

Ordinary tests must not require network access, private media, ffmpeg, Resolve, a GUI, or machine-specific paths. Use a skipped optional integration case for installed executables rather than weakening fake coverage.

## Build deterministic fixtures

- Seed every random generator and avoid wall-clock IDs/times in canonical assertions.
- Generate files under `tmp_path`; do not write to the repository or user cache.
- Build audio from chords/tones/chirps/transients, then vary gain, EQ-like filtering, noise, silence, channels, sampling, crossfades, repetition, bounded occurrences, and controlled drift.
- State the exact coordinate convention and ground truth. Assert every accepted boundary within two frames at relevant rates.
- For dynamic APIs, make fakes fail on unplanned calls and assert both arguments and ordering.

## Prove safety, not only success

Assert that validate/analyze and every preflight rejection make zero Resolve mutation calls. Cover stale report dimensions independently. Force failures after each timeline creation step and prove rollback targets only the new timeline; also cover rollback failure. Test all false/`None`/exception returns rather than assuming Resolve raises.

Test the distinction between `not_provided` and `unsafe`: omitted takes must cause no decode/matcher work and must remain buildable; supplied takes must produce video for every occurrence or block the build. Prove continuous master audio, exact matched video ranges, explicit intentional video gaps, no filler/placeholder items, and no undeclared video gap or overlap.

Test cache hits and misses against identical canonical output. Test paths with spaces, Unicode take names, fractional rates, multiple candidates, shared physical sources, manual offsets, corrupt caches, malformed third-party output, and more than 16 takes where the task touches them.

## Run and report gates

Iterate with the focused test file, then run:

```bash
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
```

Use `uv run pre-commit run --all-files` for final/shared integration. Report test names or counts, numerical tolerances, commands/results, and any opt-in live/private test that was not run. Never describe an unavailable live acceptance check as passed.
