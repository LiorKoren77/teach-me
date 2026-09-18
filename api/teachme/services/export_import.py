from __future__ import annotations

from teachme.ingestion.pipeline import PipelineDeps


class ExportImportService:
    def __init__(self, deps: PipelineDeps) -> None:
        self.d = deps
