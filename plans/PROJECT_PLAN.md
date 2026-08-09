# Multi-Cam Sync — Implementation Plan

## Mission and definition of done

Build the external Python CLI defined in [`specifications.md`](../specifications.md): validate a user-authored TOML project, match mastered-audio segments only for the logical takes whose video was supplied, emit a reviewable alignment report, and create one verified, non-destructive Resolve timeline. Unsupplied takes are valid audio-only regions.

The project is done when the full `uv`/Ruff/ty/pytest/pre-commit gate passes, accepted synthetic alignments are within two timeline frames, and the opt-in Resolve/Arabesques acceptance workflow produces continuous master-audio segments plus multicam video only for configured takes, with exact intentional video gaps elsewhere, without modifying existing timelines or media.

## Fixed architecture

Use a `src/multi_cam_sync/` package with these boundaries:

- **Domain/config:** immutable typed models, TOML loading, cut parsing, validation, Decimal time values, and versioned JSON report models.
- **Media:** Resolve Media Pool discovery, filesystem path resolution, `ffprobe`/`ffmpeg` access, audio decode, fingerprints, and atomic cache.
- **Alignment:** project-owned feature extraction and subsequence-DTW APIs adapted from Elidan Take Picker, invoked only for video-enabled segments; no dependency on that application or `.etp` state.
- **Planning:** pure conversion of validated cuts and available accepted matches into an `EditPlan` containing continuous master clips, optional video clips, explicit video-gap spans, exact frames, names, colors, and markers.
- **Resolve adapter:** the only module allowed to call `DaVinciResolveScript`; it preflights, mutates a newly created timeline, verifies it, and rolls back that new timeline on failure.
- **CLI:** `validate`, `analyze`, and `build` orchestration, stable exit codes, structured logs, concise errors, and deterministic report serialization.

The central data flow is:

```text
project.toml + cuts + open Resolve project
                    │
                    ▼
           validated ProjectSpec
                    │
         media probe/decode/cache
                    │
                    ▼
    video status + SegmentMatch results
                    │
                    ▼
       versioned AlignmentReport/EditPlan
                    │
             full build preflight
                    │
                    ▼
       new verified Resolve timeline
```

## Public interfaces to preserve

- CLI: `multi-cam-sync validate CONFIG`, `analyze CONFIG --report PATH`, and `build CONFIG --report PATH`.
- Configuration: `schema_version = 1` TOML with `[project]`, `[master]`, and repeated `[[sources]]` tables exactly as specified.
- Cut list: repeated `Out`, `In`, decimal timestamp blocks; names are normalized but never inferred from filenames.
- Report: deterministic, versioned JSON containing input fingerprints, Resolve identity/settings, per-segment `not_provided`/`matched`/`unsafe` video status, available matches, frame plan, confidence diagnostics, overrides, warnings, and tool/config versions.
- Resolve boundary: typed `ResolveGateway`/protocol abstractions return project-owned models; all raw API calls remain inside the adapter.

Breaking any of these shapes requires a deliberate schema/version change and migration tests.

## Work graph and agent ownership

Implement tasks in dependency order. Tasks on the same row may run in parallel after their dependencies merge. An agent owns only the production and test files named by its task; shared configuration belongs to Task 00 and final reconciliation belongs to Task 07.

| Order | Task | Depends on | Primary deliverable |
| --- | --- | --- | --- |
| 1 | [00 — Foundation and tooling](tasks/00-foundation-tooling.md) | — | Installable typed package; locked toolchain and quality gates |
| 2 | [01 — Domain, configuration, and cuts](tasks/01-domain-config-cuts.md) | 00 | Validated `ProjectSpec`, segments, report schema, exact time parsing |
| 3A | [02 — Media probing, decoding, and cache](tasks/02-media-audio-cache.md) | 00, 01 | Deterministic analysis audio and safe cache |
| 3B | [05 — Resolve read adapter and API fakes](tasks/05-resolve-integration.md), read/preflight half | 00, 01 | Typed Media Pool/project discovery behind fakes |
| 4 | [03 — Audio alignment engine](tasks/03-audio-alignment.md) | 01, 02 | Accepted/rejected `SegmentMatch` results with diagnostics |
| 5 | [04 — Edit planning and frame math](tasks/04-edit-planning.md) | 01, 03 | Pure plan with continuous audio and explicit optional-video gaps |
| 6 | [05 — Resolve timeline construction](tasks/05-resolve-integration.md), mutation half | 04 | Created, verified timeline and narrow rollback |
| 7 | [06 — CLI and end-to-end orchestration](tasks/06-cli-orchestration.md) | 02–05 | Complete validate/analyze/build workflow |
| 8 | [07 — System verification and handoff](tasks/07-system-verification.md) | 00–06 | Cross-module tests, live runbook, docs, release gate |

Task 05 is one ownership unit even though its read-only API layer can begin earlier. Do not merge its timeline mutation portion before Task 04 fixes the `EditPlan` contract.

## Agent working contract

Every implementation agent must:

1. read `specifications.md`, this file, and its task file before changing code;
2. invoke the relevant repository skills from `.agents/skills/`;
3. preserve public contracts and add no hidden fallback behavior;
4. add tests in the same change—no task is complete with deferred tests;
5. run its focused tests plus Ruff and ty on touched code;
6. report changed interfaces, commands run, known limitations, and any acceptance artifact;
7. avoid real Resolve mutations except the explicit opt-in smoke workflow in Task 07.

When a dependency contract is insufficient, the agent must update its own task notes or raise the gap for the owning task; it must not create a second competing model or reach across module boundaries.

## Cross-cutting decisions

- **Safety:** `validate` and `analyze` never mutate Resolve. `build` completes all preflight checks first, refuses an existing target timeline, and can delete only the new timeline created by its own failed run.
- **Partial video:** configure only the takes with available video. Every occurrence of a configured take must receive video; every occurrence of an unconfigured take remains an intentional empty video span while master audio continues.
- **Synchronization:** reuse the MFCC/delta/normalized asymmetric open-ended DTW proven in Take Picker. Run it only for video-enabled segments and their bounded logical occurrences, use it to locate media and quantify confidence, and place unity-speed video.
- **Multiple logical takes per recording:** represent each occurrence explicitly with a unique source ID and source bounds; repeated entries may refer to the same Media Pool item/audio file.
- **Missing versus unsafe:** no configured source means `not_provided` and is valid. A configured source that cannot be matched safely means `unsafe` and blocks `build`; never turn a failed requested match into an audio-only gap.
- **Ambiguity:** do not guess. Multiple close candidates, unstable edges, excess drift, or insufficient coverage become reportable unsafe results that block `build`; `manual_offset_seconds` is the explicit escape hatch.
- **Frame accuracy:** keep Decimal seconds through analysis; independently round absolute boundaries, then subtract neighboring boundaries. Separate source-frame and timeline-frame conversions.
- **Testability:** numerical work is pure, subprocess calls are injectable, and Resolve is behind strict fakes. Normal CI needs neither real media nor Resolve.
- **Observability:** every report/log associates work with run, config, source, and segment IDs. Cached and manual results remain visible.

## Test strategy and merge gate

Each task file lists focused tests. Task 07 adds the cross-module matrix and opt-in acceptance paths. The default suite must be deterministic, offline, and safe to run without Resolve. Synthetic audio fixtures are generated during tests and must exercise microphone-response differences, gain, noise, silence, offsets, repeated phrases, multiple bounded occurrences, ambiguity, and drift.

Before the final merge:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run pre-commit run --all-files
```

Then run the separately marked live Resolve smoke test against a disposable project and the human-reviewed Arabesques acceptance procedure. Live tests must never be part of pre-commit or ordinary CI.

## Delivery milestones

1. **Schema milestone (Tasks 00–01):** sample configuration and cut list validate; domain/configuration models round-trip deterministically.
2. **Analysis milestone (Tasks 02–03):** synthetic and bounded multi-occurrence audio maps within two frames and unsafe matches are rejected.
3. **Plan milestone (Task 04):** the Arabesques cut list plus a one/two-take source subset produces continuous audio, the exact corresponding video clips, deterministic intentional video gaps, and no Resolve mutation.
4. **Resolve milestone (Task 05):** strict fakes verify every API call, error check, post-build invariant, and rollback branch.
5. **Product milestone (Tasks 06–07):** the three CLI commands, reports, documentation, quality gates, disposable-project smoke test, and real-project review all pass.

## Repository skills

- [`develop-python`](../.agents/skills/develop-python/SKILL.md): package structure, `uv`, Ruff, ty, pytest, and pre-commit workflow.
- [`align-audio`](../.agents/skills/align-audio/SKILL.md): the project-specific audio matching workflow and safety criteria.
- [`script-davinci-resolve`](../.agents/skills/script-davinci-resolve/SKILL.md): Resolve API boundaries, native timeline workflow, fakes, and mutation safety.
- [`test-multi-cam-sync`](../.agents/skills/test-multi-cam-sync/SKILL.md): deterministic test layers, fixture requirements, and acceptance rules.

## Explicitly deferred

- multicam angle selection or automatic shot choice;
- a graphical UI or Resolve Workflow Integration panel;
- automatic time-stretch/retime curves;
- `.etp` import, score/MusicXML use, or dependency on Elidan Take Picker;
- media import, relink, destructive timeline replacement, or batch processing;
- support for a configured Resolve multicam item without either a readable physical audio path or an explicit `audio_reference_path`.
