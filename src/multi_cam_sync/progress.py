"""Terminal-aware progress reporting for long-running CLI operations."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Lock, Thread, current_thread
from typing import TextIO

_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_BAR_WIDTH = 20
ANALYZE_STEP_COUNT = 6
BUILD_STEP_COUNT = 5


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """One active step, optionally refined by progress through repeated items."""

    completed: int
    total: int
    message: str
    item_index: int | None = None
    item_total: int | None = None

    def __post_init__(self) -> None:
        if self.total <= 0 or not 0 <= self.completed <= self.total:
            raise ValueError("progress totals must satisfy 0 <= completed <= total")
        if not self.message.strip():
            raise ValueError("progress message must not be empty")
        if (self.item_index is None) != (self.item_total is None):
            raise ValueError("item_index and item_total must be supplied together")
        if (
            self.item_index is not None
            and self.item_total is not None
            and (self.completed >= self.total or not 1 <= self.item_index <= self.item_total)
        ):
            raise ValueError("item progress must describe an active, one-based item")

    @property
    def fraction(self) -> float:
        """Return overall completion as a clamped display-only fraction."""
        completed = float(self.completed)
        if self.item_index is not None and self.item_total is not None:
            completed += (self.item_index - 1) / self.item_total
        return min(1.0, max(0.0, completed / self.total))

    @property
    def step_number(self) -> int:
        """Return the one-based active step shown to the user."""
        return self.total if self.completed == self.total else self.completed + 1


ProgressCallback = Callable[[ProgressEvent], None]


class ProgressDisplay:
    """Render an animated TTY line or deterministic redirected-output steps."""

    def __init__(self, operation: str, stream: TextIO, *, interval_seconds: float = 0.08) -> None:
        if not operation.strip():
            raise ValueError("progress operation must not be empty")
        if interval_seconds <= 0:
            raise ValueError("progress interval must be positive")
        self._operation = operation
        self._stream = stream
        self._interval_seconds = interval_seconds
        self._terminal = self._is_terminal(stream)
        self._event: ProgressEvent | None = None
        self._last_line_key: tuple[object, ...] | None = None
        self._frame_index = 0
        self._stop = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._closed = False

    @staticmethod
    def _is_terminal(stream: TextIO) -> bool:
        try:
            return stream.isatty() and os.environ.get("TERM", "") != "dumb"
        except (AttributeError, OSError):
            return False

    def update(self, event: ProgressEvent) -> None:
        """Display a new progress state and start animation when appropriate."""
        with self._lock:
            if self._closed:
                return
            self._event = event
            if self._terminal:
                self._render_terminal(event)
            else:
                self._render_step(event)
        if self._terminal and self._thread is None:
            self._thread = Thread(target=self._animate, name="multi-cam-sync-progress", daemon=True)
            self._thread.start()

    def finish(self, message: str) -> None:
        """Stop animation and leave one completed progress line."""
        self._stop_thread()
        with self._lock:
            if self._closed:
                return
            total = self._event.total if self._event is not None else 1
            final = ProgressEvent(total, total, message)
            if self._terminal:
                self._render_terminal(final, finished=True)
                self._stream.write("\n")
                self._stream.flush()
            else:
                self._render_step(final)
            self._closed = True

    def fail(self) -> None:
        """Stop animation and clear its transient TTY line before an error is printed."""
        self._stop_thread()
        with self._lock:
            if self._closed:
                return
            if self._terminal:
                self._stream.write("\r\x1b[2K")
                self._stream.flush()
            self._closed = True

    def _stop_thread(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join()

    def _animate(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            with self._lock:
                if self._closed or self._event is None:
                    return
                self._frame_index = (self._frame_index + 1) % len(_SPINNER_FRAMES)
                self._render_terminal(self._event)

    def _render_terminal(self, event: ProgressEvent, *, finished: bool = False) -> None:
        marker = "✓" if finished else _SPINNER_FRAMES[self._frame_index]
        self._stream.write(f"\r\x1b[2K{marker} {self._format_line(event)}")
        self._stream.flush()

    def _render_step(self, event: ProgressEvent) -> None:
        key = (
            event.completed,
            event.total,
            event.message,
            event.item_index,
            event.item_total,
        )
        if key == self._last_line_key:
            return
        self._last_line_key = key
        print(self._format_line(event, include_bar=False), file=self._stream)

    def _format_line(self, event: ProgressEvent, *, include_bar: bool = True) -> str:
        percentage = int(event.fraction * 100)
        step = f"[{event.step_number}/{event.total}]"
        item = ""
        if event.item_index is not None and event.item_total is not None:
            item = f" ({event.item_index}/{event.item_total})"
        prefix = f"{self._operation} {step}"
        if not include_bar:
            return f"{prefix} {percentage:3d}% {event.message}{item}"
        filled = int(event.fraction * _BAR_WIDTH)
        bar = "█" * filled + "░" * (_BAR_WIDTH - filled)
        return f"{prefix} [{bar}] {percentage:3d}% {event.message}{item}"
