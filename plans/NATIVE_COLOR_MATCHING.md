# Native Resolve multicam color matching

Status: historical workflow proposal. Native source-multicam matching was completed
and visually checked on 2026-10-09. Use the
[approved session recipe](../arabesques/COLOR_MATCHING.md) and
[camera preset](../arabesques/color-match.toml) for future footage. The final recipe
used primary controls rather than the Shot Match procedure proposed below;
automated grading in the application is not implemented.

## Take 1 target

The live read-only inspection found project `Arabesques` and Media Pool item
`Master/multicams/Take 1 multicam`. Match the clips on Video 1 and Video 2 to
Video 3 inside that multicam. Track-to-camera identities must be checked in the
opened multicam before applying any grade; the underlying tracks were not
exposed by the project's ordinary timeline list during inspection.

Use Resolve's native Color-page tools for correction. Do not introduce a Python
image-processing pipeline or generated matching LUTs. Scripting may discover
media and inspect state, but must not claim that copying a grade performs shot
matching or that an API success verifies the resulting colors.

## Grading workflow

1. Open the multicam using **Open in Timeline** from its Media Pool context
   menu. Identify Video 1, Video 2, and Video 3 by their actual source clips.
   Preserve the existing grades using local versions or saved Gallery stills
   before changing the two target angles. Check whether remote grades or shared
   nodes would propagate changes to other clips.
2. Confirm each camera's input color space and the project's color management.
   Normalize camera log footage using Resolve's input transforms before
   comparing it. Do not assume that every camera uses the same transfer curve.
3. On the Color page, view individual source angles rather than the multicam
   composite. Choose a corresponding performance moment with visible jacket,
   wall, and keys. Save a reference still from Video 3 for comparison.
4. Select the target angle's clip thumbnail, right-click the Video 3 reference
   thumbnail, and choose **Shot Match to This Clip**. Repeat for the other
   target. The selected clip receives the match; the right-clicked clip supplies
   the reference. Treat automatic matching as a starting point for refinement.
5. Use native primary controls to align exposure and color balance. Compare with
   the reference still using a wipe or split screen. Refine the jacket with
   native hue curves or qualified secondary nodes when primary adjustments
   cannot align it without shifting the wall or keys. Inspect qualifiers for
   spill, edge artifacts, and temporal instability; track any needed windows.
6. Inspect matching performance moments near the beginning, middle, and end of
   the take. If lighting or automatic camera white balance changes, one static
   correction may not suffice. Use native keyframes or separate corrections
   only where inspection demonstrates a need.

## Required color checks

Compare corresponding diffuse surfaces; framing, shadows, reflections, and
specular highlights can differ legitimately between cameras. Full-frame scope
distributions are not object-by-object comparisons.

| Subject | Check against Video 3 | Failure to look for |
| --- | --- | --- |
| Blue jacket | Hue and saturation with comparable fabric illumination; preserve folds | Cyan/purple drift, oversaturation, crushed fabric detail |
| Wall | Same wall area under comparable lighting, including its intended warm/cool tint | Green/magenta cast, exposure mismatch, forcing a colored wall to neutral |
| White piano keys | Diffuse key surfaces, highlight detail, RGB balance relative to the reference | Channel clipping, tinted whites, loss of separation between keys |
| Black piano keys | Shadow level and retained detail relative to the reference | Crushed blacks or lifted gray shadows |

Use RGB parade/waveform for channel balance and luminance and the vectorscope
for hue/saturation, alongside the visual comparison. Isolate comparable regions
when reading scopes. Do not attempt to recover clipped source detail by simply
raising or lowering a grade. Check additional frames that were not used for the
initial match and check the final edit for visible jumps at angle changes.

Record the reference and target source names, inspected timecodes, changed
native grade versions/nodes, per-subject results, and remaining mismatches.
Never mark the take verified solely because Shot Match completed.

## Automation boundary observed in this environment

Resolve's installed scripting reference documents `TimelineItem.SetCDL`,
`Graph.SetLUT`, and `Graph.ApplyGradeFromDRX`, but does not document a native Shot
Match invocation or general access to Color-page primary/secondary controls.
The initial inspection had no connected desktop tool for driving Resolve. The
later completed workflow combined the official MCP with native desktop control
to apply the primary settings. The API still exposed the parent timeline while
the UI was inside a multicam; see the approved session recipe for the verified
workflow and its limitations.

## References

- [Blackmagic Design Color-page overview](https://www.blackmagicdesign.com/products/davinciresolve/color)
  describes native Shot Match and grading tools.
- [Blackmagic Design Colorist Guide](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-17-Colorist-Guide.pdf)
  explains Shot Match selection direction and reference comparisons.
- [Blackmagic Design Editor's Guide](https://documents.blackmagicdesign.com/UserManuals/DaVinci-Resolve-17-Editors-Guide.pdf)
  describes opening multicam contents in a timeline.
- Installed API reference: `/opt/resolve/Developer/Scripting/README.txt`.
