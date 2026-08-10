"""Deterministic, adjacency-aware Resolve clip colors."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

RESOLVE_COLORS: tuple[str, ...] = (
    "Orange",
    "Teal",
    "Purple",
    "Lime",
    "Pink",
    "Blue",
    "Yellow",
    "Navy",
    "Green",
    "Chocolate",
    "Apricot",
    "Violet",
    "Olive",
    "Tan",
    "Beige",
    "Brown",
)

_COLOR_FEATURES: dict[str, tuple[str, int, int]] = {
    "Orange": ("warm", 30, 60),
    "Apricot": ("warm", 35, 80),
    "Yellow": ("warm", 55, 85),
    "Pink": ("warm", 330, 70),
    "Lime": ("green", 90, 75),
    "Green": ("green", 120, 50),
    "Olive": ("green", 100, 35),
    "Teal": ("cyan", 180, 50),
    "Blue": ("blue", 220, 50),
    "Navy": ("blue", 225, 25),
    "Purple": ("purple", 280, 45),
    "Violet": ("purple", 265, 65),
    "Tan": ("earth", 40, 70),
    "Beige": ("earth", 45, 85),
    "Brown": ("earth", 25, 40),
    "Chocolate": ("earth", 20, 25),
}


def _similarity(left: str, right: str) -> float:
    if left == right:
        return 100.0
    left_family, left_hue, left_light = _COLOR_FEATURES[left]
    right_family, right_hue, right_light = _COLOR_FEATURES[right]
    family = 15.0 if left_family == right_family else 0.0
    hue_distance = min(abs(left_hue - right_hue), 360 - abs(left_hue - right_hue))
    hue = max(0.0, (180.0 - hue_distance) / 180.0) * 15.0
    light = (1.0 - abs(left_light - right_light) / 100.0) * 5.0
    return family + hue + light


def assign_take_colors(take_sequence: Sequence[str]) -> dict[str, str]:
    """Assign stable colors while favoring contrast between nearby takes."""
    first_seen = list(dict.fromkeys(take_sequence))
    occurrences = Counter(take_sequence)
    adjacency: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for index, take in enumerate(take_sequence):
        for offset, weight in ((-1, 3.0), (1, 3.0), (-2, 1.0), (2, 1.0)):
            neighbor_index = index + offset
            if 0 <= neighbor_index < len(take_sequence):
                neighbor = take_sequence[neighbor_index]
                if neighbor != take:
                    adjacency[take][neighbor] += weight

    order_index = {take: index for index, take in enumerate(first_seen)}
    assignment_order = sorted(first_seen, key=lambda take: (-occurrences[take], order_index[take]))
    assigned: dict[str, str] = {}
    color_use = Counter[str]()
    for take in assignment_order:
        best_color = RESOLVE_COLORS[0]
        best_score = float("inf")
        for palette_index, candidate in enumerate(RESOLVE_COLORS):
            score = color_use[candidate] * 50.0
            for neighbor, weight in adjacency[take].items():
                if neighbor in assigned:
                    score += weight * _similarity(candidate, assigned[neighbor])
            score += palette_index / 1000.0
            if score < best_score:
                best_color = candidate
                best_score = score
        assigned[take] = best_color
        color_use[best_color] += 1

    return {take: assigned[take] for take in first_seen}
