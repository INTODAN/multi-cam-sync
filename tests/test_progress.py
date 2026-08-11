from __future__ import annotations

from collections.abc import Callable
from io import StringIO

import pytest

from multi_cam_sync.progress import ProgressDisplay, ProgressEvent


class TerminalBuffer(StringIO):
    def isatty(self) -> bool:
        return True


def test_item_progress_contributes_to_overall_fraction() -> None:
    event = ProgressEvent(2, 6, "Aligning", item_index=2, item_total=4)

    assert event.step_number == 3
    assert event.fraction == pytest.approx(0.375)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ProgressEvent(-1, 6, "Invalid"),
        lambda: ProgressEvent(7, 6, "Invalid"),
        lambda: ProgressEvent(1, 6, "Invalid", item_index=1),
        lambda: ProgressEvent(1, 6, "Invalid", item_total=2),
        lambda: ProgressEvent(1, 6, "Invalid", item_index=0, item_total=2),
    ],
)
def test_invalid_progress_events_are_rejected(factory: Callable[[], ProgressEvent]) -> None:
    with pytest.raises(ValueError):
        factory()


def test_redirected_progress_is_stable_and_deduplicated() -> None:
    stream = StringIO()
    display = ProgressDisplay("Analyze", stream)
    first = ProgressEvent(0, 3, "Validating")

    display.update(first)
    display.update(first)
    display.update(ProgressEvent(1, 3, "Aligning", item_index=1, item_total=2))
    display.finish("Complete")

    assert stream.getvalue().splitlines() == [
        "Analyze [1/3]   0% Validating",
        "Analyze [2/3]  33% Aligning (1/2)",
        "Analyze [3/3] 100% Complete",
    ]


def test_terminal_progress_uses_spinner_bar_and_clean_completion(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = TerminalBuffer()
    display = ProgressDisplay("Build", stream, interval_seconds=10)

    display.update(ProgressEvent(1, 5, "Checking inputs"))
    display.finish("Complete")

    rendered = stream.getvalue()
    assert "\r\x1b[2K⠋ Build [2/5]" in rendered
    assert "[████░░░░░░░░░░░░░░░░]" in rendered
    assert "✓ Build [5/5] [████████████████████] 100% Complete\n" in rendered


def test_terminal_failure_clears_transient_line(monkeypatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = TerminalBuffer()
    display = ProgressDisplay("Build", stream, interval_seconds=10)

    display.update(ProgressEvent(0, 5, "Starting"))
    display.fail()

    assert stream.getvalue().endswith("\r\x1b[2K")
