from __future__ import annotations

import tomllib
from decimal import Decimal
from pathlib import Path

from multi_cam_sync.config import load_project_spec

REPOSITORY_ROOT = Path(__file__).parents[1]
EXAMPLE_CONFIG = REPOSITORY_ROOT / "examples" / "project.example.toml"
EXAMPLE_CUTS = REPOSITORY_ROOT / "examples" / "Arabesques_composite_cuts.txt"
README = REPOSITORY_ROOT / "README.md"


def test_sanitized_partial_video_example_parses_from_a_private_copy(tmp_path: Path) -> None:
    example_text = EXAMPLE_CONFIG.read_text(encoding="utf-8")
    raw = tomllib.loads(example_text)

    assert "/home/" not in example_text
    assert "@gmail.com" not in example_text
    assert not Path(raw["master"]["audio_path"]).is_absolute()
    assert all(not Path(source["audio_reference_path"]).is_absolute() for source in raw["sources"])

    copied_config = tmp_path / "project.toml"
    copied_config.write_text(example_text, encoding="utf-8")
    (tmp_path / "Arabesques_composite_cuts.txt").write_text(
        EXAMPLE_CUTS.read_text(encoding="utf-8"), encoding="utf-8"
    )

    spec = load_project_spec(copied_config)

    assert [source.id for source in spec.sources] == ["take-8-a", "take-8-b"]
    assert [source.take for source in spec.sources] == ["Take 8 A", "Take 8 B"]
    assert spec.sources[0].media_pool_name == spec.sources[1].media_pool_name
    assert spec.sources[0].audio_reference_path == spec.sources[1].audio_reference_path
    assert spec.sources[0].source_end == Decimal(130)
    assert spec.sources[1].source_start == Decimal(145)
    assert set(spec.sources_by_take) == {"Take 8 A", "Take 8 B"}


def test_readme_documents_commands_and_partial_video_safety_contract() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())

    for command in (
        "uv run multi-cam-sync validate /path/to/project.toml",
        "uv run multi-cam-sync analyze /path/to/project.toml --report",
        "uv run multi-cam-sync build /path/to/project.toml --report",
    ):
        assert command in readme

    for required_text in (
        'video_status = "not_provided"',
        'video_status = "matched"',
        'video_status = "unsafe"',
        "Intervals for omitted takes remain genuinely empty on Video Track 1",
        "supplied take with a failed or ambiguous match",
        "build is blocked",
        "master audio continues on Audio Track 1",
    ):
        assert required_text in normalized_readme


def test_readme_exposes_setup_recovery_gates_and_project_documents() -> None:
    readme = README.read_text(encoding="utf-8")
    normalized_readme = " ".join(readme.split())

    for required_text in (
        "ffmpeg -version",
        "ffprobe -version",
        "RESOLVE_SCRIPT_API",
        "RESOLVE_SCRIPT_LIB",
        'dvr_script.scriptapp("Resolve")',
        "resolve.GetProjectManager()",
        "project_manager.GetCurrentProject()",
        "resolve.GetProductName()",
        "resolve.GetVersionString()",
        "uv sync --all-groups",
        "uv run ruff format --check .",
        "uv run ruff check .",
        "uv run ty check",
        "uv run pytest",
        "uv run pre-commit run --all-files",
        "multi-cam-sync/analysis-audio",
        "rerun `validate` and `analyze`",
        "specifications.md",
        "plans/PROJECT_PLAN.md",
        "plans/HUMAN_GUIDE.md",
    ):
        assert required_text in readme

    for required_text in (
        "Run this application from a normal terminal while DaVinci Resolve Studio is open",
        "Set **External scripting using** to **Local**",
        "It does not change the project",
        "Run all three commands from the same externally configured terminal",
    ):
        assert required_text in normalized_readme

    assert "from multi_cam_sync.cli import main" not in readme
