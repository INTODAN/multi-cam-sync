from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from multi_cam_sync.cuts import build_master_segments, parse_cut_list
from multi_cam_sync.domain.errors import CutListError

ARABESQUES_CUTS = Path(__file__).parents[1] / "examples" / "Arabesques_composite_cuts.txt"


def test_arabesques_cut_list_builds_expected_segments() -> None:
    transitions = parse_cut_list(ARABESQUES_CUTS.read_text(encoding="utf-8"))
    segments = build_master_segments(transitions)

    assert len(transitions) == 28
    assert len(segments) == 29
    assert transitions[9].incoming_take == "Take 6 B"
    assert transitions[10].outgoing_take_key == "Take 6 B"
    assert segments[0].id == "segment-0001"
    assert segments[0].index == 0
    assert segments[-1].id == "segment-0029"
    assert segments[-1].end_seconds is None
    assert all(isinstance(segment.start_seconds, Decimal) for segment in segments)


def test_headers_blank_lines_crlf_and_case_insensitive_fields_are_accepted() -> None:
    text = (
        "Composite cut notes\r\n\r\n"
        "out:   Take  1\r\n"
        "IN:\tTake 2\r\n"
        "00:00:01.0000001\r\n\r\n"
        "Out: Take 2\r\n"
        "In: Take 3\r\n"
        "00:00:02.5\r\n"
    )

    transitions = parse_cut_list(text)

    assert transitions[0].outgoing_take == "Take 1"
    assert transitions[0].master_time == Decimal("1.0000001")
    assert transitions[1].outgoing_take_key == "Take 2"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("heading only", "no transition"),
        ("Out: Take 1\n", "incomplete trailing block"),
        ("Out: Take 1\nIn: Take 2\n", "missing timestamp"),
        ("Out: Take 1\nOut: Take 2\nIn: Take 3\n00:00:01", "duplicate Out"),
        ("Out: Take 1\nIn: Take 2\nIn: Take 3\n00:00:01", "duplicate In"),
        ("Out: Take 1\nwhat is this\nIn: Take 2\n00:00:01", "expected In"),
        ("Out: Take 1\nIn: Take 2\nnot-a-time", "invalid timestamp"),
        (
            "Out: Take 1\nIn: Take 2\n00:00:01\nOut: Take 3\nIn: Take 4\n00:00:02",
            "discontinuous",
        ),
        (
            "Out: Take 1\nIn: Take 2\n00:00:01\nOut: Take 2\nIn: Take 3\n00:00:01",
            "later than",
        ),
        (
            "Out: Take 1\nIn: Take 2\n00:00:02\nOut: Take 2\nIn: Take 3\n00:00:01",
            "later than",
        ),
    ],
)
def test_malformed_cut_lists_are_actionable(text: str, message: str) -> None:
    with pytest.raises(CutListError, match=message):
        parse_cut_list(text)


def test_master_duration_closes_last_segment() -> None:
    transitions = parse_cut_list("Out: A\nIn: B\n00:00:01.25")

    segments = build_master_segments(transitions, master_duration="00:00:03.500")

    assert [(item.start_seconds, item.end_seconds) for item in segments] == [
        (Decimal(0), Decimal("1.25")),
        (Decimal("1.25"), Decimal("3.500")),
    ]


@pytest.mark.parametrize("duration", ["00:00:01.250", "00:00:01.000", 0, -1])
def test_master_duration_must_follow_every_cut(duration: object) -> None:
    transitions = parse_cut_list("Out: A\nIn: B\n00:00:01.250")

    with pytest.raises(CutListError, match="duration"):
        build_master_segments(transitions, master_duration=duration)


def test_models_are_immutable_and_serialize_deterministically() -> None:
    transitions = parse_cut_list("Out: A\nIn: B\n00:00:01")
    first = build_master_segments(transitions)
    second = build_master_segments(transitions)

    assert first == second
    assert first[0].model_dump_json() == second[0].model_dump_json()
    with pytest.raises(ValidationError, match="frozen"):
        setattr(  # noqa: B010 - deliberately exercise runtime immutability
            first[0], "display_take", "changed"
        )
