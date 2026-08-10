from __future__ import annotations

import importlib
from importlib.metadata import entry_points

import multi_cam_sync
from multi_cam_sync.cli import main


def test_package_import_is_independent_of_resolve_and_media() -> None:
    module = importlib.reload(multi_cam_sync)

    assert module.__version__
    assert "DaVinciResolveScript" not in module.__dict__


def test_reserved_console_entry_point_is_callable() -> None:
    matching = [
        entry_point
        for entry_point in entry_points(group="console_scripts")
        if entry_point.name == "multi-cam-sync"
    ]

    assert callable(main)
    assert len(matching) == 1
    assert matching[0].value == "multi_cam_sync.cli:main"
    assert matching[0].load() is main
