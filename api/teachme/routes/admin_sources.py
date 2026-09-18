from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, File, Request, Response, UploadFile

from teachme.auth.roles import AdminUser
from teachme.domain.models import Subject, SubjectState
from teachme.ingestion.errors import SubjectLocked, UploadTooLarge
from teachme.ingestion.pipeline import INGEST_SOURCE
from teachme.routes.deps import ScopeDep
from teachme.routes.schemas import (
    AdminJob,
    AdminJobRef,
    AdminSubject,
    AdminSubjectStatus,
    AdminUpload,
    Capabilities,
)
from teachme.services.generation_jobs import GENERATE_SUBJECT, GenerateSubjectJob

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_draft(subject: Subject) -> Subject:
    """Everything that changes what a subject teaches is refused while students are using it.
    The services check this too; the routes check it first so an upload is refused before its
    body is stored, and so `generate` refuses now rather than inside a job nobody is watching."""
    if subject.state == SubjectState.PUBLISHED:
        raise SubjectLocked(f"subject {subject.name!r} is published; unpublish before changing it")
    return subject


def _refuse_oversized(request: Request, limit: int) -> None:
    """Content-Length covers the whole multipart body, so this is an upper bound on the file and
    never lets one through: a body that does not fit cannot contain a file that does."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > limit:
        raise UploadTooLarge(f"upload is larger than the {limit} byte limit")


@router.get("/capabilities", response_model=Capabilities)
def capabilities(user: AdminUser, scope: ScopeDep) -> Capabilities:
    return Capabilities(
        accepted_media_types=sorted(scope.source_service.accepted_media_types()),
        max_upload_bytes=scope.shared.settings.max_upload_bytes,
    )


@router.post("/subjects/{subject_id}/sources", response_model=AdminUpload)
def upload_source(
    subject_id: UUID,
    user: AdminUser,
    scope: ScopeDep,
    request: Request,
    file: Annotated[UploadFile, File()],
) -> AdminUpload:
    """The browser's path to the same `SourceService.register` and `ingest_source` job the CLI
    uses: nothing about ingestion knows which of the two put the file there."""
    limit = scope.shared.settings.max_upload_bytes
    _refuse_oversized(request, limit)
    subject = _require_draft(scope.subjects.get(subject_id))
    data = file.file.read()
    if len(data) > limit:
        raise UploadTooLarge(f"upload is larger than the {limit} byte limit")
    source = scope.source_service.register(subject, file.filename or "", data)
    job_id = scope.job_runner.enqueue(INGEST_SOURCE, {"source_id": str(source.id)})
    return AdminUpload.of_job(scope.sources.get(source.id), job_id)


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: UUID, user: AdminUser, scope: ScopeDep) -> Response:
    scope.source_service.delete(source_id)
    return Response(status_code=204)


@router.post("/sources/{source_id}/reingest", response_model=AdminJobRef)
def reingest_source(source_id: UUID, user: AdminUser, scope: ScopeDep) -> AdminJobRef:
    source = scope.source_service.mark_for_reingest(source_id)
    return AdminJobRef(job_id=scope.job_runner.enqueue(INGEST_SOURCE, {"source_id": str(source.id)}))


@router.get("/jobs/{job_id}", response_model=AdminJob)
def job(job_id: UUID, user: AdminUser, scope: ScopeDep) -> AdminJob:
    return AdminJob(**scope.jobs.get(job_id))


@router.post("/subjects/{subject_id}/generate", response_model=AdminJobRef)
def generate(subject_id: UUID, user: AdminUser, scope: ScopeDep) -> AdminJobRef:
    subject = _require_draft(scope.subjects.get(subject_id))
    # Plan the run here, so everything it would refuse - an unready subject above all - is a status
    # code the admin sees now, rather than a queued job that fails where nobody is looking.
    scope.tutorial_service.plan_generation(subject)
    payload = GenerateSubjectJob(subject_id=subject.id).model_dump(mode="json")
    return AdminJobRef(job_id=scope.job_runner.enqueue(GENERATE_SUBJECT, payload))


@router.post("/subjects/{subject_id}/publish", response_model=AdminSubject)
def publish(subject_id: UUID, user: AdminUser, scope: ScopeDep) -> AdminSubject:
    return AdminSubject.of(scope.tutorial_service.publish(scope.subjects.get(subject_id)))


@router.post("/subjects/{subject_id}/unpublish", response_model=AdminSubject)
def unpublish(subject_id: UUID, user: AdminUser, scope: ScopeDep) -> AdminSubject:
    return AdminSubject.of(scope.tutorial_service.unpublish(scope.subjects.get(subject_id)))


@router.get("/subjects/{subject_id}/status", response_model=AdminSubjectStatus)
def status(subject_id: UUID, user: AdminUser, scope: ScopeDep) -> AdminSubjectStatus:
    return AdminSubjectStatus.of(scope.tutorial_service.status(scope.subjects.get(subject_id)))
