from __future__ import annotations

import importlib
import sys

import pytest

from multi_cam_sync.resolve.connection import connect_resolve
from multi_cam_sync.resolve.errors import ResolveConnectionError

from .fakes.resolve import make_resolve_fake  # ty: ignore[unresolved-import]


def test_resolve_package_import_does_not_import_vendor_module() -> None:
    sys.modules.pop("DaVinciResolveScript", None)

    package = importlib.import_module("multi_cam_sync.resolve")
    importlib.reload(package)

    assert "DaVinciResolveScript" not in sys.modules


def test_connection_imports_vendor_module_only_when_called() -> None:
    fake = make_resolve_fake()
    loaded: list[str] = []

    def loader(name: str) -> object:
        loaded.append(name)
        return fake.module

    session = connect_resolve(module_loader=loader)

    assert session.project is fake.project
    assert loaded == ["DaVinciResolveScript"]
    assert fake.events[:5] == [
        ("scriptapp", "Resolve"),
        ("Resolve.GetProjectManager",),
        ("ProjectManager.GetCurrentProject",),
        ("Project.GetMediaPool",),
        ("MediaPool.GetRootFolder",),
    ]


@pytest.mark.parametrize(
    ("failures", "operation"),
    [
        ({"scriptapp": None}, "scriptapp"),
        ({"Resolve.GetProjectManager": False}, "Resolve.GetProjectManager"),
        ({"ProjectManager.GetCurrentProject": None}, "ProjectManager.GetCurrentProject"),
        ({"Project.GetMediaPool": False}, "Project.GetMediaPool"),
        ({"MediaPool.GetRootFolder": None}, "MediaPool.GetRootFolder"),
    ],
)
def test_connection_rejects_every_missing_required_object(
    failures: dict[str, object], operation: str
) -> None:
    fake = make_resolve_fake(failures=failures)

    with pytest.raises(ResolveConnectionError, match=operation):
        connect_resolve(module_loader=lambda _: fake.module)


def test_connection_reports_missing_vendor_module() -> None:
    def missing(_: str) -> object:
        raise ModuleNotFoundError("not installed")

    with pytest.raises(ResolveConnectionError, match="Resolve scripting module is unavailable"):
        connect_resolve(module_loader=missing)
