# Take 1 native color trial

Historical trial: the settings below were superseded by the
[approved session recipe](../arabesques/COLOR_MATCHING.md) on 2026-10-09. Use that
recipe and its preset for new footage; retain this record for the earlier trial
and comparison timelines.

Performed in Resolve 21.0.2.4, project `Arabesques`.

This is a single-clip visual trial, not completed source-multicam matching.
The original `full timeline` was duplicated as `Take 1 color trial`.
Only `Take 1 — segment 026 - Video 1` in the duplicate received a new local
version, `Native match trial`. Video 3 and all other clips were left ungraded
by this operation.

Reference: `Take 1 — segment 028 - Video 3`, at `01:04:05:20`.
Trial comparison: `Take 1 — segment 026 - Video 1`, at `01:03:56:06`.
These are different performance moments, not synchronized camera samples.

Native `SetCDL` settings on node 1:

| Control | Value |
| --- | --- |
| Slope RGB | 1.01, 1.02, 0.97 |
| Offset RGB | 0, 0, 0 |
| Power RGB | 1, 1, 1 |
| Saturation | 0.93 |

The small adjustment was chosen by visual inspection to reduce the cooler,
more saturated appearance of Video 1 relative to Video 3. Resolve rendered
the correction; no external image transform or generated LUT was used.
The jacket and wall were visually inspected, without quantitative claims of
color agreement. Piano keys are not visible in the target framing and could
not be verified. Temporal validation and Video 2 matching remain outstanding.

Read-back confirmed the new grade version was active. An export of the original
timeline at the target timecode was byte-identical to the ungraded trial export,
and the original retained `Version 1`. The trial was left open at `01:03:56:06`
for review. Select `Version 1` on this trial clip for the before view.

The API initially returned `full timeline` while the UI was navigating nested
multicam contents. Seeking then returned success without changing the reported
timecode, producing unreliable exports. Explicitly selecting the duplicate
using `SetCurrentTimeline` resolved this for the trial. Always verify the actual
timecode and current item before using an exported frame as grading evidence.

Temporary Resolve-rendered PNGs are under `/tmp/take1-color-ty_q8aui/` and may
disappear when temporary storage is cleaned. No explicit project save was issued.

## Playback comparison

Created `Take 1 - matched vs original - Video 3 reference` on request, at 24 fps,
12 seconds long. Left: the same three-second Video 1 excerpt, matched for seconds
0–3 and 6–9, original for seconds 3–6 and 9–12. Right: the same unchanged
three-second Video 3 reference excerpt throughout. Reference and target show
different performance moments. This comparison is silent.

The comparison nests source ranges from the trial and original timelines to
preserve the selected multicam angles and native grades. Each panel uses 0.5
zoom, with horizontal positions -480 and +480 on the 1920-wide canvas. Four
timeline markers label the sections, and the two video tracks identify the sides.
Rendered matched/original frames were visually checked for the correct layout;
read-back verified four clips per video track and a 288-frame duration. The
comparison is left selected at its start. Failed intermediate/probe timelines
were deleted; existing user timelines were preserved.

## Warmer wall revision and hands camera

Following user review, the Video 1 trial now uses local version `Warmer wall
match`: slope RGB `1.055 1.015 0.90`, offset `-0.008 -0.008 0.005`, power
`1 1 1`, saturation `0.96`. This replaces the active trial grade, retaining
the earlier versions. The wall is warmer; final aesthetic acceptance is pending.

The comparison now lasts 24 seconds. Seconds 12–24 add the Take 1 hands camera,
selected by exact Media Pool name `Take1 | 2 - 00002.mov` in `finished` and
visually confirmed as the keyboard close-up. This is used as the Video 2 example;
the nested multicam's track mapping remains unavailable through the API.
Source frames 7800–7890 at 29.97 fps produce 72 timeline frames at 24 fps.
The same excerpt alternates matched/original at 12, 15, 18, and 21 seconds.
The Video 3 excerpt continues on the right, from a different performance moment.

Matched hands-camera instances use local version `Video 2 warm match`: slope
`0.96 0.94 0.89`, offset `-0.008 -0.008 0.005`, power `1 1 1`, saturation
`1.03`. This revision reduces the green shadow cast observed in the first
hands-camera trial. Corrections remain native Resolve CDL operations.

Read-back verified eight comparison clips per video track, eight markers, and
576 frames. Refined rendered frames were exported at verified timecodes
`00:00:01:00` and `00:00:13:00`; the comparison was then rewound. Keys are visible
in the hands camera, but clipped source highlights cannot be recovered by this
grade. These are visual trial matches, not quantitatively certified matches.
