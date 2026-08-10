# Task 04 — Edit Planning, Frame Math, Labels, and Colors

## Objective

Convert validated master segments and the available accepted audio matches into a complete, deterministic, Resolve-independent `EditPlan`. Guarantee continuous master audio, exact optional video coverage, and explicit intentional video gaps before any API mutation.

## Dependencies and ownership

- Depends on: Tasks 01 and 03; consumes media rates from Task 02/05 models.
- Owns: `planning/models.py`, `planning/frame_math.py`, `planning/colors.py`, `planning/planner.py`, and focused tests.
- Does not call Resolve or serialize the final report.
- Use `$develop-python`, `$script-davinci-resolve`, and `$test-multi-cam-sync`.

## Public interfaces

Define immutable models equivalent to:

```python
class FrameRate: ...  # exact rational rate plus display value/drop-frame metadata


class PlannedClip: ...  # stable ID, media ID, source start/end, record start/end, track/media type


class PlannedSegment: ...  # master clip, video_status, optional video clip


class PlannedGap: ...  # explicit no-video record range for an unsupplied take


class PlannedMarker: ...


class EditPlan: ...  # segments, master/video clips, video gaps, markers, color map, warnings


def seconds_to_frame(value: Decimal, rate: FrameRate) -> int: ...
def create_edit_plan(inputs: PlanningInputs) -> EditPlan: ...
def validate_edit_plan(plan: EditPlan) -> None: ...
```

Use round-half-up for positive absolute second-to-frame conversion. Parse frame rates such as `24000/1001` exactly; never approximate them as integer 23 or 24. Timeline record frames include `timeline_start_frame`; source frames are relative to the selected Media Pool item's source start and use that item's rate.

## Planning rules

1. Finalize the last master segment with the probed master duration and independently convert every absolute master boundary to a timeline frame. Derive each record duration by subtracting adjacent boundary frames.
2. Plan one Audio Track 1 clip per master segment from the master Media Pool item, with `media_type = audio-only`, contiguous record frames, take/segment name, deterministic take color, and source bounds matching the master boundaries.
3. For a `matched` video-enabled segment, plan one Video Track 1 clip from its selected multicam/video Media Pool item, with `media_type = video-only`. Its source in is the accepted mapped in-point; its source out represents exactly the master segment duration at the source frame rate. Keep the DTW-predicted end only as diagnostics—V1 does not retime.
4. For a `not_provided` segment, plan no video clip and add one `PlannedGap` covering exactly that segment's record-frame range. Do not create a filler, black generator, title, placeholder media ID, or synthetic match. If a take is video-enabled, every segment carrying that normalized take must be `matched` or `unsafe`; it cannot become `not_provided` per occurrence.
5. Reject a source out beyond its probed media duration, zero/negative frame durations, an unsafe requested match, a missing match/media ID/rate for a video-enabled take, inconsistent take/segment IDs, or source/timeline rounding that exceeds the accepted drift tolerance. Do not reject an unconfigured take for lacking a match.
6. Add one timeline marker per cut at the shared adjacent boundary, with stable marker ID/custom data, `Out → In` name, exact input timestamp, outgoing/incoming segment IDs and video statuses, and override/unsafe warning fields where relevant.
7. Normalize a stable take ordering by first appearance. Assign colors deterministically from the 16 supported Resolve colors, using the sketch's weighted adjacency/high-contrast idea. Reuse colors only after the palette is exhausted; color never affects identity.
8. Give each clip/gap a stable label or ID (`<take> — segment NNN`) and include original/display take names. Keep the plan JSON-compatible but do not serialize it here.
9. Run `validate_edit_plan` before returning. It asserts one audio clip per master segment; audio has exact continuous coverage; each segment has exactly one of a matched video clip or declared video gap; video clips are ordered/non-overlapping and use exact segment record bounds; the union of video clips and gaps equals the full audio range; every occurrence of the same take has the same enabled/omitted policy; markers cover every interior boundary; and IDs, tracks, colors, and source/record bounds are valid.

## Tests

Cover:

- Decimal half-frame values, long durations, zero start, timeline start offsets, and exact 24000/1001, 30000/1001, 24, 25, and 30 rates;
- proof that independently rounded boundaries and neighbor subtraction create no cumulative gaps;
- all 29 Arabesques segments from the checked-in cut list with zero supplied takes, one supplied take, two supplied takes, and full supplied-take coverage using deterministic fake matches/media metadata;
- source rate different from timeline rate and source out-of-duration;
- audio-only/video-only flags, track indices, stable labels/IDs, per-segment video status, marker payloads, and first/last boundaries;
- every occurrence of a supplied take producing a clip, unsupplied takes producing exact `PlannedGap` ranges, and no placeholder/filler media;
- deterministic colors, adjacent contrast, same take retaining one color, and more than 16 takes;
- rejection of unsafe requested matches, missing matches/media for enabled takes, a `not_provided` occurrence of an otherwise enabled take, negative/zero duration, unordered/duplicate boundaries, undeclared gaps, video overlap, mismatched take IDs, and excess drift;
- plan equality regardless of input dictionary insertion order.

## Acceptance criteria

- A valid input always yields a fully specified plan requiring no Resolve-side decisions.
- Audio Track 1 covers the complete contiguous master. Video clips cover exactly the supplied-take segment ranges, while explicit gaps cover exactly the unsupplied ranges; the two never overlap.
- The Arabesques example always yields 29 master clips and 28 markers, with between 0 and 29 video clips depending on which take labels are supplied.
- Every invalid invariant fails before Task 05 can mutate Resolve.
- Ruff, ty, and focused tests pass.

## Handoff

Publish all `EditPlan` field semantics, source versus record frame conventions, supported color set, label format, and validator invariants. Task 05 consumes the plan without recomputing time or selecting media.
