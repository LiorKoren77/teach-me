from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID

from pydantic import BaseModel, field_validator

from teachme.domain.models import ContentStatus
from teachme.generation.errors import GenerationError
from teachme.ports.job_runner import JobPayload, JobRunner
from teachme.repositories.jobs import JobRepository
from teachme.repositories.subjects import SubjectRepository
from teachme.services.tutorial import GenerationUnit, TutorialService, UnitKind

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

    @field_validator("unit")
    @classmethod
    def _only_parts(cls, unit: GenerationUnit) -> GenerationUnit:
        """The outline unit is the only one that may create a version, so it belongs to the
        `generate_subject` handler, which resolves that decision once and pins every part to the
        version it produced. Carrying one in a job of its own would create a second version on
        every delivery, which is exactly what the fan-out is built to avoid."""
        if unit.kind is not UnitKind.PART:
            raise ValueError(f"{GENERATE_UNIT} carries a PART unit, not {unit.kind.value!r}")
        return unit


def _decided_version(jobs: JobRepository, job_id: UUID) -> int | None:
    """The outline version an earlier delivery of this same job already resolved, if any."""
    version = (jobs.get(job_id).get("result") or {}).get("outline_version")
    return int(version) if version is not None else None


def run_generate_subject(
    payload: JobPayload,
    job_id: UUID,
    *,
    service: TutorialService,
    subjects: SubjectRepository,
    runner: JobRunner,
    jobs: JobRepository,
    commit: Callable[[], None],
) -> None:
    """Runs the outline and glossary here, then hands each part to a job of its own. Only the
    outline has to happen before anything else; the parts are independent, so they are enqueued
    rather than run, which is what keeps a single invocation short enough for a function.

    Delivered twice - which an at-least-once queue is allowed to do - it must not generate a second
    outline version. The version this run resolved is written to the job row the moment the outline
    unit answers, before a single part is enqueued, so the second delivery skips the outline unit
    entirely and fans out against the version the first one produced. The fan-out itself is
    idempotent the same way: a part whose identical job has already finished is not enqueued again,
    so a redelivery re-runs only the parts that never made it."""
    job = GenerateSubjectJob.model_validate(payload)
    subject = subjects.get(job.subject_id)
    languages = list(job.languages) or None
    parts = list(job.parts) or None
    version = _decided_version(jobs, job_id)
    if version is None:
        plan = service.plan_generation(
            subject, languages=languages, parts=parts, content_only=job.content_only
        )
        outline = service.run_unit(plan[0]).outline
        assert outline is not None  # an outline unit created or reused a version, or it raised
        version = outline.version
        jobs.set_result(job_id, {"outline_version": version})
        commit()
    enqueued = 0
    failure: Exception | None = None
    for unit in service.plan_part_units(subject, languages=languages, parts=parts, outline_version=version):
        unit_payload = GenerateUnitJob(unit=unit).model_dump(mode="json")
        if jobs.has_done(GENERATE_UNIT, unit_payload):
            continue  # a redelivery: this exact part, against this version, is already generated
        try:
            runner.enqueue(GENERATE_UNIT, unit_payload)
        except Exception as exc:
            # An in-process runner runs the unit here and re-raises what it failed with; a queued
            # one can fail to accept the message. Either way that unit's own job row carries the
            # error, and its siblings are independent - one bad part must not cancel the subject.
            log.exception("generate_unit for part %s [%s] failed", unit.part_position, unit.language)
            failure = exc
        else:
            enqueued += 1
    if failure is not None and enqueued == 0:
        # Nothing was handed over at all - a queue that is down, not one bad part. No sibling job
        # is left to carry the error, so this job has to be the one that says the run failed.
        raise failure


def run_generate_unit(payload: JobPayload, *, service: TutorialService) -> None:
    """One part in one language. The service records a part it could not generate as FAILED content
    and returns rather than raising, so that a whole run survives one bad part; a job has to say so
    in its own row, which is what the raise below is for."""
    unit = GenerateUnitJob.model_validate(payload).unit
    result = service.run_unit(unit).part
    if result is not None and result.content_status is not ContentStatus.READY:
        raise GenerationError(result.error or f"part {unit.part_position} [{unit.language}] failed")
