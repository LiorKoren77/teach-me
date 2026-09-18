from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from teachme.domain.models import ContentStatus
from teachme.generation.errors import GenerationError
from teachme.ports.job_runner import JobPayload, JobRunner
from teachme.repositories.subjects import SubjectRepository
from teachme.services.tutorial import GenerationUnit, TutorialService

log = logging.getLogger(__name__)

GENERATE_SUBJECT = "generate_subject"
GENERATE_UNIT = "generate_unit"


class GenerateSubjectJob(BaseModel):
    """One subject's whole generation, as one message. Empty `languages` means every language the
    subject has, empty `parts` every part of the outline - the same defaults the CLI takes."""

    subject_id: UUID
    languages: tuple[str, ...] = ()
    parts: tuple[int, ...] = ()
    content_only: bool = False


class GenerateUnitJob(BaseModel):
    """One part of one subject, in one language."""

    unit: GenerationUnit


def run_generate_subject(
    payload: JobPayload, *, service: TutorialService, subjects: SubjectRepository, runner: JobRunner
) -> None:
    """Runs the outline and glossary here, then hands each part to a job of its own. Only the
    outline has to happen before anything else; the parts are independent, so they are enqueued
    rather than run, which is what keeps a single invocation short enough for a function."""
    job = GenerateSubjectJob.model_validate(payload)
    subject = subjects.get(job.subject_id)
    languages = list(job.languages) or None
    parts = list(job.parts) or None
    plan = service.plan_generation(subject, languages=languages, parts=parts, content_only=job.content_only)
    service.run_unit(plan[0])
    for unit in service.plan_part_units(subject, languages=languages, parts=parts):
        try:
            runner.enqueue(GENERATE_UNIT, GenerateUnitJob(unit=unit).model_dump(mode="json"))
        except Exception:
            # An in-process runner runs the unit here and re-raises what it failed with; a queued
            # one can fail to accept the message. Either way that unit's own job row carries the
            # error, and its siblings are independent - one bad part must not cancel the subject.
            log.exception("generate_unit for part %s [%s] failed", unit.part_position, unit.language)


def run_generate_unit(payload: JobPayload, *, service: TutorialService) -> None:
    """One part in one language. The service records a part it could not generate as FAILED content
    and returns rather than raising, so that a whole run survives one bad part; a job has to say so
    in its own row, which is what the raise below is for."""
    unit = GenerateUnitJob.model_validate(payload).unit
    result = service.run_unit(unit)
    if result is not None and result.content_status is not ContentStatus.READY:
        raise GenerationError(result.error or f"part {unit.part_position} [{unit.language}] failed")
