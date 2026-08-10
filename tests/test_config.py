from __future__ import annotations

from decimal import Decimal
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
