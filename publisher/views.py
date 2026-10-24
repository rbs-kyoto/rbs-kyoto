import re

from django.contrib import admin, messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import Http404, HttpResponse, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_POST

from . import builder
from .models import Deployment
from .pages import (
    EMAIL_PLACEHOLDER,
    MEMBERS,
    MESSAGE_PLACEHOLDER,
    PUBLIC,
    QUERY_KEYS,
    VARIANTS,
    iter_pages,
    page_file_path,
)

# サイト内リンクをプレビューの中で辿れるように付け替える（静的ファイルとメディアは除く）
_SITE_LINK_RE = re.compile(r'\b(?P<attr>href|action)="/(?!/|static/|media/)')


@staff_member_required
def dashboard(request):
    active_version = builder.active_version()
    return render(
        request,
        "publisher/dashboard.html",
        {
            **admin.site.each_context(request),
            "title": "デプロイを管理",
            "deployments": Deployment.objects.select_related("created_by"),
            "active_version": active_version,
            "has_unpublished_changes": builder.has_unpublished_changes(),
        },
    )


@staff_member_required
@require_POST
def deploy(request):
    description = request.POST.get("description", "").strip()[:200]
    deployment = builder.deploy(description=description, user=request.user)
    if deployment.status == Deployment.Status.READY:
        messages.success(request, f"バージョン {deployment.version} を公開しました。")
    else:
        messages.error(
            request,
            f"バージョン {deployment.version} の書き出しに失敗しました。公開中のバージョンは変わっていません。",
        )
    return redirect("publisher:dashboard")


@staff_member_required
@require_POST
def activate(request, version):
    deployment = get_object_or_404(Deployment, version=version, status=Deployment.Status.READY)
    try:
        builder.activate(deployment.version)
    except FileNotFoundError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, f"バージョン {deployment.version} を公開しました。")
    return redirect("publisher:dashboard")


def _find_page(variant, url_path, query):
    pages = {}
    for page in iter_pages(variant):
        pages.setdefault(page.file_path, page)
    return pages.get(page_file_path(url_path, query)) or pages.get(page_file_path(url_path))


@staff_member_required
def preview(request, variant, path=""):
    """GASのテストデプロイに相当。DBの最新状態を、書き出す前にその場で描画して見せる。"""
    if variant not in VARIANTS:
        raise Http404

    url_path = f"/{path}"
    query = {key: request.GET[key] for key in QUERY_KEYS if key in request.GET}
    page = _find_page(variant, url_path, query)
    if page is None:
        if variant == PUBLIC and _find_page(MEMBERS, url_path, query) is not None:
            notice = "このページは部員限定です。公開サイトではログイン画面に移動します。"
        else:
            notice = "このページは書き出されません（公開サイトでは404になります）。"
        return HttpResponseNotFound(
            _preview_banner(variant, url_path) + f'<p style="padding:2rem">{escape(notice)}</p>'
        )

    html = builder.render_page(page, variant)
    html = html.replace(EMAIL_PLACEHOLDER, escape(request.user.email or "（プレビュー）"))
    html = html.replace(MESSAGE_PLACEHOLDER, "")
    html = _SITE_LINK_RE.sub(
        lambda match: f'{match.group("attr")}="{reverse("publisher:preview", args=[variant])}',
        html,
    )
    html = html.replace("<body>", "<body>" + _preview_banner(variant, url_path), 1)

    response = HttpResponse(html)
    response["Cache-Control"] = "no-store"
    return response


def _preview_banner(variant, url_path):
    labels = {PUBLIC: "公開用", MEMBERS: "部員用"}
    other = MEMBERS if variant == PUBLIC else PUBLIC
    other_url = reverse("publisher:preview", args=[other]) + url_path.lstrip("/")
    return (
        '<div style="position:sticky;top:0;z-index:9999;display:flex;gap:1rem;flex-wrap:wrap;'
        "align-items:center;padding:.5rem 1rem;background:#1f2937;color:#fff;"
        'font:14px/1.5 sans-serif">'
        f"<strong>プレビュー（{labels[variant]}）</strong>"
        "<span>まだ公開されていません</span>"
        f'<a style="color:#93c5fd" href="{escape(other_url)}">{labels[other]}で見る</a>'
        f'<a style="color:#93c5fd" href="{reverse("publisher:dashboard")}">デプロイ管理へ戻る</a>'
        "</div>"
    )


def _error_response(code):
    return HttpResponse(builder.render_error(code), status=code)


def bad_request(request, exception):
    return _error_response(400)


def permission_denied(request, exception):
    return _error_response(403)


def page_not_found(request, exception):
    return _error_response(404)


def server_error(request):
    return _error_response(500)
