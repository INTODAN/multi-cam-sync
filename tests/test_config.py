from __future__ import annotations

from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from multi_cam_sync.config import load_project_spec
from multi_cam_sync.domain.errors import ConfigError


def _write_project(tmp_path: Path, config: str, cuts: str | None = None) -> Path:
    if cuts is not None:
        (tmp_path / "cuts.txt").write_text(cuts, encoding="utf-8")
    path = tmp_path / "project.toml"
    path.write_text(config, encoding="utf-8")
    return path


def _base_config(*, sources: str = "", cuts_file: str = "cuts.txt") -> str:
    return f'''schema_version = 1

[project]
timeline_name = "Synced timeline"
cuts_file = "{cuts_file}"

[master]
media_pool_folder = "Masters"
media_pool_name = "Master.wav"
audio_path = "media/master.wav"
{sources}
'''


SIMPLE_CUTS = "Out: Take 1\nIn: Take 2\n00:00:10.125\n"
THREE_TAKE_CUTS = "Out: Take 1\nIn: Take 2\n00:00:10\n\nOut: Take 2\nIn: Take 3\n00:00:20\n"


def test_relative_paths_and_omitted_sources_are_valid(tmp_path: Path) -> None:
    path = _write_project(tmp_path, _base_config(), SIMPLE_CUTS)

    spec = load_project_spec(path)

    assert spec.config_path == path.resolve()
    assert spec.project.cuts_file == (tmp_path / "cuts.txt").resolve()
    assert spec.master.audio_path == (tmp_path / "media/master.wav").resolve()
    assert spec.sources == ()
    assert spec.sources_by_take == {}


def test_explicit_empty_sources_are_valid(tmp_path: Path) -> None:
    config = _base_config().replace("schema_version = 1", "schema_version = 1\nsources = []")

    spec = load_project_spec(_write_project(tmp_path, config, SIMPLE_CUTS))

    assert spec.sources == ()


def test_frame_cut_list_can_be_cross_validated_with_an_explicit_rate(tmp_path: Path) -> None:
    cuts = "Out: Take 1\nIn: Take 2\n00:00:10:03\n"
    path = _write_project(tmp_path, _base_config(), cuts)

    spec = load_project_spec(path, cut_frame_rate=Fraction(24))

    assert spec.project.cuts_file == (tmp_path / "cuts.txt").resolve()


def test_standalone_config_load_explains_missing_rate_for_frame_cuts(tmp_path: Path) -> None:
    cuts = "Out: Take 1\nIn: Take 2\n00:00:10:03\n"
    path = _write_project(tmp_path, _base_config(), cuts)

    with pytest.raises(ConfigError, match="requires the active Resolve timeline frame rate"):
        load_project_spec(path)


def test_partial_video_candidates_are_grouped_deterministically(tmp_path: Path) -> None:
    sources = """
[[sources]]
id = "take-2-main"
take = " Take  2 "
media_pool_folder = "Multicam"
media_pool_name = "Shared recording"
audio_reference_path = "camera/shared.mov"
source_start = "00:00:01.125"
source_end = "00:00:08.500"

[[sources]]
id = "take-2-backup"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "Shared recording"
audio_reference_path = "camera/shared.mov"
manual_offset_seconds = -1.25

[[sources]]
id = "take-3"
take = "Take 3"
media_pool_folder = "Multicam"
media_pool_name = "Take 3"
"""
    spec = load_project_spec(
        _write_project(tmp_path, _base_config(sources=sources), THREE_TAKE_CUTS)
    )

    assert list(spec.sources_by_take) == ["Take 2", "Take 3"]
    assert [item.id for item in spec.sources_by_take["Take 2"]] == [
        "take-2-main",
        "take-2-backup",
    ]
    assert spec.sources[0].take == "Take 2"
    assert spec.sources[0].source_start == Decimal("1.125")
    assert spec.sources[1].manual_offset_seconds == Decimal("-1.25")
    assert spec.sources[0].audio_reference_path == (tmp_path / "camera/shared.mov").resolve()
    assert spec.sources_by_take.get("Take 1", ()) == ()


def test_additional_audio_reference_paths_are_ordered_and_resolved(tmp_path: Path) -> None:
    absolute_reference = tmp_path / "absolute camera.wav"
    sources = f'''
[[sources]]
id = "take-1"
take = "Take 1"
media_pool_folder = "Multicam"
media_pool_name = "Take 1 multicam"
audio_reference_path = "camera/primary.wav"
additional_audio_reference_paths = [
    "camera/second.wav",
    "{absolute_reference}",
]
'''

    spec = load_project_spec(_write_project(tmp_path, _base_config(sources=sources), SIMPLE_CUTS))

    assert spec.sources[0].additional_audio_reference_paths == (
        (tmp_path / "camera/second.wav").resolve(),
        absolute_reference.resolve(),
    )


@pytest.mark.parametrize(
    ("primary", "additional", "message"),
    [
        (
            'audio_reference_path = "camera/primary.wav"',
            'additional_audio_reference_paths = "camera/second.wav"',
            "must be a TOML array",
        ),
        (
            'audio_reference_path = "camera/primary.wav"',
            'additional_audio_reference_paths = [" "]',
            "must be a nonblank filesystem path",
        ),
        (
            'audio_reference_path = "camera/primary.wav"',
            'additional_audio_reference_paths = ["camera/second.wav", "camera/second.wav"]',
            "must be unique",
        ),
        (
            'audio_reference_path = "camera/primary.wav"',
            'additional_audio_reference_paths = ["camera/primary.wav"]',
            "must not repeat",
        ),
        (
            "manual_offset_seconds = 1.0",
            'additional_audio_reference_paths = ["camera/second.wav"]',
            "manual matching does not decode audio",
        ),
    ],
)
def test_additional_audio_reference_paths_are_validated(
    tmp_path: Path,
    primary: str,
    additional: str,
    message: str,
) -> None:
    sources = f"""
[[sources]]
id = "take-1"
take = "Take 1"
media_pool_folder = "Multicam"
media_pool_name = "Take 1 multicam"
{primary}
{additional}
"""

    with pytest.raises(ConfigError, match=message):
        load_project_spec(_write_project(tmp_path, _base_config(sources=sources), SIMPLE_CUTS))


@pytest.mark.parametrize("provided", [(), (2,), (2, 9), tuple(range(1, 10))])
def test_zero_partial_and_full_coverage_of_nine_takes_is_valid(
    tmp_path: Path, provided: tuple[int, ...]
) -> None:
    cuts = "\n\n".join(
        f"Out: Take {take}\nIn: Take {take + 1}\n00:00:{take:02d}" for take in range(1, 9)
    )
    sources = "\n".join(
        (
            "[[sources]]\n"
            f'id = "take-{take}"\n'
            f'take = "Take {take}"\n'
            'media_pool_folder = "Multicam"\n'
            f'media_pool_name = "Take {take}"\n'
        )
        for take in provided
    )

    spec = load_project_spec(_write_project(tmp_path, _base_config(sources=sources), cuts))

    assert tuple(spec.sources_by_take) == tuple(f"Take {take}" for take in provided)


def test_two_logical_occurrences_can_share_one_physical_recording(tmp_path: Path) -> None:
    sources = """
[[sources]]
id = "take-8-a"
take = "Take 8 A"
media_pool_folder = "Multicam"
media_pool_name = "Take 8 multicam"
audio_reference_path = "Take 8 recording.mov"
source_start = "00:00:00"
source_end = "00:02:10"

[[sources]]
id = "take-8-b"
take = "Take 8 B"
media_pool_folder = "Multicam"
media_pool_name = "Take 8 multicam"
audio_reference_path = "Take 8 recording.mov"
source_start = "00:02:25"
source_end = "00:05:20"
"""
    cuts = "Out: Take 8 A\nIn: Take 8 B\n00:02:20\n"

    spec = load_project_spec(_write_project(tmp_path, _base_config(sources=sources), cuts))

    assert spec.sources[0].audio_reference_path == spec.sources[1].audio_reference_path
    assert spec.sources[0].source_end == Decimal(130)
    assert spec.sources[1].source_start == Decimal(145)


def test_source_can_narrow_search_bounds_for_one_matching_segment(tmp_path: Path) -> None:
    sources = """
[[sources]]
id = "take-2"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "Take 2 multicam"
source_start = "00:00:01"
source_end = "00:00:30"

[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:08.125"
source_end = "00:00:13.500"
"""

    spec = load_project_spec(_write_project(tmp_path, _base_config(sources=sources), SIMPLE_CUTS))

    source = spec.sources[0]
    search_range = source.search_range_for("segment-0002")
    assert search_range is not None
    assert search_range.source_start == Decimal("8.125")
    assert search_range.source_end == Decimal("13.500")
    assert source.search_range_for("segment-0001") is None


def test_source_can_override_one_segment_manually_without_disabling_other_controls(
    tmp_path: Path,
) -> None:
    cuts = "Out: Take 2\nIn: Take 1\n00:00:10\n\nOut: Take 1\nIn: Take 2\n00:00:20\n"
    sources = """
[[sources]]
id = "take-2"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "Take 2 multicam"
audio_reference_path = "camera/primary.wav"
additional_audio_reference_paths = ["camera/fallback.wav"]
source_start = "00:00:01"
source_end = "00:01:00"

[[sources.segment_manual_offsets]]
segment_id = "segment-0001"
manual_offset_seconds = 17.25

[[sources.segment_search_ranges]]
segment_id = "segment-0003"
source_start = "00:00:40"
source_end = "00:00:55"
"""

    spec = load_project_spec(_write_project(tmp_path, _base_config(sources=sources), cuts))

    source = spec.sources[0]
    assert source.manual_offset_for("segment-0001") == Decimal("17.25")
    assert source.manual_offset_for("segment-0003") is None
    assert source.search_range_for("segment-0001") is None
    assert source.search_range_for("segment-0003") is not None
    assert source.additional_audio_reference_paths == (
        (tmp_path / "camera/fallback.wav").resolve(),
    )


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        (
            """[[sources.segment_manual_offsets]]
segment_id = "segment-9999"
manual_offset_seconds = 2.0""",
            "unknown segment",
        ),
        (
            """[[sources.segment_manual_offsets]]
segment_id = "segment-0001"
manual_offset_seconds = 2.0""",
            "does not use source take",
        ),
        (
            """[[sources.segment_manual_offsets]]
segment_id = "segment-0002"
manual_offset_seconds = 2.0

[[sources.segment_manual_offsets]]
segment_id = "segment-0002"
manual_offset_seconds = 3.0""",
            "must be unique",
        ),
        (
            '''[[sources.segment_manual_offsets]]
segment_id = "segment-0002"
manual_offset_seconds = "2.0"''',
            "finite numeric TOML value",
        ),
        (
            """[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:08"
source_end = "00:00:13"

[[sources.segment_manual_offsets]]
segment_id = "segment-0002"
manual_offset_seconds = 2.0""",
            "cannot both configure the same segment",
        ),
        (
            """manual_offset_seconds = 1.0

[[sources.segment_manual_offsets]]
segment_id = "segment-0002"
manual_offset_seconds = 2.0""",
            "cannot be combined with the source-wide",
        ),
    ],
)
def test_segment_manual_offsets_are_cross_validated(
    tmp_path: Path, configuration: str, message: str
) -> None:
    sources = f"""
[[sources]]
id = "take-2"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "Take 2 multicam"
source_start = "00:00:01"
source_end = "00:00:30"
{configuration}
"""

    with pytest.raises(ConfigError, match=message):
        load_project_spec(_write_project(tmp_path, _base_config(sources=sources), SIMPLE_CUTS))


@pytest.mark.parametrize(
    ("ranges", "message"),
    [
        (
            '''[[sources.segment_search_ranges]]
segment_id = "segment-9999"
source_start = "00:00:08"
source_end = "00:00:13"''',
            "unknown segment",
        ),
        (
            '''[[sources.segment_search_ranges]]
segment_id = "segment-0001"
source_start = "00:00:08"
source_end = "00:00:13"''',
            "does not use source take",
        ),
        (
            '''[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:08"
source_end = "00:00:13"

[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:14"
source_end = "00:00:18"''',
            "must be unique",
        ),
        (
            '''[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:00"
source_end = "00:00:13"''',
            "start at or after",
        ),
        (
            '''[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:08"
source_end = "00:00:31"''',
            "end at or before",
        ),
        (
            '''[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:08"
source_end = "00:00:08"''',
            "must be greater than",
        ),
    ],
)
def test_segment_search_ranges_are_cross_validated(
    tmp_path: Path, ranges: str, message: str
) -> None:
    sources = f"""\n[[sources]]
id = "take-2"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "Take 2 multicam"
source_start = "00:00:01"
source_end = "00:00:30"
{ranges}
"""

    with pytest.raises(ConfigError, match=message):
        load_project_spec(_write_project(tmp_path, _base_config(sources=sources), SIMPLE_CUTS))


def test_segment_search_ranges_cannot_be_combined_with_manual_matching(tmp_path: Path) -> None:
    sources = """
[[sources]]
id = "take-2"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "Take 2 multicam"
manual_offset_seconds = 2.0

[[sources.segment_search_ranges]]
segment_id = "segment-0002"
source_start = "00:00:08"
source_end = "00:00:13"
"""

    with pytest.raises(ConfigError, match="manual matching does not search"):
        load_project_spec(_write_project(tmp_path, _base_config(sources=sources), SIMPLE_CUTS))


def test_absolute_paths_are_preserved_and_normalized(tmp_path: Path) -> None:
    absolute_cuts = tmp_path / "elsewhere" / "cuts.txt"
    absolute_cuts.parent.mkdir()
    absolute_cuts.write_text(SIMPLE_CUTS, encoding="utf-8")
    absolute_audio = tmp_path / "elsewhere" / "master.wav"
    config = _base_config(cuts_file=str(absolute_cuts)).replace(
        'audio_path = "media/master.wav"', f'audio_path = "{absolute_audio}"'
    )

    spec = load_project_spec(_write_project(tmp_path, config))

    assert spec.project.cuts_file == absolute_cuts.resolve()
    assert spec.master.audio_path == absolute_audio.resolve()


@pytest.mark.parametrize(
    "schema",
    [
        "",
        "schema_version = true",
        'schema_version = "1"',
        "schema_version = 0",
        "schema_version = 2",
    ],
)
def test_only_integer_schema_version_one_is_supported(tmp_path: Path, schema: str) -> None:
    config = _base_config().replace("schema_version = 1", schema)

    with pytest.raises(ConfigError, match=r"schema_version.*integer 1"):
        load_project_spec(_write_project(tmp_path, config, SIMPLE_CUTS))


@pytest.mark.parametrize("missing", ["id", "take", "media_pool_folder", "media_pool_name"])
def test_supplied_source_requires_every_identity_field(tmp_path: Path, missing: str) -> None:
    fields = {
        "id": 'id = "source-1"',
        "take": 'take = "Take 1"',
        "media_pool_folder": 'media_pool_folder = "Multicam"',
        "media_pool_name": 'media_pool_name = "Take 1 clip"',
    }
    source = "\n[[sources]]\n" + "\n".join(value for key, value in fields.items() if key != missing)

    with pytest.raises(ConfigError, match=missing):
        load_project_spec(_write_project(tmp_path, _base_config(sources=source), SIMPLE_CUTS))


@pytest.mark.parametrize(
    "bounds",
    [
        'source_start = "-0.1"',
        'source_start = "00:00:02"\nsource_end = "00:00:02"',
        'source_start = "00:00:03"\nsource_end = "00:00:02"',
        'source_end = "-1"',
        'manual_offset_seconds = "NaN"',
        'manual_offset_seconds = "1.25"',
    ],
)
def test_source_bounds_and_offsets_are_validated(tmp_path: Path, bounds: str) -> None:
    source = f"""
[[sources]]
id = "source-1"
take = "Take 1"
media_pool_folder = "Multicam"
media_pool_name = "Take 1 clip"
{bounds}
"""

    with pytest.raises(ConfigError, match=r"source_|finite"):
        load_project_spec(_write_project(tmp_path, _base_config(sources=source), SIMPLE_CUTS))


def test_duplicate_source_ids_are_rejected(tmp_path: Path) -> None:
    source = """
[[sources]]
id = "same"
take = "Take 1"
media_pool_folder = "Multicam"
media_pool_name = "first"

[[sources]]
id = "same"
take = "Take 2"
media_pool_folder = "Multicam"
media_pool_name = "second"
"""

    with pytest.raises(ConfigError, match=r"unique.*same"):
        load_project_spec(_write_project(tmp_path, _base_config(sources=source), SIMPLE_CUTS))


def test_configured_take_not_used_by_cuts_is_rejected(tmp_path: Path) -> None:
    source = """
[[sources]]
id = "typo"
take = "Take 99"
media_pool_folder = "Multicam"
media_pool_name = "Take 9"
"""

    with pytest.raises(ConfigError, match=r"unused: typo \(Take 99\)"):
        load_project_spec(_write_project(tmp_path, _base_config(sources=source), SIMPLE_CUTS))


def test_independent_configuration_errors_are_aggregated(tmp_path: Path) -> None:
    config = (
        _base_config()
        .replace('timeline_name = "Synced timeline"', 'timeline_name = " "')
        .replace('media_pool_name = "Master.wav"', 'media_pool_name = " "')
    )

    with pytest.raises(ConfigError) as captured:
        load_project_spec(_write_project(tmp_path, config, SIMPLE_CUTS))

    assert "project.timeline_name" in str(captured.value)
    assert "master.media_pool_name" in str(captured.value)
    assert "Traceback" not in str(captured.value)


def test_cut_errors_are_wrapped_with_the_configuration_key(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"project.cuts_file.*incomplete"):
        load_project_spec(_write_project(tmp_path, _base_config(), "Out: Take 1\n"))


def test_loaded_models_are_immutable_and_serialize_deterministically(tmp_path: Path) -> None:
    path = _write_project(tmp_path, _base_config(), SIMPLE_CUTS)
    first = load_project_spec(path)
    second = load_project_spec(path)

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    with pytest.raises(ValidationError, match="frozen"):
        setattr(first, "sources", ())  # noqa: B010 - deliberately exercise runtime immutability


def test_derived_take_key_cannot_disagree_with_display_take(tmp_path: Path) -> None:
    config = _base_config(
        sources="""
[[sources]]
id = "source"
take = "Take 1"
take_key = "something else"
media_pool_folder = "Multicam"
media_pool_name = "Take 1"
"""
    )

    with pytest.raises(ConfigError, match=r"take_key.*unexpected"):
        load_project_spec(_write_project(tmp_path, config, SIMPLE_CUTS))
