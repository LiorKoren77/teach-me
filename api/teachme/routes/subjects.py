from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from teachme.auth.clerk import CurrentUser
from teachme.domain.models import PartStatus, SourceStatus, Subject, SubjectState
from teachme.routes.deps import ScopeDep
from teachme.routes.schemas import StudentSource, SubjectSummary
from teachme.services.learning import NotAllowed
from teachme.services.learning_views import SubjectView

router = APIRouter(prefix="/api/subjects", tags=["subjects"])


def _visible(subject: Subject, enabled: list[str]) -> bool:
    """A student sees a published subject, and only in the languages this deployment enables."""
    return (
        subject.state == SubjectState.PUBLISHED
        and subject.current_outline_version is not None
        and any(code in enabled for code in subject.languages)
    )


@router.get("", response_model=list[SubjectSummary])
def list_subjects(user: CurrentUser, scope: ScopeDep) -> list[SubjectSummary]:
    enabled = scope.shared.settings.enabled_languages
    out: list[SubjectSummary] = []
    for subject in scope.subjects.list():
        if not _visible(subject, enabled):
            continue
        parts = scope.progress_service.parts_with_progress(user.user_id, subject)
        out.append(
            SubjectSummary(
                id=subject.id,
                name=subject.name,
                languages=tuple(code for code in subject.languages if code in enabled),
                parts_total=len(parts),
                parts_passed=sum(1 for p in parts if p.status == PartStatus.PASSED),
            )
        )
    return out


@router.get("/{subject_id}", response_model=SubjectView)
def open_subject(subject_id: UUID, user: CurrentUser, scope: ScopeDep) -> SubjectView:
    return scope.learning_service.open_subject(user.user_id, scope.subjects.get(subject_id))


@router.get("/{subject_id}/sources", response_model=list[StudentSource])
def sources(subject_id: UUID, user: CurrentUser, scope: ScopeDep) -> list[StudentSource]:
    """The material behind a published subject, so the reader can see what is being taught from.
    Sources still being ingested are left out: a student has no use for a half-read file."""
    subject = scope.subjects.get(subject_id)
    if subject.state != SubjectState.PUBLISHED:
        raise NotAllowed(f"subject {subject.name!r} is not published")
    return [
        StudentSource(filename=s.filename, media_type=s.media_type, page_count=s.page_count)
        for s in scope.sources.list_by_subject(subject.id)
        if s.status == SourceStatus.READY
    ]
