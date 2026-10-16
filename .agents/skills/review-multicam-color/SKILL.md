---
name: review-multicam-color
description: Assess and refine DaVinci Resolve multicam color consistency when grading, comparing takes or camera angles, or investigating a reported color mismatch. Review rendered images, important subject and background areas, and continuity in the edited timeline.
---

# Review Multicam Color

Judge the rendered appearance against the intended look. Identical settings,
same-session footage, a successful MCP call, or an automatic grade do not establish
a visual match. A technically applied correction can still look wrong.

## Establish the scope and reference

- Start a reported mismatch at the exact cuts or timecodes the user identified.
  Identify their actual source takes and cameras before diagnosing the difference.
  Broaden the comparison as needed to understand the issue and check regressions.
- For an all-takes review, inventory every distinct multicam, internal source clip,
  and camera angle used by the edit. Include the wide camera. A combined multicam
  containing several performances needs samples from each performance section.
- Record active local versions and choose a stable reference the user liked.
  Preserve the intended warmth and contrast; do not assume that cooler, brighter,
  more saturated, or AI-assisted grading is better. Use the same review criteria
  for manual corrections, Auto Color, Shot Match, and LUTs.
- For Arabesques, read the current [session guide](../../../arabesques/COLOR_MATCHING.md)
  and [preset with per-take overrides](../../../arabesques/color-match.toml).
  They hold settings and source mappings; avoid duplicating those changing values
  in this skill. Old report images may show superseded versions.
- Inspection and applying a new correction are separate task scopes. Use existing
  session authorization for refinements; a review-only request should produce a
  finding without silently changing the grade.

## Build trustworthy comparisons

Export native Resolve frames with consistent color management and output settings.
Record source identity, camera, version, and timecode. For before/after comparisons,
use the exact same source frame, framing, and viewing size. Keep reference pixels
intact when assembling sheets or crops.

Use a contact sheet to find candidates, then inspect large paired frames and
detail crops. Small thumbnails hid the remaining Take 9 wide mismatch in the
Arabesques review; a complete grid alone is insufficient evidence of a good match.
Confirm references still correspond to the current or deliberately preserved grade.

Review three relationships:

| Comparison | What to hold comparable | What to check |
| --- | --- | --- |
| Same angle across takes | Camera/framing, similar pose, corresponding surfaces | Exposure, tint, saturation, jacket density, and background color |
| Different angles within a take | Corresponding performance moment where each camera has footage | Continuity of skin, hands, jacket, room warmth, shadows, and highlights |
| Adjacent shots in the finished edit | Actual selected angles and frames around the cut | A visible brightness or color jump, including after returning from another angle |

Early, middle, and late positions are a useful starting sample. Add positions around
reported problems, source changes, lighting changes, and moving subjects/windows.
For a comprehensive review, account for every edited shot, then inspect suspect cut
boundaries closely. Treat existing fades separately from grading mismatches.
Use playback or scrubbing when assessing temporal behavior; stills alone cannot
establish that a qualifier or window holds through motion.

## Inspect the areas the viewer notices

| Area | Evidence of a good match | Problems to look for |
| --- | --- | --- |
| Jacket and other clothing | Consistent intended navy/hue, density, fold and fabric detail | Crushed folds in the hands angle, purple/cyan shifts, lifted gray blacks, excessive saturation, uneven masks |
| Face and hands | Plausible skin hue and brightness across angles and takes | Pink/magenta or green cast, pale highlights, excessive warmth, skin damaged while matching the wall |
| Walls and neutral surfaces | Comparable room warmth, tint, and brightness on the same surface | Yellow/green/pink shifts or a brighter background that makes a take stand out |
| Piano keys and bright reflections | Compatible highlight color and roll-off with available detail | Clipping, glare, yellow keys, or dim hands after a global highlight reduction |
| Piano body and deep shadows | Consistent black level while retaining useful separation | Crushed detail, muddy or washed-out blacks, color contamination, halos |

Inspect the whole image again after every targeted improvement. A lighter jacket
does not compensate for worse skin or keys, and a matching wall does not establish
that the subject matches. A face-camera fix does not validate the same take's wide
or hands camera. Allow for pose, framing, reflections, and actual local lighting;
do not use them as an unexamined explanation for a reported discrepancy.

Use RGB parade, waveform, and vectorscope where available to support the visual
assessment. Patch statistics can help compare trials when the patches depict
equivalent surfaces under comparable light. Fixed pixel coordinates may sample
different content after framing changes. Whole-frame averages, a lower RGB error,
or identical controls cannot serve as an automatic pass criterion. Do not invent
a camera-white-balance or lighting explanation without evidence.

## Refine and verify when authorized

Preserve the current version and project state before changing a grade. Make a
separate local version on the intended internal source clip; document per-take
exceptions instead of changing an otherwise satisfactory session preset. Set
absolute values or replace a complete grade as intended; avoid stacking duplicates.

Compare each candidate with both the previous version and the stable reference.
Evaluate temperature, tint, exposure, contrast, and saturation separately enough
to understand the tradeoff. Use a selective correction when a global adjustment
harms already satisfactory areas. Check qualifiers/windows through the relevant
motion, including folds and soft boundaries, before reusing them on other takes.

For API operations, also follow [script-davinci-resolve](../script-davinci-resolve/SKILL.md).
Confirm the visible clip, timecode, active version, and control readback. In this
Resolve workflow, the API could expose the parent timeline while the UI was inside
a multicam, and native input could succeed without Resolve having focus. A tool
return value alone proves neither selection nor the applied appearance.

Re-export the chosen result at the sampled positions and inspect the actual edited
shots that use it. Verify that the shared multicam propagates the intended grade,
the old version remains available, and unrelated grades, trims, angles, and audio
timing are preserved. Pixel equality is useful for unchanged frames or the same
frame rendered through source and parent; it is not a matching goal across takes.
Save the project and record the active version and absolute settings.

If candidates do not reliably improve the comparison, retain or restore the prior
version and report the unresolved difference. Stop speculative tweaking once the
targeted issue and relevant regressions have been assessed; further changes should
respond to observed problems or user feedback.

## Make a bounded assessment

Before calling the result satisfactory, check that the requested take/angle scope
is covered, important areas were inspected at useful size, and the change holds
in the relevant timeline shots. Revisit a user's reported difference even after
a previous pass; do not defend a match using version counts or applied settings.

Report visual findings separately from application verification. State the takes,
angles, and timecodes sampled, the reference used, remaining differences, and any
unreviewed coverage. Distinguish sampled stills from continuous playback. Use
"closer in the reviewed frames" when that is the evidence; avoid claiming exact
consistency or that every frame was checked.

Save labeled comparisons and a compact record of source/version, reference,
samples, area findings, changes, and remaining issues. In this repository, keep
private media evidence and project backups under ignored `reports/`, and maintain
reusable settings and instructions in the session guide/preset. Distinguish
**applied and verified**, **visually preferred/provisional**, and **user-approved**;
the assistant's assessment does not create user approval for a new refinement.
