"""Lazy connection setup for the external Resolve scripting API."""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

from .errors import ResolveConnectionError
from .protocols import (
    ModuleLoader,
    RawFolder,
    RawMediaPool,
    RawProject,
    RawProjectManager,
    RawResolve,
    ResolveScriptModule,
)


@dataclass(frozen=True, slots=True)
class ResolveSession:
    """The required object graph for one read or mutation transaction."""

    resolve: RawResolve
    project_manager: RawProjectManager
    project: RawProject
    media_pool: RawMediaPool
    root_folder: RawFolder


def _required_call(operation: str, function: Callable[[], object]) -> object:
    try:
        value = function()
    except Exception as exc:
        raise ResolveConnectionError(
            operation, f"API call raised {type(exc).__name__}: {exc}"
        ) from exc
    if value is None or value is False:
        raise ResolveConnectionError(operation, "API returned no usable object")
    return value


def connect_resolve(*, module_loader: ModuleLoader = importlib.import_module) -> ResolveSession:
    """Import Resolve lazily and require an open, usable current project."""

    try:
        loaded = module_loader("DaVinciResolveScript")
    except (ImportError, ModuleNotFoundError) as exc:
        raise ResolveConnectionError(
            "import DaVinciResolveScript",
            "Resolve scripting module is unavailable; install/configure it and enable "
            "External scripting",
        ) from exc
    except Exception as exc:
        raise ResolveConnectionError(
            "import DaVinciResolveScript", f"module loader raised {type(exc).__name__}: {exc}"
        ) from exc

    module = cast("ResolveScriptModule", loaded)
    try:
        resolve = module.scriptapp("Resolve")
    except Exception as exc:
        raise ResolveConnectionError(
            "DaVinciResolveScript.scriptapp('Resolve')",
            f"API call raised {type(exc).__name__}: {exc}",
        ) from exc
    if resolve is None or resolve is False:  # type: ignore[comparison-overlap]
        raise ResolveConnectionError(
            "DaVinciResolveScript.scriptapp('Resolve')",
            "could not connect to a running Resolve instance",
        )

    project_manager = cast(
        "RawProjectManager",
        _required_call("Resolve.GetProjectManager", resolve.GetProjectManager),
    )
    project = cast(
        "RawProject",
        _required_call("ProjectManager.GetCurrentProject", project_manager.GetCurrentProject),
    )
    media_pool = cast("RawMediaPool", _required_call("Project.GetMediaPool", project.GetMediaPool))
    root_folder = cast(
        "RawFolder", _required_call("MediaPool.GetRootFolder", media_pool.GetRootFolder)
    )
    return ResolveSession(resolve, project_manager, project, media_pool, root_folder)
