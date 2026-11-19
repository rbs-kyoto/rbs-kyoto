from django.shortcuts import redirect, render

from accounts.decorators import club_member_required

from .models import GucchiJob, Script
from .worker import run_next_job


@club_member_required
def index(request):
    result = None
    job = None
    error = ""

    if request.method == "POST":
        text = request.POST.get("text", "").strip()
        target_seconds_text = request.POST.get("target_seconds", "").strip()

        if not text:
            error = "原稿を入力してください。"
        else:
            try:
                target_seconds = (
                    int(target_seconds_text) if target_seconds_text else None
                )
            except ValueError:
                target_seconds = None
                error = "目標尺は秒数で入力してください。"

            if not error:
                script = Script.objects.create(
                    owner=request.user,
                    source_text=text,
                    target_seconds=target_seconds,
                )
                job = GucchiJob.objects.create(
                    owner=request.user,
                    script=script,
                    kind=GucchiJob.Kind.DETERMINISTIC_CHECK,
                    payload={"text": text, "target_seconds": target_seconds},
                )
                job = run_next_job()
                if job is not None:
                    result = job.result

    queued_count = GucchiJob.objects.filter(status=GucchiJob.Status.QUEUED).count()
    recent_jobs = GucchiJob.objects.filter(owner=request.user).select_related("script")[:10]

    return render(
        request,
        "gucchi/index.html",
        {
            "result": result,
            "job": job,
            "error": error,
            "queued_count": queued_count,
            "recent_jobs": recent_jobs,
        },
    )
