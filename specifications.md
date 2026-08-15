# Multi-Cam Sync — Product and Technical Specification

## 1. Goal

Create a non-destructive DaVinci Resolve timeline for a music performance whose final master audio is a composite of several takes. The generated timeline must:

- preserve the mastered audio as the only audible program track;
- place matching multicam video only for master-audio segments whose logical take has been supplied by the user;
- keep each placed item aligned to the performance heard in the master;
- label, color, and mark the edit so a human can inspect and continue editing it in Resolve.

The user prepares the media in the current Resolve project's Media Pool. The application does not import, rename, relink, or delete user media.

## 2. V1 scope

V1 is an external Python command-line application that connects to an open DaVinci Resolve instance through Resolve's Python API. It validates the project, analyzes the supplied video takes, writes a reviewable JSON report, and then creates one new timeline. Supplying video is optional per logical take: a project may contain video for only one or two takes out of a larger composite, or no video at all. Unsupplied take regions remain empty on the video tracks while the master audio continues uninterrupted.

V1 does not choose multicam angles, alter the master mix, modify an existing timeline, or use GUI automation. It does not time-stretch video. If the measured drift would be visible, the build is blocked for manual review instead of silently producing a bad timeline.

## 3. Required inputs

### 3.1 Resolve project

DaVinci Resolve must be running with the intended project open. The following items must already exist in the Media Pool:

- one physical master-audio item;
- one video or Resolve multicam item for every source occurrence that is named in the configuration.

Media Pool items are selected by exact folder path plus exact item name. A missing selector or a selector matching more than one item is an error.

### 3.2 Cut list

The existing decimal-seconds text format remains supported:

```text
Out: Take 8 A
In:  Take 2 A
00:00:19.375
```

Whitespace around take names is trimmed and internal runs of whitespace are collapsed. Each timestamp is a position relative to the beginning of the master audio and may use either decimal `HH:MM:SS[.fraction]` or non-drop frame timecode `HH:MM:SS:FF`. Frame timecode uses the active Resolve timeline frame rate; for example, `00:03:08:13` at 24 fps is `188 + 13/24` seconds. The four fields and leading hour field are required for frame timecode so an existing three-field value such as `00:03:08` remains unambiguously decimal hours, minutes, and seconds. Frame numbers must fit the nominal timeline rate. Drop-frame semicolon notation is not supported.

The parser must reject incomplete blocks, invalid or non-increasing timestamps, adjacent transition mismatches, timestamps outside the master duration, and a cut list with no transitions. The first `Out` value is the first segment's take; every `In` value becomes the next segment's take. Every previous `In` must equal the next `Out` after normalization.

### 3.3 Project configuration

The user supplies a versioned TOML file. Its public shape is:

```toml
schema_version = 1

[project]
timeline_name = "Arabesques — synced"
cuts_file = "examples/Arabesques_composite_cuts.txt"

[master]
media_pool_folder = "Masters"
media_pool_name = "Arabesque final Master.wav"
# Optional when the physical Media Pool item exposes a readable File Path.
audio_path = "/media/arabesques/master.wav"

[[sources]]
id = "take-8-a"
take = "Take 8 A"
media_pool_folder = "Multicam"
media_pool_name = "Take 8 multicam"
# Required for virtual multicam/compound items that have no readable File Path.
audio_reference_path = "/media/arabesques/camera-a/take-8.mov"
additional_audio_reference_paths = [
    "/media/arabesques/camera-b/take-8.mov",
]
source_start = "00:00:00.000"
source_end = "00:02:10.000"

[[sources]]
id = "take-8-b"
take = "Take 8 B"
media_pool_folder = "Multicam"
media_pool_name = "Take 8 multicam"
audio_reference_path = "/media/arabesques/camera-a/take-8.mov"
additional_audio_reference_paths = [
    "/media/arabesques/camera-b/take-8.mov",
]
source_start = "00:02:25.000"
source_end = "00:05:20.000"

[[sources.segment_search_ranges]]
segment_id = "segment-0014"
source_start = "00:04:57.000"
source_end = "00:05:03.000"

[[sources.segment_manual_offsets]]
segment_id = "segment-0018"
manual_offset_seconds = 517.8726761706474
```

`id` is unique, while several source entries may share a take label or the same Media Pool item. `source_start` and `source_end` describe the occurrence within the physical recording and are the supported solution for a file containing multiple takes separated by a break. The program never infers take identity from filenames.

Optional `additional_audio_reference_paths` are ordered microphone fallbacks for the same
physical-source timeline. The primary reference is always matched first. Only an unsafe
complete segment match advances to the next reference, and matching stops at the first safe
result. Every fallback is probed and fingerprinted before analysis, must have exactly the
primary reference's whole-file duration, and receives the same occurrence and per-segment
bounds. Decoding remains lazy. Reports retain candidates from every attempted reference and
identify them as `primary`, `additional-1`, and so on. Sources using the source-wide
`manual_offset_seconds` cannot declare additional references. Segment-specific manual offsets
may coexist with fallbacks because every other segment still matches automatically.

An optional `[[sources.segment_search_ranges]]` entry narrows one source candidate for one stable master-segment ID. Its bounds use the same absolute physical-source timeline as the parent bounds and must remain inside the parent source occurrence; its segment must carry the parent source's logical take, and a source may declare at most one range per segment. Segments without an override search the full parent occurrence. Effective search bounds are included with candidate diagnostics in the report. Segment search ranges cannot be combined with source-wide `manual_offset_seconds`, or with a segment manual offset for the same segment, because manual matching bypasses DTW.

An optional `[[sources.segment_manual_offsets]]` entry applies `source time = master time + manual offset` to one stable segment ID only. The segment must carry the parent source's take, IDs must be unique within the source, and `manual_offset_seconds` must be an unquoted finite TOML number. Matching for that source and segment is labeled `manual` and bypasses DTW and microphone fallback attempts; every other segment remains automatic and may use its configured search range and fallback references. Segment-specific offsets cannot be combined with source-wide `manual_offset_seconds`.

The `[[sources]]` list is a partial-video selection, not a completeness requirement. A logical take with one or more source entries is **video-enabled**, and the program must create video for every master segment carrying that take label. A logical take with no source entry is **audio-only**, which is valid and produces no video item, placeholder, title, or black generator over those segments. Every configured source's take label must occur in the cut-derived master segments; an unused source is rejected as a likely typo.

Optional source-wide `manual_offset_seconds` bypasses automatic matching for every eligible segment of that source. It means `source time = master time + manual offset` within that logical occurrence and is always called out in the report. Use a segment-specific manual offset when other segments of the same take should remain automatic.

Relative filesystem paths are resolved relative to the TOML file. `sources` may be empty. Missing source entries are reported as intentional audio-only coverage, not as validation or alignment failures.

## 4. Outputs and commands

The installed command is `multi-cam-sync` and exposes:

- `multi-cam-sync validate CONFIG`: validate TOML, cuts, files, Resolve connection, project settings, and unique Media Pool selectors without changing Resolve;
- `multi-cam-sync analyze CONFIG --report PATH`: perform audio alignment and write a deterministic JSON alignment report without changing Resolve;
- `multi-cam-sync build CONFIG --report PATH`: verify that the report still matches all input fingerprints, preflight the entire edit, and create the timeline.

The report contains the schema version, tool version, configuration hash, input fingerprints, Resolve project/timeline frame rates, every master segment, its `video_status` (`not_provided`, `matched`, or `unsafe`), the selected source occurrence when applicable, source in/out seconds, a suggested segment-specific manual offset when an unsafe automatic match still provides an in-bounds unity-speed location, timeline/source frame boundaries, DTW diagnostics, confidence status, warnings, and whether a manual override was used.

`build` refuses stale reports, an `unsafe` segment for any video-enabled take, unresolved configured media, an existing timeline with the requested name, or a changed Resolve project. `not_provided` segments do not block building. There is no replace mode in V1.

## 5. Audio-alignment design

### 5.1 Reused proven approach

Use the successful alignment approach in:

`/home/itaielidan/PycharmProjects/elidan-take-picker-workspace/main`

In particular, take inspiration from `elidan_take_picker/warping_path.py`, `waveform.py`, `measure.py`, and the cached warping-path flow in `main.py` and `server.py`:

- decode mono audio and resample analysis copies to 22,050 Hz;
- compute 80 MFCC coefficients with a hop length of 256;
- append first- and second-order MFCC deltas;
- normalize each feature dimension so microphone level and tonal balance dominate less;
- use cosine-distance DTW with the asymmetric step pattern and open begin/end;
- preserve a monotonic mapping in seconds and cache expensive results by content/configuration fingerprint.

Do not import that project as a runtime dependency or copy its application state. Extract and adapt the small alignment concepts behind project-owned interfaces and tests.

The `.etp` file is not a V1 input. Its cache describes good-microphone recordings and score-related state, whereas this application must compare the final master with camera-reference audio. It may be reconsidered only if a later benchmark demonstrates a measurable benefit.

### 5.2 Segment matching

For each master segment whose take is video-enabled, the matcher considers only source entries with the normalized logical take label. A segment-specific manual offset takes precedence for only that source/segment. Otherwise each candidate is cropped to its configured segment-specific search range when present, or to its occurrence bounds. Automatic sources are matched in reference rounds: all primary references first, followed by each configured fallback index only while the earlier round is unsafe. A short guard region at the master segment's edit edges is excluded from feature scoring so master crossfades do not dominate the match. The matcher is not invoked for an audio-only segment; that segment receives `video_status = "not_provided"` without a confidence score or warning.

Subsequence DTW locates the master segment inside each candidate occurrence. A robust affine fit over the interior warping path estimates the source start and end, rejects outlier path points, and measures drift. The lowest-cost valid candidate wins only when it is unambiguous and stable under a one-hop boundary perturbation.

A result for a video-enabled segment is low confidence, receives `video_status = "unsafe"`, and blocks `build` when any of these conditions holds:

- the warping path does not cover at least 95% of the scored master frames;
- its mapped times leave the configured source bounds;
- the runner-up candidate's normalized cost is within 5% of the winner;
- perturbing the scoring boundary moves either mapped boundary by more than two timeline frames;
- predicted unity-speed drift across the placed segment exceeds two timeline frames;
- the segment is too short to produce the MFCC/delta windows required by the configured analysis.

The timeline uses unity-speed source media. The mapped source start is used as the source in-point, and the source out-point is derived from the exact master segment duration. DTW is a locator and confidence mechanism, not a request to warp or resynthesize the performance.

When an unsafe automatic result still contains a concrete source in/out interval that fits the selected source occurrence at unity speed, its segment report includes `suggested_manual_offset_seconds = source_in_seconds - master_start_seconds`. This is an unverified review aid, not an automatic acceptance: analysis remains unsafe and `build` remains blocked until the user explicitly adds the value as a segment-specific manual override and reruns analysis. Failed or out-of-bounds locations have no suggestion. A segment search range for the same segment must be removed when replacing it with the suggested manual offset.

### 5.3 Audio decoding and cache

Use `ffprobe` to inspect media and `ffmpeg` to extract the selected audio stream to a mono analysis WAV when direct decoding is unavailable. Cache decoded audio and alignment results outside the repository. Cache keys include a fast content fingerprint plus stream index, source bounds, sample rate, feature settings, and application version. Writes are atomic; corrupt or incompatible entries are ignored and rebuilt.

## 6. Timeline construction

All validation and alignment completes before Resolve is mutated. On success, `build`:

1. creates a new empty timeline with the configured name;
2. appends contiguous master-audio segments to Audio Track 1 using the cut boundaries;
3. names and colors those audio items by logical take;
4. appends the selected multicam/video source ranges, video-only, to Video Track 1 at the corresponding absolute record frames only for `matched` segments;
5. adds a labeled timeline marker at every cut containing the outgoing and incoming take IDs and report segment IDs;
6. leaves every `not_provided` interval genuinely empty on Video Track 1—without filler clips or generated black—and verifies that video clips exist exactly for the matched intervals, with the intentional gaps matching the report;
7. verifies item count, boundaries, gaps, overlaps, track placement, names, colors, and markers through the API.

Time arithmetic uses `Decimal` seconds until the final conversion. Each absolute boundary is independently rounded to the nearest frame; segment durations are differences between adjacent rounded boundaries, preventing accumulated gaps. Source in/out conversion uses the source item's frame rate, while record placement uses the timeline frame rate. The master item's end supplies the final segment boundary.

Take colors are assigned deterministically from Resolve's supported palette using the high-contrast adjacency idea in the rough scripts. Color is presentation metadata only and never identifies a take.

If a failure occurs after timeline creation, the program attempts to delete only the timeline it created in that run and reports whether rollback succeeded. It never deletes pre-existing media or timelines.

## 7. Resolve sketch reference

Use these scripts as behavioral prototypes:

`/home/itaielidan/Insync/itaielidan@gmail.com/Google Drive/DaVinciResolve/scripts/`

The useful patterns are the recursive Media Pool search, native `CreateEmptyTimeline` and `AppendToTimeline` clip-info calls, explicit `recordFrame` placement, cut markers, segment naming, and high-contrast supported clip colors in `build_timeline_segments.py` and `01_arabesques_build_timeline_segments.py`.

Do not carry forward hard-coded Arabesques paths/timestamps, substring clip matching, a fake `999999` duration fallback, swallowed API errors, or the `pyautogui` workflow in `03_arabesques_auto_split_at_cuts.py`. The installed Resolve documentation at `/opt/resolve/Developer/Scripting/README.txt` is the API source of truth for the development machine.

## 8. Engineering constraints

- Python package with `src/` layout and Python 3.12 or newer for the external process.
- `uv` owns environments, dependency locking, and command execution.
- `ruff` owns formatting and linting; `ty` owns static type checking; `pytest` owns tests.
- Pre-commit runs repository hygiene checks, `ruff format --check`, `ruff check`, `ty check`, and the fast pytest suite through `uv`.
- Numerical and Resolve APIs are isolated behind typed project interfaces so unit tests do not require Resolve or real media.
- Logging is structured enough to associate every message with a configuration, source, segment, and run ID. User errors do not print tracebacks unless verbose mode is enabled.
- The CLI and report format are versioned public interfaces. Internal alignment parameters are centralized and recorded in each report.

## 9. Test and acceptance requirements

Every implementation task must add or update its own automated tests in the same change. The complete suite must cover:

- TOML and cut parsing, normalization, schema-version rejection, empty/partial/full source lists, rejection of unused configured sources, and every validation failure;
- exact decimal-to-frame behavior at integer and fractional frame rates;
- audio probing/extraction, mono conversion, cache invalidation, and corrupt-cache recovery;
- synthetic cross-microphone audio with filtering, gain, noise, leading silence, bounded multiple occurrences, repeated phrases, ambiguous candidates, and manual overrides;
- alignment boundary error at or below two timeline frames for accepted synthetic fixtures;
- deterministic edit-plan generation with continuous master audio, no video overlap, exact video clips for supplied takes, and explicit intentional video gaps for unsupplied takes;
- Resolve adapter behavior using strict fake API objects, including false/`None` returns and rollback;
- CLI exit codes, concise errors, deterministic JSON, all three video statuses, stale-report rejection, and zero Resolve mutation during validate/analyze;
- an opt-in live Resolve smoke test and an opt-in Arabesques acceptance run, both excluded from normal CI.

Required local gate:

```bash
uv sync --all-groups
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run pytest
uv run pre-commit run --all-files
```

V1 is accepted when all gates pass, every accepted synthetic alignment is within two timeline frames, an opt-in live partial-video build produces exactly one new timeline with continuous master audio and video only at supplied-take intervals, the master is the only audible program track, and a human can verify all Arabesques transition markers and take colors against the supplied cut list.
