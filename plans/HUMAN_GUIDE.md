# Multi-Cam Sync — Human Guide to the Plan

## What the program will do

You will prepare the master audio and whichever multicam recordings are currently available in DaVinci Resolve, then describe them in a small TOML file. The program will read your cut list, listen for each segment belonging to a supplied video take, and produce a review report. Once every requested match is trustworthy, it will create a new Resolve timeline with:

- the mastered audio, cut into continuous colored sections on Audio Track 1;
- matching video/multicam sections on Video Track 1 only for the takes you supplied;
- intentional empty video regions for every take you did not supply;
- markers at every transition;
- names and colors that make it easy to see which take supplies each section.

The camera's rough audio is used only for synchronization. It is not placed as the program soundtrack. Existing timelines and Media Pool items are left alone.

## What you will provide

There are three inputs:

1. The existing text cut list, such as `Arabesques_composite_cuts.txt`.
2. A TOML project file naming the master and only the logical take occurrences for which you want video.
3. An open Resolve project whose Media Pool already contains those items.

The source list may be partial. If the cut list uses nine takes but you provide video for only Take 2 and Take 8, every Take 2 and Take 8 area gets synchronized video and the other seven takes remain empty on Video Track 1. The program does not add black clips, placeholders, or warning titles; Resolve simply has no video item in those intervals. The master audio remains complete from start to finish.

The TOML mapping is important because filenames cannot reliably tell us what happened in a recording. If one recording contains “Take 8 A”, a break, and then “Take 8 B”, you can make two source entries that point to the same multicam clip and camera-audio file but give each entry its own start/end window. This prevents the matcher from confusing similar passages or selecting the wrong half.

If a Media Pool item is a virtual Resolve multicam clip and has no physical file path, its source entry also names one real camera file whose rough audio starts at the same point as the multicam item.

## How the difficult synchronization works

The master and camera microphones do not sound the same, so comparing raw waveforms is unreliable. Instead, the program converts both recordings into compact descriptions of their changing frequency content (MFCCs). It also compares how those descriptions change over time. These features are normalized so differences in microphone level and color matter less.

It then uses dynamic time warping (DTW) to locate a master segment inside the bounded camera recording. This is the same core idea that already works in your Elidan Take Picker project: MFCCs plus first/second deltas, cosine distance, and an asymmetric open-begin/open-end alignment. Here it is applied separately to each composite segment whose take has supplied video because the final master jumps between performances. Audio-only segments are not analyzed and are recorded as `not_provided`, which is a valid status rather than a failed match.

DTW is not used to bend the video. It finds the correct source in-point and measures whether the match is stable. The video remains at normal speed. If the camera clock has drifted enough to cause more than two frames of error across a segment, the program stops and asks for human correction instead of hiding the problem.

## Why there is an analysis step before building

Resolve changes are deliberately the last step. The workflow is:

```text
validate inputs → analyze audio → inspect report → build new timeline → verify timeline
```

For supplied takes, the report tells you which source occurrence won, its in/out positions, whether the answer came from cache or a manual offset, and why the program considers it safe or unsafe. Every master segment has a video status: `matched`, `unsafe`, or `not_provided`. The build command accepts `not_provided`, but refuses an unsafe requested match or stale results. If you change a media file or the configuration after analysis, you must analyze again.

This makes failures cheap: a typo or questionable match produces a report, not a half-edited timeline.

## How confidence and hard cases are handled

For a take whose video you supplied, the program blocks automatic building when:

- too little of the master segment was matched;
- the match leaves the source window you supplied;
- two candidate recordings score almost equally;
- moving the analysis edge by a tiny amount changes the answer by more than two frames;
- the predicted drift exceeds two frames;
- the segment is too short for meaningful audio features.

Repeated musical phrases are the main ambiguity risk. Narrow source windows are the best remedy. Use `[[sources.segment_search_ranges]]` with a stable `segment_id`, `source_start`, and `source_end` to narrow one source candidate without affecting its other segments. If one camera microphone is poor, add same-length, same-timeline recordings to `additional_audio_reference_paths`; they are tried in order only after the primary match is unsafe, and the chosen reference is visible in the report. For an exceptional case, enter source-wide `manual_offset_seconds`, or use `[[sources.segment_manual_offsets]]` to override only one segment while later segments of the same take remain automatic. The effective bounds, fallback reference, or manual override are never hidden in the report.

Not supplying video for a take never triggers these confidence errors. However, if you configure a video source and its match fails, the program will not silently omit it; you must fix its bounds/reference or use an explicit manual offset.

Master crossfades are another edge case. The analysis ignores a small amount at a segment's edges so the outgoing/incoming blend does not dominate the match, then extrapolates back to the exact cut boundary.

## How timeline accuracy is protected

The program performs time calculations in decimal seconds and converts only final boundaries to frames. It rounds every absolute boundary once and calculates a section's duration from its neighboring boundaries. That avoids one-frame gaps accumulating across many cuts. Audio Track 1 must always be continuous; Video Track 1 may contain gaps, but only the exact gaps declared by `not_provided` master segments.

The Resolve scripts you sketched already demonstrate the correct native building blocks: create a new timeline, append exact clip ranges with explicit record positions, add markers, and use supported colors. The production version generalizes those ideas and verifies all API return values. It will not use `pyautogui` or simulate razor shortcuts, because keyboard focus and user shortcuts make that approach fragile.

## What the implementation agents will build

The work is divided so each agent has a clear contract and its own tests:

1. project/tooling foundation with `uv`, Ruff, ty, pytest, and pre-commit;
2. TOML, cut-list, time, and report models;
3. media probing, audio extraction, and caching;
4. audio feature extraction, DTW matching, confidence, and overrides;
5. exact edit planning and frame conversion, including explicit intentional video gaps;
6. the Resolve adapter, timeline build, verification, and narrow rollback;
7. the CLI and end-to-end workflow;
8. system tests, disposable Resolve smoke test, Arabesques runbook, and final documentation.

Every task includes tests in the same change. A task is not considered complete if it only adds production code.

## What you should expect to review

The automated tests can prove time math, parser behavior, audio matching on controlled degraded recordings, edit-plan continuity, and correct Resolve API calls through fakes. They cannot judge whether a musical cut looks good or whether the intended camera angle is selected.

For the final Arabesques acceptance run, you will review:

- every marker against the cut list;
- whether every supplied take appears in all of its master segments and matches at each segment's start and end;
- whether unsupplied-take intervals contain no video item or generated filler;
- every low-confidence/manual segment called out by the report;
- the continuity of the master audio;
- the labeling and color grouping;
- that the multicam clips remain available for your later angle choices.

### Running the guarded acceptance workflow

The exact environment variables and commands are documented in the README under **Opt-in
live Resolve smoke test** and **Opt-in Arabesques acceptance**. The live smoke test requires a
separately named disposable Resolve project, a private partial-video configuration, an exact
new timeline name, a persistent report path, `MULTI_CAM_SYNC_LIVE_CONFIRM_DISPOSABLE=1`, and
`MULTI_CAM_SYNC_ALLOW_MUTATION=1`. The Arabesques run similarly requires explicit config,
report, current-project, and new-timeline values plus mutation authorization.

Both workflows perform validation, analysis, and report review before the one build call.
They stop before mutation when the current Resolve project or configured timeline differs
from the explicit environment values, when the target timeline already exists, when video
coverage is not partial, or when a supplied match is unsafe. A successful run intentionally
leaves the new verified timeline in Resolve and the JSON report at the requested path.

After a successful Arabesques run, inspect all 29 colored master-audio segments and all 28
markers. Scrub the beginning and end of every supplied-take video segment, confirm every
omitted-take span is genuinely empty on Video Track 1, confirm camera audio is absent from the
program tracks, record any manual offsets, and then unset `MULTI_CAM_SYNC_ALLOW_MUTATION`.

## Key choices and their consequences

- **No `.etp` input in V1:** its cached alignment is based on good-microphone/score inputs, not the camera rough audio that must be located here. The proven algorithm is reused directly instead.
- **No automatic retiming:** this avoids hidden visual artifacts. Drift beyond the tolerance becomes a review item.
- **No existing-timeline replacement:** a name collision is an error. This keeps every run recoverable.
- **Partial sources are valid:** omitted takes remain audio-only. A supplied take with an unsafe match still blocks the build so requested video is never silently lost.
- **No take-name inference:** the TOML mapping is a little more work for the video you do supply, but it correctly handles A/B takes in one recording and duplicate or misleading filenames.
- **External Python process:** it can use a modern locked environment through `uv` while still calling the Resolve API, and it is much easier to test than code pasted into Resolve's console.

## Reference material used

- Working alignment implementation: `/home/itaielidan/PycharmProjects/elidan-take-picker-workspace/main`
- Resolve timeline sketches: `/home/itaielidan/Insync/itaielidan@gmail.com/Google Drive/DaVinciResolve/scripts/`
- Installed Resolve scripting reference: `/opt/resolve/Developer/Scripting/README.txt`

The first two are design references, not runtime dependencies. The project will remain self-contained.
