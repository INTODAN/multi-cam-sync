# Task 05 — DaVinci Resolve Integration

## Objective

Implement the only boundary that talks to DaVinci Resolve: connect to the current project, resolve exact Media Pool selectors for the master and configured video subset, preflight an `EditPlan`, create one new timeline with native API calls, verify continuous audio plus intentional video gaps, and remove only that newly created timeline if the run fails.

## Dependencies and ownership

- Read/discovery half depends on: Tasks 00 and 01.
- Timeline mutation half depends on: Task 04's final `EditPlan` contract.
- Owns: `resolve/protocols.py`, `resolve/connection.py`, `resolve/discovery.py`, `resolve/gateway.py`, `resolve/builder.py`, strict fake objects, and Resolve-focused unit tests.
- Use `$script-davinci-resolve`, `$develop-python`, and `$test-multi-cam-sync`.

## Public interfaces

Expose project-owned types instead of raw Resolve objects:

```python
class ResolveProjectSnapshot: ...  # project name, rates/start, timeline names, selected media
class ResolvedMediaItem: ...       # media ID, selector, kind, file path, duration/rate metadata
class ResolveGateway(Protocol):
    def snapshot(self, selectors) -> ResolveProjectSnapshot: ...
    def build_timeline(self, plan: EditPlan) -> BuildResult: ...
```

Production code obtains `DaVinciResolveScript.scriptapp("Resolve")` lazily. Importing any package module must work when the Resolve module/library is absent.

## Discovery and preflight

1. Require a Resolve connection, Project Manager, current project, Media Pool, and root folder. Convert every false/`None`/exception return into a typed error naming the operation.
2. Traverse folders by exact component and match an exact item name in the configured folder. Never use substring matching. Zero or multiple matches are errors for the master or a configured source. Do not search for unsupplied takes. Repeated source selectors reuse one resolved item.
3. Capture `GetMediaId`, `GetClipProperty()` values needed for file path, duration, frames, and FPS. Do not use a fake duration fallback. Normalize Resolve's property aliases in one adapter function and preserve raw properties for diagnostics.
4. Snapshot the project name, timeline frame rate, timeline start frame/timecode, existing timeline names, and resolved item IDs. Compare this snapshot/fingerprint again immediately before building.
5. Preflight the complete plan: target timeline absent; every media ID referenced by the master or a planned matched video clip still resolves to the expected item; frames are within source media; planned gaps carry no media ID; supported colors; track/media types valid; and plan validator passes. No API mutation may occur before all checks pass.

## Timeline build

1. Call `CreateEmptyTimeline` and verify the returned object, then `SetCurrentTimeline` and verify success. Record the returned timeline identity as the only rollback target.
2. Ensure Audio Track 1 exists. Ensure Video Track 1 only when at least one video clip is planned. Do not alter or remove other project tracks/media.
3. Append every master segment through `MediaPool.AppendToTimeline([{...}])` with `mediaType = 2`, exact `startFrame`, `endFrame`, `recordFrame`, and `trackIndex = 1`. Check that exactly one TimelineItem is returned for each request.
4. Append each planned matched multicam/video segment with the same native clip-info shape and `mediaType = 1` on Video Track 1. For every planned gap, make no append call and add no filler item. Do not append camera audio.
5. Apply planned `SetName`, `SetClipColor`, and optional clip marker calls and require true results where the installed API documents a Boolean. Add timeline cut markers with `AddMarker`, including stable custom data when supported.
6. Do not use keyboard automation, `SetCurrentTimecode` razor shortcuts, hard-coded Arabesques data, or swallowed exceptions. The native segmented-append pattern in the rough scripts is the prototype.
7. Read the finished timeline back through `GetItemListInTrack` and `GetMarkers`. Verify master item count and continuous coverage; video item count and exact matched ranges; absence of items in every planned gap; no unplanned video gaps or overlaps; tracks, source boundaries, labels, colors, marker positions/data, and total range against the plan.
8. If any post-creation step fails, call `DeleteTimelines([created_timeline])` on only that object. Return the original failure plus rollback success/failure. Never delete a pre-existing timeline, media item, or clip.

The installed `/opt/resolve/Developer/Scripting/README.txt` is the API source of truth. Isolate version/property quirks in the gateway; do not leak them into planning.

## Tests

Build strict fakes that fail on unexpected calls and record ordered operations. Cover:

- missing Resolve/module/connection/current project/media pool/root;
- exact nested-folder lookup, duplicate/missing item, repeated selector reuse, property aliases, virtual multicam with explicit reference path, and absent physical file path;
- fractional rates, invalid duration/frames, existing target timeline, stale project/media snapshot, and invalid plan—all with zero mutation calls;
- exact `AppendToTimeline` dictionaries for master audio and video-only multicam items, zero video append calls for audio-only segments, and no Video Track requirement for an all-audio plan;
- false/`None`/empty/exception returns from every mutating API operation;
- current timeline selection, track setup, names, supported colors, markers/custom data, and call ordering;
- successful read-back verification for zero/partial/full video coverage and every count/boundary/undeclared-gap/planned-gap-filled/overlap/label/color/marker mismatch;
- rollback called exactly once with exactly the newly created timeline; rollback failure surfaced; no rollback before creation or after success;
- package import without Resolve installed.

Keep the real-Resolve smoke test out of this task's default suite; Task 07 owns it.

## Acceptance criteria

- Preflight failures make no Resolve mutation.
- Success uses only documented native API operations and produces a verified representation of the plan, including genuinely empty Video Track intervals for unsupplied takes.
- Partial failure can affect at most the new timeline from that run and reports rollback status.
- All production logic is testable with fakes and no test requires a GUI.
- Ruff, ty, and focused tests pass.

## Handoff

Publish the connection prerequisites/environment discovery, normalized property keys, snapshot fields, typed error operations, build result/rollback semantics, and fake factory used by Task 06/07.
