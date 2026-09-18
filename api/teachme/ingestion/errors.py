from __future__ import annotations


class IngestionError(Exception):
    """Base class; the pipeline records str(exc) on the source."""


class UnsupportedMediaType(IngestionError):
    pass


class TooManyPages(IngestionError):
    pass


class ExtractionError(IngestionError):
    pass


class CoverageError(IngestionError):
    pass


class SubjectLocked(IngestionError):
    pass
