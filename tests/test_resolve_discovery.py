from __future__ import annotations

from decimal import Decimal

import pytest

from multi_cam_sync.resolve.discovery import (
    capture_snapshot,
    parse_resolve_rate,
    parse_resolve_timecode_frame,
)
from multi_cam_sync.resolve.errors import ResolveDiscoveryError, ResolveOperationError
from multi_cam_sync.resolve.protocols import MediaSelector

from .fakes.resolve import (  # ty: ignore[unresolved-import]
    FakeFolder,
    FakeMediaItem,
    make_resolve_fake,
)

MASTER = MediaSelector(("Masters",), "Master.wav", "master")
VIDEO = MediaSelector(("Media", "Multicam"), "Take 1 multicam", "video")


def test_snapshot_uses_exact_nested_paths_and_reuses_repeated_selector() -> None:
    fake = make_resolve_fake()

    snapshot, raw = capture_snapshot(fake.session, [MASTER, VIDEO, VIDEO])

    assert snapshot.project_name == "Test Project"
    assert snapshot.project_id == "project-id"
    assert snapshot.timeline_frame_rate == Decimal("24000") / Decimal("1001")
    assert snapshot.timeline_start_frame == 100
    assert snapshot.timeline_names == ("Existing",)
    assert [item.media_id for item in snapshot.media] == ["master-id", "video-id"]
    assert snapshot.media[1].file_path is None
    assert snapshot.media[1].frame_rate == Decimal("24000") / Decimal("1001")
    assert raw == {"master-id": fake.master, "video-id": fake.video}
    assert fake.events.count(("MediaPoolItem.GetClipProperty", "video-id", None)) == 1


def test_explicit_root_folder_selects_only_root_clips() -> None:
    fake = make_resolve_fake()
    masters = fake.media_pool.root.folders[0]
    masters.clips.remove(fake.master)
    fake.media_pool.root.clips.append(fake.master)
    root_master = MediaSelector.from_folder(".", "Master.wav", "master")

    snapshot, raw = capture_snapshot(fake.session, [root_master])

    assert snapshot.media[0].selector == root_master
    assert raw == {"master-id": fake.master}


def test_root_folder_marker_cannot_be_combined_with_child_components() -> None:
    with pytest.raises(ValueError, match="root marker"):
        MediaSelector.from_folder("./Masters", "Master.wav", "master")


def test_selector_requires_exact_item_name() -> None:
    fake = make_resolve_fake()

    with pytest.raises(ResolveDiscoveryError, match="matched no item"):
        capture_snapshot(
            fake.session,
            [MediaSelector(("Masters",), "Master", "master")],
        )


def test_duplicate_exact_items_are_rejected() -> None:
    fake = make_resolve_fake()
    duplicate = FakeMediaItem(
        fake.master.name,
        "other-id",
        dict(fake.master.properties),
        fake.events,
    )
    masters = fake.media_pool.root.folders[0]
    masters.clips.append(duplicate)

    with pytest.raises(ResolveDiscoveryError, match="matched 2 items"):
        capture_snapshot(fake.session, [MASTER])


def test_duplicate_exact_folder_components_are_rejected() -> None:
    fake = make_resolve_fake()
    fake.media_pool.root.folders.append(FakeFolder("Masters", fake.events))

    with pytest.raises(ResolveDiscoveryError, match="multiple exact folders"):
        capture_snapshot(fake.session, [MASTER])


def test_virtual_multicam_without_file_path_is_valid_when_metadata_is_complete() -> None:
    fake = make_resolve_fake()

    snapshot, _ = capture_snapshot(fake.session, [VIDEO])

    assert snapshot.media[0].file_path is None
    assert snapshot.media[0].duration_frames == 2000


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (24, Decimal("24")),
        (24.0, Decimal("24.0")),
        (Decimal("23.976"), Decimal("23.976")),
        ("24000/1001", Decimal("24000") / Decimal("1001")),
    ],
)
def test_project_or_clip_rates_accept_resolve_numeric_shapes(
    value: object, expected: Decimal
) -> None:
    assert parse_resolve_rate(value, operation="test rate") == expected


@pytest.mark.parametrize(
    "value",
    ["", "0", "nan", "not-a-rate", "1/0", 0, 0.0, float("nan"), False, None],
)
def test_invalid_project_or_clip_rates_are_rejected(value: object) -> None:
    with pytest.raises(ResolveOperationError, match="frame rate"):
        parse_resolve_rate(value, operation="test rate")


def test_missing_video_fps_is_rejected_without_fallback() -> None:
    fake = make_resolve_fake()
    fake.video.properties.pop("Frame Rate")

    with pytest.raises(ResolveOperationError, match="has no FPS metadata"):
        capture_snapshot(fake.session, [VIDEO])


def test_missing_duration_is_rejected_without_fake_duration() -> None:
    fake = make_resolve_fake()
    fake.master.properties.pop("Frames")

    with pytest.raises(ResolveOperationError, match="refusing guessed duration"):
        capture_snapshot(fake.session, [MASTER])


def test_audio_duration_timecode_uses_project_rate_when_audio_has_no_fps() -> None:
    fake = make_resolve_fake()
    fake.master.properties = {"FilePath": "/media/master.wav", "Duration": "00:00:10:00"}

    snapshot, _ = capture_snapshot(fake.session, [MASTER])

    assert snapshot.media[0].duration_frames == 240
    assert snapshot.media[0].frame_rate == Decimal("24000") / Decimal("1001")


def test_project_start_is_available_even_when_no_timeline_is_current() -> None:
    fake = make_resolve_fake()
    fake.project.current_timeline = None
    fake.project.settings["timelineStartTimecode"] = "01:00:00:00"

    snapshot, _ = capture_snapshot(fake.session, [MASTER])

    assert snapshot.timeline_start_timecode == "01:00:00:00"
    assert snapshot.timeline_start_frame == 86400


def test_drop_frame_start_timecode_is_converted_exactly() -> None:
    assert (
        parse_resolve_timecode_frame(
            "01:00:00;00",
            Decimal("29.97"),
            drop_frame=True,
            operation="test timecode",
        )
        == 107892
    )

    with pytest.raises(ResolveOperationError, match="invalid dropped frame"):
        parse_resolve_timecode_frame(
            "00:01:00;00",
            Decimal("29.97"),
            drop_frame=True,
            operation="test timecode",
        )
