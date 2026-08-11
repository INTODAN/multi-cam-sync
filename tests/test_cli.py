from __future__ import annotations

import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from multi_cam_sync.cli import build_parser, main
from multi_cam_sync.progress import ProgressCallback, ProgressEvent
from multi_cam_sync.reporting import AlignmentReport
from multi_cam_sync.resolve import BuildResult, ResolveConnectionError, ResolveOperationError
from multi_cam_sync.services import AnalysisOutcome, ServiceInputError, ValidationContext


class FakeService:
    def __init__(self) -> None:
        self.validation = cast(
            "ValidationContext",
            SimpleNamespace(
                enabled_take_keys=frozenset({"Take A"}),
                segments=(
                    SimpleNamespace(take_key="Take A"),
                    SimpleNamespace(take_key="Take B"),
                ),
                snapshot=SimpleNamespace(project_name="Project"),
                spec=SimpleNamespace(project=SimpleNamespace(timeline_name="Synced")),
            ),
        )
        self.outcome = AnalysisOutcome(
            report=cast(
                "AlignmentReport",
                SimpleNamespace(
                    segments=(
                        SimpleNamespace(video_status=SimpleNamespace(value="matched")),
                        SimpleNamespace(video_status=SimpleNamespace(value="not_provided")),
                    )
                ),
            ),
            unsafe_count=0,
        )
        self.result = BuildResult("timeline-id", "Synced", 2, 1, 1)
        self.calls: list[tuple[str, Path, object | None]] = []
        self.error: Exception | None = None

    def validate(self, config_path: Path) -> ValidationContext:
        self.calls.append(("validate", config_path, None))
        if self.error:
            raise self.error
        return self.validation

    def analyze(
        self, config_path: Path, *, progress: ProgressCallback | None = None
    ) -> AnalysisOutcome:
        self.calls.append(("analyze", config_path, None))
        if progress is not None:
            progress(ProgressEvent(0, 6, "Validating fake inputs"))
            progress(
                ProgressEvent(
                    2,
                    6,
                    "Aligning fake segment",
                    item_index=1,
                    item_total=1,
                )
            )
            progress(ProgressEvent(4, 6, "Fingerprinting fake inputs"))
        if self.error:
            raise self.error
        return self.outcome

    def build(
        self,
        config_path: Path,
        report: AlignmentReport,
        *,
        progress: ProgressCallback | None = None,
    ) -> BuildResult:
        self.calls.append(("build", config_path, report))
        if progress is not None:
            progress(ProgressEvent(1, 5, "Validating fake report"))
            progress(ProgressEvent(4, 5, "Building fake timeline"))
        if self.error:
            raise self.error
        return self.result


def test_cli_rejects_subinterpreter_before_importing_native_dependencies() -> None:
    script = """
import sys
import types

interpreters = types.ModuleType("_interpreters")
interpreters.get_current = lambda: 1
interpreters.get_main = lambda: 0
sys.modules["_interpreters"] = interpreters

try:
    import multi_cam_sync.cli
except RuntimeError as error:
    assert "cannot run inside a Python sub-interpreter" in str(error)
    assert not any(
        name == "numpy" or name.startswith(("numpy.", "scipy.", "dtw."))
        for name in sys.modules
    )
else:
    raise AssertionError("sub-interpreter import was not rejected")
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_parser_requires_commands_and_report() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as no_command:
        parser.parse_args([])
    assert no_command.value.code == 2
    with pytest.raises(SystemExit) as no_report:
        parser.parse_args(["analyze", "project.toml"])
    assert no_report.value.code == 2


def test_validate_is_read_only_summary() -> None:
    service = FakeService()
    output = StringIO()
    assert main(["validate", "project.toml"], service=service, stdout=output) == 0
    assert service.calls == [("validate", Path("project.toml"), None)]
    assert "1 video-enabled, 1 audio-only" in output.getvalue()


def test_analyze_writes_report_and_unsafe_returns_four(monkeypatch, tmp_path: Path) -> None:
    service = FakeService()
    written: list[object] = []
    progress_output = StringIO()
    monkeypatch.setattr(
        "multi_cam_sync.cli.write_report", lambda path, report: written.append((path, report))
    )
    path = tmp_path / "report.json"
    assert (
        main(
            ["analyze", "project.toml", "--report", str(path)],
            service=service,
            stderr=progress_output,
        )
        == 0
    )
    assert written == [(path, service.outcome.report)]
    assert "Analyze [1/6]   0% Validating fake inputs" in progress_output.getvalue()
    assert "Analyze [3/6]  33% Aligning fake segment (1/1)" in progress_output.getvalue()
    assert "Analyze [6/6] 100% Analysis complete" in progress_output.getvalue()

    unsafe = SimpleNamespace(
        video_status=SimpleNamespace(value="unsafe"),
        segment_id="segment-0001",
        take="Take A",
        blockers=("ambiguous",),
    )
    service.outcome = AnalysisOutcome(
        report=cast("AlignmentReport", SimpleNamespace(segments=(unsafe,))),
        unsafe_count=1,
    )
    assert main(["analyze", "project.toml", "--report", str(path)], service=service) == 4


def test_build_reads_report_and_calls_gateway_once(monkeypatch, tmp_path: Path) -> None:
    service = FakeService()
    report = object()
    monkeypatch.setattr("multi_cam_sync.cli.read_report", lambda path: report)
    output = StringIO()
    progress_output = StringIO()
    path = tmp_path / "report.json"
    assert (
        main(
            ["build", "project.toml", "--report", str(path)],
            service=service,
            stdout=output,
            stderr=progress_output,
        )
        == 0
    )
    assert service.calls == [("build", Path("project.toml"), report)]
    assert "Built and verified" in output.getvalue()
    assert "Build [1/5]   0% Reading alignment report" in progress_output.getvalue()
    assert "Build [5/5]  80% Building fake timeline" in progress_output.getvalue()
    assert "Build [5/5] 100% Build complete" in progress_output.getvalue()


@pytest.mark.parametrize(
    ("command", "error", "expected"),
    [
        ("validate", ServiceInputError("bad input"), 2),
        ("validate", ResolveConnectionError("connect", "offline"), 3),
        ("build", ResolveOperationError("append", "failed"), 5),
        ("validate", RuntimeError("unexpected"), 1),
    ],
)
def test_exit_code_mapping(command: str, error: Exception, expected: int, monkeypatch) -> None:
    service = FakeService()
    service.error = error
    errors = StringIO()
    if command == "build":
        monkeypatch.setattr("multi_cam_sync.cli.read_report", lambda path: object())
        argv = [command, "project.toml", "--report", "report.json"]
    else:
        argv = [command, "project.toml"]
    assert main(argv, service=service, stderr=errors) == expected
    assert "Traceback" not in errors.getvalue()


def test_verbose_prints_traceback() -> None:
    service = FakeService()
    service.error = ServiceInputError("bad input")
    errors = StringIO()
    assert main(["--verbose", "validate", "project.toml"], service=service, stderr=errors) == 2
    assert "Traceback" in errors.getvalue()
