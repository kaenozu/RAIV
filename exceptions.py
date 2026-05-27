from __future__ import annotations


class RAIVError(Exception):
    """Base exception for RAIV-specific failures."""


class ArchiveError(RAIVError):
    """Base exception for archive handling failures."""


class UnsupportedArchiveFormatError(ArchiveError):
    """Raised when an archive extension is not supported."""


class ArchiveToolNotFoundError(ArchiveError):
    """Raised when no archive extraction backend is available."""


class ArchiveExtractionError(ArchiveError):
    """Raised when an archive backend fails to extract content."""
