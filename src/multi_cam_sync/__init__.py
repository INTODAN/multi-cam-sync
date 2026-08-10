"""Synchronize selected camera recordings to a composite master audio track."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("multi-cam-sync")
except PackageNotFoundError:  # pragma: no cover - only used for an unpackaged source tree
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
