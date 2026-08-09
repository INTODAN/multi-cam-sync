# Task 01 — Domain Models, Configuration, Cuts, and Time Values

## Objective

Turn a version-1 TOML file and the existing composite-cuts text format into a complete, immutable, validated `ProjectSpec` and ordered `MasterSegment` sequence. No audio decoding or Resolve mutation belongs here.

## Dependencies and ownership

- Depends on: Task 00.
- Owns: `domain/models.py`, `domain/errors.py`, `config.py`, `cuts.py`, `time_values.py`, and focused tests with text/TOML fixtures.
- Use `$develop-python` and `$test-multi-cam-sync`.

## Public models and functions

Implement these project-owned interfaces; exact internal helpers are flexible:

```python
class ProjectSpec: ...       # schema_version, config_path, project, master, optional sources
class ProjectSettings: ...   # timeline_name, cuts_file
class MasterSpec: ...        # exact Media Pool selector and optional audio_path
class SourceSpec: ...        # id, take, selector, reference path/bounds, optional override
class CutTransition: ...     # outgoing_take, incoming_take, master_time
class MasterSegment: ...     # stable id/index, take, master_start, optional master_end

def load_project_spec(path: Path) -> ProjectSpec: ...
def parse_cut_list(text: str) -> tuple[CutTransition, ...]: ...
def build_master_segments(cuts, master_duration=None) -> tuple[MasterSegment, ...]: ...
def parse_decimal_timestamp(value: str) -> Decimal: ...
def normalize_take_name(value: str) -> str: ...
```

Use frozen Pydantic v2 models or frozen dataclasses with equivalent validation. Store time as `Decimal` seconds; do not use floats or SMPTE objects in this layer. Keep the original display take name plus a normalized comparison key.

## Validation rules

1. Accept only `schema_version = 1`; reject missing, boolean, string, zero, or future values with an actionable message.
2. Resolve `cuts_file`, `master.audio_path`, and every `audio_reference_path` relative to the TOML's parent. Preserve absolute normalized paths without requiring Resolve.
3. Require a nonblank timeline name. Permit an omitted/empty `sources` list. For each supplied source, require exact nonblank Media Pool folder/name selectors, a unique nonblank ID, a nonblank take label, and a finite numeric manual offset when present.
4. Source bounds are optional decimal timestamps, but `source_start` defaults to zero, `source_end` must exceed it, and both must be nonnegative. Actual media-duration validation belongs to Task 02.
5. Parse repeated `Out`, `In`, timestamp blocks with blank lines allowed. Collapse internal whitespace in take names. Reject duplicate fields, unexpected content inside a block, incomplete blocks, malformed timestamps, non-increasing cuts, negative values, and trailing partial blocks. Header prose before the first `Out` is allowed for compatibility with the supplied example.
6. Enforce transition continuity: normalized `cuts[n].incoming_take == cuts[n+1].outgoing_take`.
7. Build segment 0 from the first `Out`, subsequent segments from each `In`, and stable IDs such as `segment-0001`. The last end remains absent until the probed master duration is supplied; then reject a cut at or beyond that duration.
8. Derive the set of video-enabled take keys from the configured sources. Do not require coverage for every segment/take. Require every configured source's normalized take key to occur in the cut-derived segments; reject unused sources as likely typos. Multiple candidates for one enabled take are valid.
9. Expose a deterministic lookup from take key to candidate sources so orchestration can distinguish `not_provided` (no configured candidates) from `unsafe` (configured candidates failed matching).
10. Aggregate independent validation errors where practical, include the TOML key or cut-list line, and never expose a raw Pydantic traceback through the public loader.

## Tests

Cover at minimum:

- the checked-in Arabesques cut file parses into 28 transitions and 29 segments with normalized `Take 6 B` despite double spaces;
- valid relative/absolute TOML paths, omitted/empty source lists, a one/two-take subset from a nine-take cut sequence, full source coverage, and repeated sources sharing one Media Pool selector;
- two bounded entries for Take 8 A/B in the same physical recording;
- every schema, supplied-source required-field, duplicate-ID, invalid-bound, and unused-source-take failure;
- headers, blank lines, CRLF, whitespace normalization, malformed/partial/duplicate blocks, discontinuous transitions, duplicate/decreasing/equal timestamps, and out-of-duration cuts;
- timestamp precision for hours, milliseconds, more fractional digits, and invalid minute/second ranges;
- immutability and deterministic equality/serialization of models.

Use table-driven tests and temporary files; no test may need Resolve, ffmpeg, or network access.

## Acceptance criteria

- Given only config text, cut text, and an optional master duration, callers receive either a complete immutable domain model or one actionable domain error.
- No float time enters the returned models.
- The Arabesques example produces the expected 29 logical segments with zero, partial, or full video-enabled take coverage; omitted takes are represented by an empty candidate lookup rather than a validation error.
- Ruff, ty, and focused tests pass.

## Handoff

Publish the model field names, normalized-name rule, error type hierarchy, and stable segment-ID rule. Later tasks must import these types rather than reconstructing dictionaries.
