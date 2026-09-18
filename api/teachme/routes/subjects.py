from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from teachme.auth.clerk import CurrentUser
from teachme.domain.models import PartStatus, Subject, SubjectState
from teachme.routes.deps import ScopeDep
from teachme.routes.schemas import SubjectSummary
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
