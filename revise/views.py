import re

from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from accounts.decorators import club_member_required
from accounts.models import NotificationHistory

from .models import LearningPair, ManualRevision, ProofreadRole, ReviseComment, RevisePost


OBSERVATION_FIELDS = (
    ("尺と形式", "length"),
    ("日付・数字の間違い", "numbers"),
    ("表記", "notation"),
    ("文法・言葉遣い", "grammar"),
    ("読んだときの分かりにくさ", "readability"),
    ("言い換え・短縮", "rewrite"),
)


def has_proofread_role(user):
    return bool(user.is_authenticated and ProofreadRole.objects.filter(user=user).exists())


@club_member_required
def index(request):
    status = request.GET.get("status", "").strip()
    query = request.GET.get("q", "").strip()
    practice = request.GET.get("practice") == "1"

    posts = RevisePost.objects.select_related("author").prefetch_related("comments")
    if status in RevisePost.Status.values:
        posts = posts.filter(status=status)
    if practice:
        posts = posts.filter(is_practice=True)
    if query:
        posts = posts.filter(Q(title__icontains=query) | Q(body__icontains=query))

    return render(
        request,
        "revise/index.html",
        {
            "posts": posts,
            "status_filter": status,
            "query": query,
            "practice_only": practice,
            "can_proofread": has_proofread_role(request.user),
        },
    )


@club_member_required
def new_post(request):
    error = ""
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "").strip()
        instruction = request.POST.get("instruction", "").strip()
        target_text = request.POST.get("target_seconds", "").strip()
        try:
            target_seconds = int(target_text) if target_text else None
        except ValueError:
            target_seconds = None
            error = "目標の尺は秒数で入力してください。"

        if not title:
            error = "タイトルを入力してください。"
        if not body:
            error = "原稿を入力してください。"

        if not error:
            post = RevisePost.objects.create(
                author=request.user,
                title=title,
                body=body,
                instruction=instruction,
                target_seconds=target_seconds,
                is_practice=request.POST.get("is_practice") == "1",
            )
            for role in ProofreadRole.objects.select_related("user"):
                NotificationHistory.objects.create(
                    user=role.user,
                    kind="revise",
                    title="新しいRevise投稿",
                    body=title,
                    url=f"/revise/{post.pk}/",
                )
            return redirect("revise:detail", post_id=post.pk)

    return render(request, "revise/new.html", {"error": error})


@club_member_required
def detail(request, post_id):
    post = get_object_or_404(
        RevisePost.objects.select_related("author", "closed_by").prefetch_related(
            "comments__author",
            "manual_revisions__author",
        ),
        pk=post_id,
    )

    if request.method == "POST":
        body = request.POST.get("body", "").strip()
        if body:
            ReviseComment.objects.create(post=post, author=request.user, body=body)
            return redirect("revise:detail", post_id=post.pk)

    character_count = len(re.sub(r"\s", "", post.body))
    median_seconds = round(character_count / 325 * 60)
    sentences = [sentence.strip() for sentence in re.split(r"[。！？]", post.body) if sentence.strip()]
    long_sentence_count = sum(len(re.sub(r"\s", "", sentence)) > 60 for sentence in sentences)

    can_close = (
        post.author_id == request.user.pk
        or has_proofread_role(request.user)
    )
    return render(
        request,
        "revise/detail.html",
        {
            "post": post,
            "character_count": character_count,
            "reading_seconds": median_seconds,
            "reading_min": round(character_count / 350 * 60),
            "reading_max": round(character_count / 300 * 60),
            "long_sentence_count": long_sentence_count,
            "can_proofread": has_proofread_role(request.user),
            "can_close": can_close,
        },
    )


@club_member_required
def toggle_close(request, post_id):
    post = get_object_or_404(RevisePost, pk=post_id)
    if post.author_id != request.user.pk and not has_proofread_role(request.user):
        raise PermissionDenied
    if request.method != "POST":
        raise PermissionDenied

    if post.status == RevisePost.Status.OPEN:
        post.status = RevisePost.Status.CLOSED
        post.closed_at = timezone.now()
        post.closed_by = request.user
    else:
        post.status = RevisePost.Status.OPEN
        post.closed_at = None
        post.closed_by = None
    post.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    return redirect("revise:detail", post_id=post.pk)


@club_member_required
def proofread(request, post_id):
    post = get_object_or_404(RevisePost, pk=post_id)
    if not has_proofread_role(request.user):
        raise PermissionDenied

    character_count = len(re.sub(r"\s", "", post.body))
    sentences = [sentence.strip() for sentence in re.split(r"[。！？]", post.body) if sentence.strip()]
    long_sentences = [
        sentence
        for sentence in sentences
        if len(re.sub(r"\s", "", sentence)) > 60
    ]

    error = ""
    if request.method == "POST":
        revised_body = request.POST.get("revised_body", "").strip()
        observations = {}
        missing = []
        for label, key in OBSERVATION_FIELDS:
            status = request.POST.get(f"{key}_status", "").strip()
            text = request.POST.get(f"{key}_text", "").strip()
            if not status:
                missing.append(label)
            observations[label] = {"status": status, "text": text}
        observations["その他"] = {
            "status": request.POST.get("other_status", "").strip(),
            "text": request.POST.get("other_text", "").strip(),
        }

        if not revised_body:
            error = "添正文を入力してください。"
        elif missing:
            error = "6観点すべての指摘有無を選んでください。"
        else:
            review = ManualRevision.objects.create(
                post=post,
                author=request.user,
                revised_body=revised_body,
                observations=observations,
                audio=request.FILES.get("audio"),
            )
            post.status = RevisePost.Status.OPEN
            post.save(update_fields=["status", "updated_at"])
            return redirect("revise:detail", post_id=post.pk)

    return render(
        request,
        "revise/proofread.html",
        {
            "post": post,
            "observations": OBSERVATION_FIELDS,
            "character_count": character_count,
            "reading_seconds": round(character_count / 325 * 60),
            "target_seconds": post.target_seconds,
            "long_sentences": long_sentences,
            "error": error,
        },
    )


@club_member_required
def learning_pair_queue(request):
    if not has_proofread_role(request.user):
        raise PermissionDenied

    if request.method == "POST":
        pair = get_object_or_404(LearningPair, pk=request.POST.get("pair_id"))
        decision = request.POST.get("decision")
        if decision not in ("approved", "rejected"):
            raise PermissionDenied
        pair.status = decision
        pair.reviewed_by = request.user
        pair.reviewed_at = timezone.now()
        pair.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return redirect("revise:pairs")

    return render(
        request,
        "revise/pairs.html",
        {"pairs": LearningPair.objects.filter(status=LearningPair.Status.PENDING)},
    )
