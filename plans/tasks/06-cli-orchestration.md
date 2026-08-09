# Task 06 — CLI, Reports, and End-to-End Orchestration

## Objective

Join the pure domain/media/alignment/planning layers and the Resolve gateway into the three user commands. Make reports deterministic and stale-safe, errors concise, and command exit behavior suitable for both humans and automation.

## Dependencies and ownership

- Depends on: Tasks 01–05.
- Owns: `cli.py`, `services.py`, `reporting/models.py`, `reporting/io.py`, CLI/service tests, and replacement of Task 00's placeholder entry point.
- Does not weaken domain confidence or Resolve safety checks.
- Use all four repository skills.

## Commands and behavior

### `validate CONFIG`

Load and validate TOML/cuts, connect to the current Resolve project, resolve exact selectors only for the master and configured source subset, probe configured physical/reference media, finalize master duration, and confirm the target timeline name is unused. Print a compact per-take/per-segment summary distinguishing video-enabled from intentional audio-only coverage. It must not decode full audio, write a report, create a timeline, or make any Resolve mutation.

### `analyze CONFIG --report PATH`

Run validation; assign `not_provided` without decode/alignment to segments whose takes have no configured sources; decode/cache and match only video-enabled segments; construct the edit plan when all requested matches are accepted; and atomically write a report in every case. Unsafe requested matching is a normal analyzed result: write all diagnostics, print a concise rejected-segment table, and exit with the analysis-unsafe code. A report containing only `matched` and `not_provided` segments is buildable. It must not mutate Resolve.

### `build CONFIG --report PATH`

Require an existing successful report. Reload config/cuts, re-snapshot Resolve, re-probe/fingerprint inputs, and reject any difference in tool-supported schema, configuration hash, file fingerprint, project name/settings, Media Pool ID, alignment settings, or plan. Then call the gateway once with the embedded plan and print timeline/verification/rollback outcome. Do not silently re-analyze.

## Report contract

Use immutable Pydantic v2 models and stable JSON formatting (UTF-8, sorted keys, two-space indentation, final newline, no NaN). Include:

- `report_schema_version = 1`, package version, UTC creation time, run ID, and analysis settings;
- canonical configuration hash and safe resolved paths;
- project snapshot, target timeline, master/configured-source media IDs/properties/fingerprints;
- normalized cuts/master segments;
- every segment's `video_status`; candidate summary and selected `SegmentMatch` only where requested; blocker codes, warnings, manual/cached status;
- the complete `EditPlan`, including explicit intentional video gaps, when no requested match is unsafe; otherwise `null` plus failure summary.

Volatile creation time/run ID may differ across invocations, but canonical hashes and all analysis/plan fields must remain deterministic. Provide a canonical-payload helper that excludes volatile fields for equality/fingerprint tests. Write via a sibling temporary file plus `os.replace`; never leave a partial report.

## Errors, output, and exit codes

Use one top-level exception boundary. Default output is concise text; `--verbose` enables tracebacks/debug logs. Do not log audio arrays or unrestricted subprocess stderr.

Fixed exit codes:

- `0`: success;
- `2`: CLI, configuration, cut-list, path, or report-schema error;
- `3`: Resolve connection, discovery, or preflight error;
- `4`: completed analysis with one or more unsafe requested matches (`not_provided` is not an error);
- `5`: timeline mutation, verification, or rollback error;
- `1`: unexpected internal error.

Support `--version` and `--verbose` at the root. Refuse unknown options/subcommands through argparse. Never prompt interactively; remediation is expressed in errors/report warnings so commands remain scriptable.

## Tests

Use temporary files and fake media/Resolve/matcher services to cover:

- argument parsing, help/version, required config/report arguments, unknown commands, and every exit-code mapping;
- validate call order, summary, and proof of no decode/report/mutation;
- analyze zero/partial/full-source success, unsafe/error call order, proof that missing sources trigger no decode/matcher call, atomic report replacement, deterministic canonical payload, Unicode take names, and report written on unsafe matches;
- build success and every stale dimension: config, cuts, file content, project/rate, Media Pool ID, settings, report schema/tool incompatibility, absent/unsafe plan;
- proof that stale build never calls the mutation gateway and valid build calls it exactly once;
- concise default errors, verbose traceback, safe logging, rollback outcome text, and broken output/report paths;
- service-level happy path from sample TOML/cuts through a fake plan and fake timeline.

## Acceptance criteria

- The three commands implement exactly the specified side-effect boundaries and treat an omitted take as valid audio-only coverage while preserving errors for unsafe supplied takes.
- A report is sufficient to review and exactly reproduce/verify the planned build; stale inputs cannot slip through.
- All expected user failures have stable exit codes and no default traceback.
- `python -m multi_cam_sync` and the installed `multi-cam-sync` script behave identically.
- Ruff, ty, and focused tests pass.

## Handoff

Publish CLI help snapshots, exit-code table, report JSON schema/example, canonical hashing rule, logging controls, and service injection points used by system tests.
