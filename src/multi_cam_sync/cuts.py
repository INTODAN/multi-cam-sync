"""Parser and segment builder for the composite-cuts text format."""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from fractions import Fraction

from pydantic import ValidationError

from multi_cam_sync.domain.errors import CutListError
from multi_cam_sync.domain.models import CutTransition, MasterSegment
from multi_cam_sync.time_values import (
    clean_take_name,
    parse_decimal_seconds,
    parse_decimal_timestamp,
    parse_frame_timestamp,
)

_FIELD_PATTERN = re.compile(r"^(?P<field>Out|In)\s*:\s*(?P<value>.*)$", re.IGNORECASE)


def parse_cut_list(text: str, *, frame_rate: Fraction | None = None) -> tuple[CutTransition, ...]:
    """Parse decimal or timeline-frame transition blocks from a cuts document."""
    if not isinstance(text, str):
        raise CutListError("cut list must be text")

    transitions: list[CutTransition] = []
    block: dict[str, tuple[str, int]] = {}
    started = False

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        field_match = _FIELD_PATTERN.fullmatch(line)
        if not started:
            if field_match is None or field_match.group("field").casefold() != "out":
                continue
            started = True

        if field_match is not None:
            field = field_match.group("field").casefold()
            key = "out" if field == "out" else "in"
            if key in block:
                raise CutListError(
                    f"cut list line {line_number}: duplicate {field_match.group('field')} field"
                )
            expected = "out" if not block else "in"
            if key != expected:
                raise CutListError(
                    f"cut list line {line_number}: expected {expected.title()} field, "
                    f"got {field_match.group('field')}"
                )
            try:
                take = clean_take_name(field_match.group("value"))
            except ValueError as error:
                raise CutListError(f"cut list line {line_number}: {error}") from error
            block[key] = (take, line_number)
            continue

        if set(block) != {"out", "in"}:
            expected = "Out" if not block else "In"
            raise CutListError(
                f"cut list line {line_number}: expected {expected} field, got {line!r}"
            )

        try:
            if ";" in line:
                raise ValueError(
                    "drop-frame cut timecode is not supported; use decimal time or "
                    "non-drop HH:MM:SS:FF"
                )
            if line.count(":") == 3:
                if frame_rate is None:
                    raise ValueError(
                        "frame timecode requires the active Resolve timeline frame rate"
                    )
                timestamp = parse_frame_timestamp(line, frame_rate)
            else:
                timestamp = parse_decimal_timestamp(line)
            transition = CutTransition(
                outgoing_take=block["out"][0],
                incoming_take=block["in"][0],
                master_time=timestamp,
            )
        except (ValueError, ValidationError) as error:
            raise CutListError(f"cut list line {line_number}: {error}") from error
        if transitions and timestamp <= transitions[-1].master_time:
            raise CutListError(
                f"cut list line {line_number}: cut time {line!r} must be later than "
                f"the previous cut at {transitions[-1].master_time} seconds"
            )
        if transitions and transitions[-1].incoming_take_key != transition.outgoing_take_key:
            previous = transitions[-1]
            raise CutListError(
                f"cut list line {block['out'][1]}: discontinuous transition; previous In "
                f"{previous.incoming_take!r} does not match Out {transition.outgoing_take!r}"
            )
        transitions.append(transition)
        block = {}

    if block:
        start_line = min(line_number for _, line_number in block.values())
        missing = [name for name in ("Out", "In", "timestamp") if name.casefold() not in block]
        raise CutListError(
            f"cut list line {start_line}: incomplete trailing block; missing {', '.join(missing)}"
        )
    if not transitions:
        raise CutListError("cut list contains no transition blocks")
    return tuple(transitions)


def build_master_segments(
    cuts: Iterable[CutTransition], master_duration: object | None = None
) -> tuple[MasterSegment, ...]:
    """Build stable, ordered master segments from validated transitions."""
    transitions = tuple(cuts)
    if not transitions:
        raise CutListError("at least one cut transition is required to build master segments")

    previous_time: Decimal | None = None
    for index, transition in enumerate(transitions):
        if previous_time is not None and transition.master_time <= previous_time:
            raise CutListError(f"cut {index + 1} must be later than the preceding cut")
        if index and transitions[index - 1].incoming_take_key != transition.outgoing_take_key:
            raise CutListError(
                f"cut {index + 1} is discontinuous: {transitions[index - 1].incoming_take!r} "
                f"does not match {transition.outgoing_take!r}"
            )
        previous_time = transition.master_time

    duration: Decimal | None = None
    if master_duration is not None:
        try:
            duration = parse_decimal_seconds(master_duration, field_name="master_duration")
        except ValueError as error:
            raise CutListError(str(error)) from error
        if duration <= 0:
            raise CutListError("master_duration must be greater than zero")
        if transitions[-1].master_time >= duration:
            raise CutListError(
                f"last cut at {transitions[-1].master_time} seconds must be before "
                f"master duration {duration} seconds"
            )

    segment_takes = [transitions[0].outgoing_take]
    segment_takes.extend(transition.incoming_take for transition in transitions)
    starts = [Decimal(0)]
    starts.extend(transition.master_time for transition in transitions)
    ends: list[Decimal | None] = [transition.master_time for transition in transitions]
    ends.append(duration)

    return tuple(
        MasterSegment(
            id=f"segment-{index + 1:04d}",
            index=index,
            display_take=take,
            start_seconds=starts[index],
            end_seconds=ends[index],
        )
        for index, take in enumerate(segment_takes)
    )
