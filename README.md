# multi-cam-sync

`multi-cam-sync` creates a new DaVinci Resolve timeline for a performance whose final
master audio is assembled from several takes. It keeps the mastered audio continuous and
adds synchronized video only for the logical takes you provide.

The tool is deliberately non-destructive: it reads media already in the current Resolve
project, never imports or relinks media, never replaces an existing timeline, and does not
change Resolve during `validate` or `analyze`.

## Quick start: Resolve Studio external scripting

Run this application from a normal terminal while DaVinci Resolve Studio is open. Do not
import it from **Workspace → Console**; the audio-analysis dependencies are intended for a
standalone Python process.

### 1. Install the command dependencies

You need:

- Python 3.12 or newer;
- [`uv`](https://docs.astral.sh/uv/) for the environment and locked dependencies;
- `ffmpeg` and `ffprobe` available on `PATH`;
- an activated DaVinci Resolve Studio installation.

From the repository root, check the media tools and create the locked environment:

```bash
ffmpeg -version
ffprobe -version
uv sync --all-groups
uv run multi-cam-sync --version
```

### 2. Enable local external scripting

1. Launch DaVinci Resolve Studio.
2. Open **DaVinci Resolve → Preferences → System → General**.
3. Set **External scripting using** to **Local**.
4. Save the preference and restart Resolve Studio.
5. Open the project that contains the master audio and source video.

Use `Local`, not `Network`: this application connects only from the same computer and does
not need Resolve's scripting API exposed to the network.

### 3. Expose Resolve's scripting module to Python

Python must be able to find Resolve's scripting module and native library. Export the paths in
every terminal session that will run `multi-cam-sync`. A standard Linux installation uses:

```bash
export RESOLVE_SCRIPT_API=/opt/resolve/Developer/Scripting
export RESOLVE_SCRIPT_LIB=/opt/resolve/libs/Fusion/fusionscript.so
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$RESOLVE_SCRIPT_API/Modules"
```

If Resolve is installed somewhere other than `/opt/resolve`, use its actual installation path.
For macOS and Windows, use the paths in Resolve's bundled
`Help → Documentation → Developer → Scripting` README.

### 4. Verify the external connection

With Resolve Studio running and the intended project open, run this read-only smoke check from
the same terminal:

```bash
uv run python - <<'PY'
import DaVinciResolveScript as dvr_script

resolve = dvr_script.scriptapp("Resolve")
if resolve is None or resolve is False:
    raise SystemExit("Could not connect to Resolve Studio")

project_manager = resolve.GetProjectManager()
project = project_manager.GetCurrentProject() if project_manager else None
if project is None or project is False:
    raise SystemExit("Connected to Resolve Studio, but no project is open")

print(resolve.GetProductName(), resolve.GetVersionString())
print("Current project:", project.GetName())
PY
```

The check should print `DaVinci Resolve Studio`, its version, and the exact current project
name. It does not change the project.

If importing `DaVinciResolveScript` fails, recheck the three exported paths in the current
terminal. If the import works but the connection fails, confirm that Resolve Studio was
restarted after selecting `Local`. If the product name does not include `Studio`, confirm that
the Studio license is activated.

### 5. Prepare the project and configuration

The Media Pool must already contain the master item and every video item named in the
configuration. Selectors are exact and case-sensitive: a folder path and item name must
resolve to exactly one Media Pool item. Copy
[`examples/project.example.toml`](examples/project.example.toml) to a private working location,
then update its timeline name, cut-list path, exact Media Pool selectors, and analysis paths.

## Configuration reference

Do not commit a configuration that contains private media paths.

The complete version-1 TOML shape is:

```toml
schema_version = 1

[project]
timeline_name = "Performance — synced"
cuts_file = "cuts.txt"

[master]
media_pool_folder = "Audio/Masters"
media_pool_name = "performance-master.wav"
audio_path = "media/performance-master.wav" # optional

[[sources]]
id = "take-8-a"
take = "Take 8 A"
media_pool_folder = "Video/Multicam"
media_pool_name = "Take 8 multicam"
audio_reference_path = "media/take-8-camera.mov" # optional when item has File Path
source_start = "00:00:00.000"                    # optional; defaults to zero
source_end = "00:02:10.000"                      # optional; defaults to media end
manual_offset_seconds = -1.25                    # optional numeric seconds
```

### Exact schema rules

| Location | Key | Type | Requirement and meaning |
| --- | --- | --- | --- |
| root | `schema_version` | integer | Required and must be `1`. |
| `[project]` | `timeline_name` | nonblank string | Required; build refuses an existing timeline with this exact name. |
| `[project]` | `cuts_file` | path string | Required; decimal cut-list path. |
| `[master]` | `media_pool_folder` | nonblank string | Required exact folder path; use `/` between nested folders or `.` for the root bin. |
| `[master]` | `media_pool_name` | nonblank string | Required exact master item name. |
| `[master]` | `audio_path` | path string | Optional when the Media Pool item exposes a readable `File Path`. |
| `[[sources]]` | `id` | nonblank string | Required and unique across source entries. |
| `[[sources]]` | `take` | nonblank string | Required logical cut-list take; surrounding/repeated whitespace is normalized. |
| `[[sources]]` | `media_pool_folder` | nonblank string | Required exact folder path; use `.` for the root bin. |
| `[[sources]]` | `media_pool_name` | nonblank string | Required exact video or multicam item name. |
| `[[sources]]` | `audio_reference_path` | path string | Optional unless the Resolve item has no readable physical `File Path`. |
| `[[sources]]` | `source_start` | timestamp or seconds | Optional nonnegative occurrence start; default `0`. |
| `[[sources]]` | `source_end` | timestamp or seconds | Optional occurrence end, strictly greater than `source_start`. |
| `[[sources]]` | `manual_offset_seconds` | TOML number | Optional finite offset where source time equals master time plus this value. |

`source_start` and `source_end` accept numeric seconds or a string in
`HH:MM:SS[.fraction]` form. `manual_offset_seconds` must be an unquoted TOML number. All
filesystem paths may be absolute; relative paths are resolved from the configuration file.
Unknown keys, duplicate source IDs, unused source take labels, and invalid bounds are errors.

The cut list consists of one or more transition blocks:

```text
Out: Take 8 A
In:  Take 2 A
00:00:19.375
```

Times are positions from the start of the master, not SMPTE timecode. Adjacent blocks must
join (`In` from one equals `Out` from the next), and transition times must increase.

### Partial video is intentional

`[[sources]]` is a selection, not a list that must cover every cut-list take. It may be
omitted, written as `sources = []`, or contain only the one or two takes whose video is
available. Every master segment for a supplied take receives synchronized video. Intervals
for omitted takes remain genuinely empty on Video Track 1—no black clip, title, or filler is
created—while the master audio continues on Audio Track 1.

Several logical takes may share one physical recording. Give them separate source IDs and
bounds while repeating the same Media Pool selector and reference path, as the Take 8 A/B
sample does.

There is an important safety distinction:

- omitted take: `video_status = "not_provided"`; no matching is attempted and build may
  proceed with an intentional video gap;
- supplied take with a safe match: `video_status = "matched"`; video is placed for every
  segment carrying that take;
- supplied take with a failed or ambiguous match: `video_status = "unsafe"`; build is
  blocked instead of silently leaving requested video out.

## Run the workflow

Use a report path outside source control (the repository ignores `reports/` and
`*.alignment-report.json`):

```bash
uv run multi-cam-sync validate /path/to/project.toml
uv run multi-cam-sync analyze /path/to/project.toml --report reports/alignment-report.json
uv run multi-cam-sync build /path/to/project.toml --report reports/alignment-report.json
```

Run all three commands from the same externally configured terminal while Resolve Studio
remains open on the same project. An externally installed environment can omit `uv run` and
invoke `multi-cam-sync` directly.

1. `validate` checks the TOML, cuts, files, open Resolve project, exact Media Pool selectors,
   frame settings, and target timeline name. It does not decode full audio or mutate Resolve.
2. `analyze` decodes and matches only supplied takes, then atomically writes deterministic
   report JSON. It never mutates Resolve, including when a match is unsafe.
3. Review each segment's status, selected source and bounds, blockers, warnings, candidate
   diagnostics, cache/manual flags, and the embedded edit plan.
4. `build` rechecks the configuration, file fingerprints, Resolve snapshot, report schema,
   settings, and plan before making one new timeline. It never re-analyzes implicitly.

Exit codes are stable: `0` is success, `2` is a command/configuration/cut/path/report error,
`3` is a Resolve connection/discovery/preflight error, `4` means analysis completed with an
unsafe supplied match, `5` is a timeline mutation/verification/rollback error, and `1` is an
unexpected internal error. Add root option `--verbose` for a traceback when diagnosing an
unexpected failure.

## Reports, cache, and recovery

Reports use `report_schema_version = 1`, sorted UTF-8 JSON, exact decimal strings, input
fingerprints, a Resolve project snapshot, all segment statuses, and the complete plan when it
is safe to build. Creation time and run ID are audit metadata; canonical report comparison
excludes them. Any changed configuration, cuts, media content, Resolve project/settings/media
identity, tool-supported schema, or alignment settings makes a report stale. Run `analyze`
again rather than editing report JSON.

Decoded analysis audio is cached in the operating system's user cache directory under
`multi-cam-sync/analysis-audio` (normally `$XDG_CACHE_HOME/multi-cam-sync/analysis-audio` or
`~/.cache/multi-cam-sync/analysis-audio` on Linux). Cache keys include file fingerprints,
crop/stream/decode settings, and schema versions. A missing, incompatible, or corrupt entry is
ignored and rebuilt atomically. The cache is disposable; removing only this application cache
forces clean analysis without affecting source media or reports.

For recovery:

- fix a bad selector, source bound, or reference path, then rerun `validate` and `analyze`;
- narrow occurrence bounds when repeated music makes candidates ambiguous;
- use numeric `manual_offset_seconds` only after measuring it, and review its report warning;
- rerun `analyze` whenever `build` reports stale inputs;
- choose a new `timeline_name` if it already exists—V1 has no replace mode;
- if a failure occurs after timeline creation, the tool attempts to delete only that new
  timeline and reports whether rollback succeeded. If rollback also fails, inspect Resolve
  and manually remove only the newly named incomplete timeline.

Existing timelines and Media Pool media are never recovery targets.

## Development

Run the complete local gate from the repository root:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run pre-commit run --all-files
```

Ordinary tests are offline and require neither private media nor a running Resolve instance.
Live Resolve and Arabesques acceptance are opt-in; follow the guarded commands and human
review checklist in the project documentation.

### Opt-in live Resolve Studio smoke test

Open a disposable Resolve project whose Media Pool matches a private partial-video TOML. The
TOML must supply only one or two logical takes, must leave at least one cut-list take omitted,
and must use a new `timeline_name`. Set the expected identities explicitly; the test refuses
to mutate when any identity differs and leaves the successfully verified timeline for review.
This pytest harness connects from an external process and therefore requires Resolve Studio.

```bash
export MULTI_CAM_SYNC_LIVE_CONFIG=/absolute/path/to/disposable-project.toml
export MULTI_CAM_SYNC_LIVE_REPORT=/absolute/path/to/live-smoke.alignment-report.json
export MULTI_CAM_SYNC_LIVE_PROJECT="Exact disposable Resolve project name"
export MULTI_CAM_SYNC_LIVE_TIMELINE="Exact unique timeline_name from the TOML"
export MULTI_CAM_SYNC_LIVE_CONFIRM_DISPOSABLE=1
export MULTI_CAM_SYNC_ALLOW_MUTATION=1
uv run pytest tests/test_live_acceptance.py -m resolve_live -v
```

Unset `MULTI_CAM_SYNC_ALLOW_MUTATION` immediately after the run. The workflow validates,
analyzes, writes and reviews the report, then builds exactly once. Without both the disposable
confirmation and mutation authorization, it fails before constructing a production service.

### Opt-in Arabesques acceptance

Point a private TOML at the checked-in Arabesques cut list and configure only one or two takes
with available video. The pytest command below requires Resolve Studio external scripting.
Open the exact Resolve project and choose an unused timeline name:

```bash
export MULTI_CAM_SYNC_ARABESQUES_CONFIG=/absolute/path/to/arabesques-private.toml
export MULTI_CAM_SYNC_ARABESQUES_REPORT=/absolute/path/to/arabesques.alignment-report.json
export MULTI_CAM_SYNC_ARABESQUES_PROJECT="Exact current Resolve project name"
export MULTI_CAM_SYNC_ARABESQUES_TIMELINE="Exact unique timeline_name from the TOML"
export MULTI_CAM_SYNC_ALLOW_MUTATION=1
uv run pytest tests/test_live_acceptance.py -m arabesques_acceptance -v
```

This workflow requires all 29 master segments, 28 cut markers, matched video for every
segment of the supplied take or takes, and explicit empty video gaps everywhere else. It
leaves the verified timeline and report for the human checklist below. These marked tests are
excluded from pre-commit and the ordinary offline suite; never combine both marker selections
in one authorized run.

## Project documentation

- [Product and technical specification](specifications.md)
- [Implementation plan](plans/PROJECT_PLAN.md)
- [Human guide and acceptance checklist](plans/HUMAN_GUIDE.md)
- [Task 07 system verification and live-test contract](plans/tasks/07-system-verification.md)
