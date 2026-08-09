---
name: script-davinci-resolve
description: Implement, test, diagnose, or review DaVinci Resolve Python API integration for multi-cam-sync, including partial video coverage, intentional empty video regions, connection, exact Media Pool discovery, clip properties, frame rates, AppendToTimeline clip-info calls, markers, colors, timeline verification, strict fakes, and rollback. Use whenever a task reads Resolve state or creates/verifies the synced timeline.
---

# Script DaVinci Resolve

## Verify the API locally

Read the relevant entries in `/opt/resolve/Developer/Scripting/README.txt` before using an API operation. Use the rough scripts at `/home/itaielidan/Insync/itaielidan@gmail.com/Google Drive/DaVinciResolve/scripts/` as behavioral prototypes only.

Carry forward the useful native patterns from `build_timeline_segments.py` and `01_arabesques_build_timeline_segments.py`: recursive folder traversal, `CreateEmptyTimeline`, clip-info `AppendToTimeline`, explicit `recordFrame`, segment labels/colors, and cut markers. Do not carry forward hard-coded media/cuts, substring matching, fake durations, ignored return values, or `pyautogui` razor automation.

## Keep a hard adapter boundary

- Import `DaVinciResolveScript` only inside connection code. Keep the package importable without Resolve.
- Hide raw dynamic objects behind project-owned protocols/models and one gateway.
- Treat documented Boolean false, `None`, empty results, malformed properties, and exceptions as explicit operation errors.
- Normalize Resolve property aliases in one place. Preserve exact rational frame rates where Resolve exposes them.
- Select a Media Pool item by exact folder components plus exact name. Reject zero or multiple matches and reuse resolved repeated selectors by media ID.

## Separate reads from mutation

Allow discovery/snapshot/preflight to run read-only. Before mutation, verify the complete edit plan, current project/settings/media IDs, source bounds, target timeline absence, colors, and tracks.

For a build:

1. Create and select one new empty timeline.
2. Append master segments as audio-only items on Audio Track 1.
3. Append source multicam/video segments as video-only items on Video Track 1 only for `matched` segments. Do not append filler, black, title, or placeholder items for `not_provided` segments.
4. Create/require Video Track 1 only when at least one video clip is planned.
5. Use exact planned source/record frames; do no time math or source selection in the adapter.
6. Require expected TimelineItems, names, colors, and marker results.
7. Read the timeline back and verify continuous audio, exact matched video ranges, no video item in each declared intentional gap, no undeclared gap/overlap, tracks, source/record bounds, labels, colors, and markers.
8. On failure after creation, delete only that returned timeline and report rollback status. Never replace an existing timeline or delete media.

## Test with strict fakes

Make fakes reject unexpected methods/arguments and record call order. Cover missing connection/project/configured media, exact discovery, property aliases, all falsey/exception returns, zero-mutation preflight failures, exact append dictionaries, zero/partial/full video plans, zero append calls in intentional gaps, a filler appearing in a planned gap, undeclared gaps/overlaps, success, rollback success/failure, and proof that only the new timeline is a rollback target.

Keep real Resolve checks behind the `resolve_live` marker and explicit mutation environment variable. Never run a live mutation as part of ordinary tests, pre-commit, or an implementation task without the specified disposable-project authorization.

Finish with focused pytest, Ruff, and ty via `uv`; report the documented API methods used, tested Resolve version, mutation boundary, and any live check left for Task 07.
