"""Safe, typed DaVinci Resolve integration.

Importing this package never imports ``DaVinciResolveScript``; connection occurs only
when a gateway method is invoked.
"""

from .errors import (
    ResolveBuildError,
    ResolveConnectionError,
    ResolveDiscoveryError,
    ResolveError,
    ResolveOperationError,
    ResolvePreflightError,
    ResolveVerificationError,
    RollbackStatus,
)
from .gateway import DaVinciResolveGateway
from .protocols import (
    BuildResult,
    EditPlanLike,
    MediaSelector,
    ResolvedMediaItem,
    ResolveGateway,
    ResolveProjectSnapshot,
)

__all__ = [
    "BuildResult",
    "DaVinciResolveGateway",
    "EditPlanLike",
    "MediaSelector",
    "ResolveBuildError",
    "ResolveConnectionError",
    "ResolveDiscoveryError",
    "ResolveError",
    "ResolveGateway",
    "ResolveOperationError",
    "ResolvePreflightError",
    "ResolveProjectSnapshot",
    "ResolveVerificationError",
    "ResolvedMediaItem",
    "RollbackStatus",
]
