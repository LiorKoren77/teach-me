from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from teachme.auth.roles import AdminUser
from teachme.routes.deps import ScopeDep
from teachme.routes.schemas import AdminSource, AdminSubject
from teachme.services.usage import UsageSummaryRow

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/subjects", response_model=list[AdminSubject])
def subjects(user: AdminUser, scope: ScopeDep) -> list[AdminSubject]:
    return [AdminSubject.of(s) for s in scope.subjects.list()]


@router.get("/subjects/{subject_id}/sources", response_model=list[AdminSource])
def sources(subject_id: UUID, user: AdminUser, scope: ScopeDep) -> list[AdminSource]:
    scope.subjects.get(subject_id)  # 404 instead of an empty list for a subject that is not there
    return [AdminSource.of(s) for s in scope.sources.list_by_subject(subject_id)]


@router.get("/usage", response_model=list[UsageSummaryRow])
def usage(user: AdminUser, scope: ScopeDep, subject_id: UUID | None = None) -> list[UsageSummaryRow]:
    return scope.usage_service.summary(subject_id)
