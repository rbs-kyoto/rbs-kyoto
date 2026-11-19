from django.db import transaction
from django.utils import timezone

from .checker import run_deterministic_check
from .models import GucchiJob


def claim_next_job():
    with transaction.atomic():
        if GucchiJob.objects.select_for_update().filter(
            status=GucchiJob.Status.RUNNING
        ).exists():
            return None

        job = (
            GucchiJob.objects.select_for_update()
            .filter(status=GucchiJob.Status.QUEUED)
            .order_by("queued_at", "pk")
            .first()
        )
        if job is None:
            return None

        updated = GucchiJob.objects.filter(
            pk=job.pk,
            status=GucchiJob.Status.QUEUED,
        ).update(status=GucchiJob.Status.RUNNING, started_at=timezone.now())
        if updated != 1:
            return None
        job.status = GucchiJob.Status.RUNNING
        return job


def process_job(job):
    try:
        if job.kind == GucchiJob.Kind.DETERMINISTIC_CHECK:
            result = run_deterministic_check(
                job.payload.get("text", ""),
                job.payload.get("target_seconds"),
            )
        else:
            raise ValueError(f"未対応のジョブ種類です: {job.kind}")

        GucchiJob.objects.filter(pk=job.pk).update(
            status=GucchiJob.Status.SUCCEEDED,
            result=result,
            error="",
            finished_at=timezone.now(),
        )
        return True
    except Exception as exc:
        GucchiJob.objects.filter(pk=job.pk).update(
            status=GucchiJob.Status.FAILED,
            error=str(exc),
            finished_at=timezone.now(),
        )
        return False


def run_next_job():
    job = claim_next_job()
    if job is None:
        return None
    process_job(job)
    job.refresh_from_db()
    return job
