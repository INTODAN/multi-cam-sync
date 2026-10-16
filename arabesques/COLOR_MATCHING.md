# Arabesques session color matching

Use this recipe for additional footage from the same Winter Recording session 2025,
camera session 2. The user approved the initial primary match, then requested a
manual refinement because the jacket looked too dark in the hands shot.

The current hands grade is **Manual refine v2 2026-10-09**, applied to Take 1,
Take 8, Take 9, and the shared Take 2, 6, 7 multicam in Resolve Studio 21.1.1.10.
It lifts fabric detail, strengthens the navy color, and softens the brightest keys.
The same hands refinement was checked on all four takes. A later comparison of
the face shots at 1:48 and 2:13 revealed a warmer Take 9 despite identical face
settings. A subsequent review of all cameras also identified a warmer Take 9
wide shot. Take 9 now has the separate face and wide balances documented below;
the other face and wide grades retain their previous corrections. These
refinements are ready for user review; the previously approved versions remain
available.

The current Take 9 wide version is **Take 9 wide v2 2026-10-10**. The user
identified a residual mismatch after the first wide balance, so the earlier
"consistent overall" assessment should not be treated as approval of that match.

The reusable values are in [color-match.toml](color-match.toml). This is a reference
preset for manual or assisted Resolve grading; the `multi-cam-sync` CLI does not
read it or apply color grades during a timeline build.

Use the [Review Multicam Color skill](../.agents/skills/review-multicam-color/SKILL.md)
to assess the result across takes, camera angles, and timeline cuts, with close
checks of the jacket, skin, walls, keys, and shadows.

## Approved primary-match baseline

Enter these absolute values on the camera source clip's node **01**, under
**Color → Primaries - Color Wheels**:

| Camera | Temperature | Tint | Contrast | Treatment |
| --- | ---: | ---: | ---: | --- |
| Face | 350.0 | -2.0 | 1.035 | Starting point; Take 9 override below |
| Hands | 500.0 | -1.0 | 1.045 | Baseline within the hands refinement |
| Wide | — | — | — | Default reference; Take 9 override below |

Temperature is Resolve's primary adjustment value, not a camera white-balance
reading in Kelvin. Set the fields to these values; do not add them to existing
values or stack another copy of the correction.

Only these three controls changed in the initial baseline. The clips started with neutral
grades; pivot remained `0.435`, saturation `50.000`, and the other controls stayed
unchanged. No Shot Match, additional LUT, CDL correction, or secondary correction
was used for this approved recipe. The earlier CDL experiments in
[Take 1 native color trial](../plans/TAKE1_COLOR_TRIAL.md) are historical and should
not be combined with this preset.

Keep the existing project's color management and input interpretation when using
the recipe. For new media with a different input transform, camera profile, or
existing grade, compare its baseline with the approved clips before reusing the
numbers. The preset is the starting point for this session; a changed exposure or
white balance may require a new local version with a documented adjustment.
Footage from the same recording session still needs a visual comparison between
takes; identical control values do not guarantee matching color.

## Take 9 face balance

The user noticed a mismatch between the face shots at **1:48 (Take 8)** and
**2:13 (Take 9)** in `full timeline`. Read-only project inspection confirmed that
all four multicams had the identical face correction modules: Temperature `350`,
Tint `-2`, Contrast `1.035`. The two outer cuts had no additional correction, and
their source input settings matched. Take 9 nevertheless rendered warmer. The
cause of that source difference was not established; the earlier claim that no
take-specific adjustment was needed was too broad.

Inside **Take 9 Multicam**, the face source **Take 9 - 2 - 00021.mov** now uses
local version **Face balance Take 9 2026-10-09**. On node **01**, set these
absolute Primaries values:

| Control | Previous | Current |
| --- | ---: | ---: |
| Temperature | 350.0 | 0.0 |
| Tint | -2.0 | -2.0 |
| Contrast | 1.035 | 1.035 |
| Master Gain | 1.00 | 0.98 |

RGB Gain stays `[1, 1, 1]`; other controls remain unchanged. This reduces the
extra warmth and slightly lowers brightness for a closer match to Take 8. It is
a Take 9 exception, not a replacement face preset for the entire session.
The previous **Camera match 2026-10-09** version remains available.

The revised face grade was reviewed at 65, 155, and 260 seconds in Take 9 and
against its other camera angles. In the full timeline, the exported frame at
`01:02:13:12` exactly matched the refined internal camera frame at `00:02:20:20`.
The reference frame at `01:01:48:00` was unchanged. Reloading the old Take 9
version reproduced the original comparison frame pixel-for-pixel.

The saved project comparison verified unchanged edit/audio structure across all
11 sequences, preservation of all 136 previous grade versions' corrections, and
exactly one new version on the Take 9 face source. Neutral UI serialization
updates are listed separately in the report. Local evidence and before/after
project backups are in `reports/take9-face-balance-20261009/`.

## All-camera review and Take 9 wide balance

After the user asked whether every take had been checked, the current grades
were reviewed across **all four multicams and all three cameras**. The review
used 36 fresh native source frames: face, hands, and wide at three positions per
multicam, including the Take 2, 6, and 7 sections of their shared source. It also
checked one midpoint frame from **every one of the 46 edited shots** in
`full timeline`. Sample timecodes are recorded in the local report.

Take 1, Take 8, and the shared Take 2/6/7 source showed no additional material
mismatch in these sampled views. Take 9's revised face balance was retained,
and its hands grade remained consistent with the other hands views. Its wide
camera still appeared warmer and slightly brighter than the other wide takes.

The first correction on wide source **Take 9 - 2 - 00066.mov** was local version
**Wide balance Take 9 2026-10-09**: Temperature `-350.0`, master Gain `0.98`,
Tint `0`, Contrast `1.000`, RGB Gain `[1, 1, 1]`, and other controls neutral.
This version and the neutral **Version 1** remain available. The current
replacement is described below.

The revised wide balance was checked at 65, 155, and 260 seconds. Its full-timeline
frame at `01:02:31:19` matched the internal camera frame at `00:02:39:04`
pixel-for-pixel. The old version reproduced its original comparison frame
exactly. Re-exporting all 46 timeline samples changed only the Take 9 wide shot;
the other 45 samples were pixel-identical. The last wide shot's existing fade to
black was checked separately and retained.

The saved project comparison verified unchanged edit/audio structure across all
11 sequences and preservation of 137 existing versions' corrections. Resolve
added the new wide correction version and materialized its previously implicit
neutral original as `Version 1`. Neutral serialization updates from visiting
Color controls are recorded separately.

Local evidence is in `reports/all-camera-review-20261009/`, including
`all-takes-final.jpg`, per-take camera sheets, per-camera sheets of all edited
shots, native frames, `verification.json`, and project backups. These results
describe a sampled still-image review. Small differences from pose, framing,
and local lighting remain; matching control values or these samples alone does
not establish identical color throughout every frame. The adjusted versions
are saved and ready for user review.

### Take 9 wide v2, 2026-10-10

The user noticed that the wide shot still differed. Larger comparisons confirmed
extra brightness, pinker skin highlights, and more yellow in the wall/floor.
The first correction helped, but the previous overall-consistency assessment
was too broad. Inspect large same-camera comparisons and subject crops alongside
contact sheets before calling a match satisfactory.

The active version is now **Take 9 wide v2 2026-10-10**. Set these absolute
values on the existing node **01**, under Primaries - Color Wheels:

| Control | Previous wide balance | Current v2 |
| --- | ---: | ---: |
| Temperature | -350.0 | -400.0 |
| Tint | 0.0 | -4.0 |
| Master Gain | 0.98 | 0.97 |
| Saturation | 50.0 | 48.0 |

Contrast stays `1.000`, RGB Gain `[1, 1, 1]`, and other controls remain unchanged.
This is an absolute replacement of the primary values in a new local version,
not another correction to append to the previous wide grade. It applies only
to this Take 9 wide source.

Three balances were compared with Take 1, Take 8, and the shared Take 2/6/7
wide references. The selected version reduced the residual brightness and pink
tint while retaining the room's warmth. It was preferred in larger visual
comparisons and also had the lowest average RGB difference across seven sampled
background patches among the trials. Those patch statistics are supporting
observations, not a calibrated color-accuracy measurement; local lighting and
pose differences remain. The result is a closer match, ready for user review.

The version was checked at 65, 155, and 260 seconds inside Take 9. Its frame at
`00:02:39:04` matched the full timeline at `01:02:31:19` pixel-for-pixel. Reloading
the previous wide balance reproduced the previous comparison frame exactly.
Project exports verified unchanged edit/audio structure across 11 sequences,
preservation of all 139 previous grade versions, and exactly one new version on
the Take 9 wide source. Other grades remain unchanged.

Local evidence and backups are in `reports/take9-wide-v2-20261010/`, including
`comparison.jpg`, `three-position-review.jpg`, the trial images, and
`verification.json`. The older all-camera review sheets retain the first wide
balance and are historical evidence, not the current v2 appearance.

## Current hands refinement

The reusable native grade is
[session2-hands-manual-v2.drx](grades/session2-hands-manual-v2.drx), with its
[Gallery reference image](grades/session2-hands-manual-v2.jpg). Keep the pair
together. In the Color page's Gallery, choose **Import**, select the reference
image with its matching DRX beside it, and apply that still to a new hands-camera
local version. The saved project also has a **Session 2 manual v2** album containing
**Session 2 hands - Manual refine v2 FINAL**.

This is the **complete three-node hands grade**, including the primary baseline.
Apply it once to replace the new version's grade; do not append it to an existing
match. Never apply the hands grade to the face or wide camera.

| Serial node | Purpose | Settings |
| --- | --- | --- |
| 01 | Existing primary match | Temperature `500`, Tint `-1`, Contrast `1.045` |
| 02 | Navy color and highlight shoulder | ColorSlice Blue Density `-0.50`, Blue Saturation `1.10`; Custom Curves Soft Clip, linked RGB, High Soft `30.0` |
| 03 | Fabric detail within a soft left-side window | Primaries master Gamma `0.04`, Saturation `60.0`; soft luminance qualification and rectangular window below |

On node 02, ColorSlice Blue Center and Hue remain `0`, and other slices/global
controls stay at defaults. Soft Clip Low and High remain `50`, Low Soft remains
`0`. Primary Gain is neutral and Highlights is `0`: the tested global highlight
reduction was discarded because it made the keys too yellow and dimmed the hands.
Other curves have no tonal adjustment. Soft clipping reduces glare; it does not
reconstruct detail lost in the camera.

On node 03, leave Hue and Saturation qualifier ranges fully open. Set Luminance
Low `0`, High `62`, Low Soft `0`, High Soft `12`; Matte Finesse Pre-Filter `5` and
Blur Radius `8`, with other matte controls at defaults. A hue-only selection was
discarded because it made deep fabric folds uneven. The final tonal selection
keeps those folds smooth.

Use a **Linear rectangular Power Window with its default corner geometry**:
Size `50`, Aspect `12.5`, Pan `40.6`, Tilt `50`, Rotate `0`, Opacity `100`, and
Soft 1–4 all `4`. It covers the jacket on the left while excluding the large piano
surface on the right. This window is static, with no tracking or keyframes. It
was checked at three positions per take. For new framing, inspect the window
through the performance and reposition or track it if the jacket moves outside
the soft boundary. Window numbers are Resolve control values, not percentages of
image width.

All values are recorded in [color-match.toml](color-match.toml); the native DRX
also preserves the node graph and window exactly. Preserve the project's color
management when reusing the qualifier thresholds.

## Identify the camera

The current multicams are in **Master/multicams**. Their native track mappings are:

| Exact Media Pool name | Face | Hands | Wide |
| --- | --- | --- | --- |
| `Take 1 multicam` | Video 1 | Video 2 | Video 3 |
| `Take 8 Multicam` | Angle 3 | Angle 2 | Angle 1 |
| `Take 9 Multicam` | Video 2 | Video 1 | Video 3 |
| `Take 2,6,7 Multicam` | Angle 3 | Angle 2 | Angle 1 |

Identify future clips by the visible framing and source identity. Track numbers
and Color-page thumbnail order vary. Source folder names can help: `itai Elidan
session 2 face`, `Itai Elidan 2nd session hands`, and `Itai Elidan session 2 long
shot`. Resolve an exact bin and item name, then retain its media ID for that run;
do not select a similarly named trial timeline by substring.

## Apply to new multicam footage

1. Confirm the intended project and new multicam. Export a project backup to an
   ignored local location such as `reports/`, and record the existing timeline
   clip counts, source references, in/out points, angle selections, and audio
   timing for the final check.
2. Right-click the shared multicam in the Media Pool and choose **Open in
   Timeline**, then open the **Color** page. Grade the camera clips inside this
   multicam so every edit using that same multicam receives the correction.
3. Enable **Unmix** in the viewer to inspect the selected internal camera clip.
   Select a camera thumbnail and seek to a moment where that camera has actual
   footage. Confirm the viewer shows the intended camera and timecode. Camera
   starts can be offset, so select a moment covered by all cameras for comparison.
4. For each new face or hands source clip, preserve the original local version.
   From its thumbnail menu, choose **Local Versions → Create New Version** and
   name it `Camera match YYYY-MM-DD` for face or `Manual refine v2 YYYY-MM-DD`
   for hands. The completed clips retained `Version 1`
   as their uncorrected version. If the clip is already matched, inspect the
   active version and values instead of applying another correction.
5. For face, select node **01** and enter the baseline primary values; check
   whether the exact source has a documented per-take override. For hands,
   apply the complete native refinement still, or build the three serial nodes
   described above. Confirm the controls and window after application. Keep the
   wide source unchanged unless a documented per-take override applies or the
   comparison identifies a mismatch requiring a separate local version.
   If an angle contains several source clips, handle each source clip once;
   grading one clip does not automatically grade newly appended clips.
6. Compare corresponding performance moments near the beginning, middle, and end
   of the available footage. Inspect skin, the blue jacket, comparable wall areas,
   white keys, and shadow detail against the wide reference and an approved take.
   Use RGB parade/waveform alongside the images. Check highlight clipping and
   visible jumps at camera changes. Record any extra adjustment in a separate
   version so the session preset remains reproducible.
7. Return to **full timeline** and inspect rendered frames from the edited face
   and hands shots. Verify that every intended occurrence references the shared
   multicam you graded, and that clip placement, trims, angle choices, and audio
   timing match the starting snapshot. Save the project and record the new
   source names, active versions, settings, and sample timecodes.

Edits using the **same shared multicam** inherit these internal grades. A new
independent multicam, newly added internal source clip, or separate direct use of
the media needs its own check and application. This workflow uses local grades on
the internal clips, not a global camera preset attached automatically to imports.

## MCP and desktop workflow

The successful workflow combined the official Resolve MCP for inspection, native
frame exports, project backup, and saving with Resolve's native desktop Color-page
controls for the actual adjustments. It did not require the community MCP.

In the tested Resolve 21.1.1 session, the scripting API continued to expose the
parent `full timeline` while the UI was inside a multicam. Calls such as
`project.GetCurrentTimeline()`, `resolve.GetCurrentTimeline()`, and
`MediaPoolItem.GetTimeline()` did not provide reliable access to its internal
camera clips. A successful `SetCurrentTimecode()` call on the parent did not prove
that the nested viewer moved to that position.

For nested multicams, verify the native UI selection and seek through the visible
viewer timecode. `project.ExportCurrentFrameAsStill(path)` successfully exported
the selected nested angle with Unmix enabled; inspect the exported image rather
than treating the return value as visual proof. After returning to the real parent
timeline, API seeking and `GetCurrentVideoItem()` were useful for checking edited
shots. Recheck the installed scripting documentation and available MCP tools when
working with a different Resolve version.

Desktop automation must inspect the current window position, monitor, UI scale,
field positions, and active dialog. The layout changed during this work; saved
pixel coordinates and temporary helpers are not a reusable preset. Do not edit
exported project internals to apply grades. Project exports were only inspected
read-only to verify preserved versions and timeline structure.

Confirm Resolve has desktop focus before sending native input. During the Take 9
check, input calls returned successfully while Resolve was inactive and its
controls did not change. Activating the Resolve window restored control. Verify
the visible field values, timecode, and exported frame after an adjustment;
an automation return value alone does not establish that the grade changed.

## Completed work and local evidence

| Multicam | Current face version | Current hands version | Occurrences in full timeline | Reviewed offsets from multicam start |
| --- | --- | --- | ---: | --- |
| Take 1 | `Take 1 - Camera match 2026-10-09` | `Manual refine v2 2026-10-09` | 5 | 60, 180, 270 seconds |
| Take 8 | `Camera match 2026-10-09` | `Manual refine v2 2026-10-09` | 23 | 135, 275, 425 seconds |
| Take 9 | `Face balance Take 9 2026-10-09` | `Manual refine v2 2026-10-09` | 8 | 65, 155, 260 seconds |
| Take 2, 6, 7 | `Camera match 2026-10-09` | `Manual refine v2 2026-10-09` | 10 | 115, 420, 715 seconds |

Counts and mappings describe the saved project on 2026-10-09. Take 8 and
Take 2, 6, 7 started at `01:00:00:00`; Take 1 and Take 9 started at `00:00:00:00`.
The listed sample offsets are relative to those starts, not absolute source-file
timecodes.

The hands refinement was reviewed in twelve native-rendered samples and in full-timeline
hands shots at `01:00:21:11` (Take 2, 6, 7), `01:00:31:04` (Take 8), and
`01:02:20:22` (Take 9). The current edit uses only face/wide from Take 1, but its
shared hands source also has the refinement for future angle changes.

Read-only project comparisons verified unchanged edit/audio structure across all
11 sequences and preservation of 132 existing grade versions' corrections.
Exactly four new hands versions were added. Their three nodes' correction data
match each other and the exported DRX. Opening Color palettes also initialized
neutral serialization fields in ten existing versions; those are recorded
separately in the verification report. The three affected previous hands versions
were reloaded and their rendered comparison frames matched the before images
pixel-for-pixel. The previous Take 1 hands version's stored body was unchanged.

The project was saved with the refinements active. Hands-refinement evidence is in
`reports/manual-refinement-20261009/`: before/after comparisons, twelve sampled
hands frames, full-timeline frames, the verification report, and project backups.

Local evidence is under the git-ignored directories
`reports/take1-color-20261009/` and `reports/multicam-color-20261009/`. They contain
settings/verification JSON, image comparisons, and project backups. These artifacts
may be absent in a fresh checkout; the preset and this guide contain the reusable
instructions without requiring private media paths or temporary files.

## AI comparison

On 2026-10-09, Resolve Studio 21.1.1.10's Neural Engine Auto Color and Shot Match
were tested on Take 1 in separate local versions. **Keep the approved manual
preset for this session**: it was preferred for the warmer wall, restrained navy
jacket, and more consistent skin tones across cameras. This is a visual preference
based on the sampled footage, not a measurement of absolute color accuracy.

Both **Use legacy auto color** and **Use legacy shot match** were unchecked in
**Preferences → User → Color**. The AI operations analyzed `00:03:00:00` once;
their resulting static grades were compared with identical native-rendered frames
at `00:01:00:00`, `00:03:00:00`, and `00:04:30:00`. Other takes were not AI-graded
in this comparison.

| Method | Starting point and reference | Observed result |
| --- | --- | --- |
| Approved manual | Saved face/hands settings; wide unchanged | Preferred warmth and camera continuity |
| Auto Color | Original versions of all three cameras; click **A** in Primaries | Brighter, cooler face image and stronger blue jacket; cooler wide shot |
| Auto Color then Shot Match | Auto Color on all cameras, then match face/hands to the Auto Color wide | Less intense than Auto Color alone, but cooler/paler skin and hands than the approved look |
| Shot Match to current wide | Original face/hands matched directly to the unchanged wide | Closest AI option to the intended warmth, but the face-camera wall became much brighter and the jacket shifted toward purple |

The Auto Color then Shot Match order follows the installed reference manual's
automated grading workflow. For Shot Match, select the target camera, right-click
the wide reference thumbnail, and choose **Shot Match to this Clip**. See also
[Blackmagic's automatic balancing and matching overview](https://www.blackmagicdesign.com/products/davinciresolve/color).

The AI alternatives remain available inside **Take 1 multicam**:

- `AI Auto Color 2026-10-09`: face, hands, and wide.
- `AI Shot Match 2026-10-09`: face and hands after Auto Color plus Shot Match;
  use the wide's `AI Auto Color 2026-10-09` version to review this camera set.
- `AI Match Wide 2026-10-09`: face and hands matched directly to the original
  wide; use the wide's `Version 1` to review this set.

At the end of the AI test, before the later manual refinement, face/hands were restored to
`Take 1 - Camera match 2026-10-09`, and the wide was restored to `Version 1`.
Rendered pixels at `00:03:00:00` matched the pre-test images exactly for all three
cameras. Project-export comparisons verified that all 124 pre-existing local
grade versions and all 11 sequences' edit/audio structure were preserved, and
unrelated grades were unchanged. The project was saved with the approved grades
active. The subsequent manual v2 pass changed only the hands grade. Later passes
added the separate Take 9 face and wide balances. The AI alternatives remain
preserved.

The local, git-ignored `reports/ai-color-comparison-20261009/` directory contains
three comparison sheets (`comparison-60.jpg`, `comparison-180.jpg`, and
`comparison-270.jpg`), the JSON report, the checked preferences, and project
backups. Each sheet shows the four methods in the table's order, with face, hands,
and wide on separate rows.
