from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Response

from teachme.auth.clerk import CurrentUser
from teachme.ports.file_store import FileNotFound
from teachme.routes.deps import ScopeDep

router = APIRouter(prefix="/api/subjects", tags=["pages"])


@router.get("/{subject_id}/pages/{global_index}/image")
def page_image(subject_id: UUID, global_index: int, user: CurrentUser, scope: ScopeDep) -> Response:
    """The page image the teaching text points at. Global page indices are the ones that text
    refers to; they are mapped back to a source page through the subject's corpus, which is also
    what refuses a subject the caller cannot open: only a published one has pages to serve."""
    subject = scope.subjects.get(subject_id)
    corpus = scope.learning_service.corpus_for(subject)
    if not 0 <= global_index < corpus.total_pages:
        raise HTTPException(status_code=404, detail="no such page")
    source_id, page_index = corpus.locate(global_index)
    try:
        png = scope.thumbnail_service.png(source_id, page_index)
    except FileNotFound:
        raise HTTPException(status_code=404, detail="page image unavailable") from None
    # Private: the image is part of a published subject's material, not public content, so an
    # intermediary must not keep a copy to hand to the next caller.
    return Response(content=png, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})
