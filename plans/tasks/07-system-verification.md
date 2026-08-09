# Task 07 — System Verification, Documentation, and Handoff

## Objective

Reconcile all modules, prove the complete safe workflow, document setup/use/recovery, and run the final automated and opt-in acceptance gates. This is integration and hardening, not a place to redesign stable task contracts.

## Dependencies and ownership

- Depends on: Tasks 00–06.
- Owns: cross-module tests, generated synthetic fixture helpers, opt-in test/runbook assets, `README.md`, sample version-1 TOML, and final configuration reconciliation.
- May adjust shared tooling only to resolve an observed final-gate issue and must explain the change.
- Use all four repository skills.

## Integration work

1. Add a reusable deterministic synthetic-performance generator that produces master composites and source occurrences with seeded gain, filtering, noise, silence, offsets, repeated phrases, and controlled clock drift. Generate files under pytest temporary directories; commit no bulky media.
2. Add an offline system test that uses real parsers, media readers for generated WAV, alignment, plan creation, report round-trip, and a strict fake Resolve gateway. It must cover at least nine logical takes with video supplied for only one or two takes, every repeated segment of a supplied take receiving video, intentional gaps for the other takes, a physical file containing two bounded logical occurrences, a return to an earlier take, and one master edge crossfade.
3. Add failure-path system tests for ambiguous audio on a supplied take, proof that an omitted take is not analyzed and remains buildable, changed media after analysis, changed Resolve snapshot, target timeline collision, mid-build API failure with successful rollback, and failed rollback.
4. Add an opt-in `resolve_live` smoke test/runbook. It requires an explicitly named disposable project/config through `MULTI_CAM_SYNC_LIVE_CONFIG`, refuses to run without an additional `MULTI_CAM_SYNC_ALLOW_MUTATION=1`, uses a unique target timeline, and verifies/then leaves the new timeline for human inspection. It must never run in pre-commit/default pytest.
5. Add an opt-in `arabesques_acceptance` command/runbook using the checked-in cut list and a user-local TOML (never committed with private paths). It runs validate, analyze, report review, build, and the human checklist in `HUMAN_GUIDE.md`.
6. Replace the minimal README with setup prerequisites (Resolve external scripting, Python/uv, ffmpeg/ffprobe), configuration example, commands, report/confidence explanation, recovery, development commands, and links to specifications/plan/human guide.
7. Add a sanitized `examples/project.example.toml` showing a partial source list where only Take 8 A/B have video, share a multicam item and bounded reference file, and every other take in the example cuts remains audio-only. It must parse in tests after temporary paths/media selectors are substituted.
8. Audit public model/report schema documentation, exception-to-exit mappings, type coverage, cache/report schema versions, deterministic behavior, absence of machine-specific paths in executable code, and all task acceptance criteria.

## Required automated matrix

In addition to every task's focused tests, prove:

- clean-cache and warm-cache system results have identical canonical reports/plans;
- `validate` and `analyze` make zero Resolve mutations;
- every accepted source boundary is within two timeline frames of generated ground truth;
- the complete plan has continuous master audio; matched video exactly for all occurrences of supplied takes; declared empty video intervals for unsupplied takes; no video overlap or filler; correct markers; and camera audio excluded;
- report write/read/build retains Decimal/frame semantics without float drift;
- Unicode, paths with spaces, fractional rates, long master duration, more than 16 takes, multiple source candidates, manual overrides, corrupt cache, and unavailable ffmpeg/Resolve behave as documented;
- all user-facing examples and CLI help stay synchronized with actual interfaces.

## Final gates

Run from a clean worktree environment:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run pre-commit run --all-files
```

Then, with explicit user authorization and a disposable Resolve project:

```bash
MULTI_CAM_SYNC_LIVE_CONFIG=/absolute/path/to/live.toml \
MULTI_CAM_SYNC_ALLOW_MUTATION=1 \
uv run pytest -m resolve_live -v
```

The private Arabesques media/config acceptance is manual/opt-in and must not be treated as a CI dependency.

## Acceptance criteria

- Every task's focused tests and the offline system matrix pass in one run.
- Pre-commit explicitly runs uv, Ruff format/check, ty, and the fast pytest suite.
- The live disposable-project timeline passes API verification and human spot-checking for partial video without modifying pre-existing timelines/media.
- The Arabesques review accounts for all 29 master segments and 28 transitions, verifies video only for the configured take subset (including Take 8 A/B from a shared physical recording when configured), and confirms all other intervals are video-empty.
- README, sample config, report example/schema, project plan, human guide, and CLI help agree.

## Handoff

Deliver the commands/results, canonical sample report, known platform prerequisites, cache/report locations, live timeline name, human acceptance notes, any manual-offset segments, and unresolved limitations. Do not call the project complete if a required gate is skipped; label unavailable live/private acceptance separately from automated completion.
