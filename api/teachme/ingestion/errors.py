from __future__ import annotations


class IngestionError(Exception):
    """Base class; the pipeline records str(exc) on the source."""


class UnsupportedMediaType(IngestionError):
    pass


class TooManyPages(IngestionError):
    pass


class UploadTooLarge(IngestionError):
    pass


class TooManyUploads(IngestionError):
    """This admin has uploaded more than MAX_UPLOADS_PER_HOUR sources in the last hour."""


class ExtractionError(IngestionError):
    pass


class CoverageError(IngestionError):
    pass


class SubjectLocked(IngestionError):
    pass
