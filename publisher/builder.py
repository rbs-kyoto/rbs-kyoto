"""静的サイトの書き出しと公開バージョンの切り替え。

SITE_BUILD_ROOT/
    releases/v1/, v2/, ...   各デプロイの書き出し結果（消さずに残す）
        public/              未ログイン向けページ
        members/             ログイン中の部員向けページ（gate/ 経由でのみ配信）
        errors/              404.html などのエラーページ
        static/  media/      Apache が直接配信する
    current -> releases/vN   公開中のバージョン（Djangoが落ちていても残る）
"""

import json
import os
import re
import shutil
import traceback
import uuid
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.template.loader import render_to_string
from django.urls import get_urlconf, set_urlconf
from django.utils import timezone

from config.staticstorage import plain_static_urls
from .models import ContentRevision, Deployment
from .pages import ERROR_CODES, PUBLIC_URLCONF, VARIANTS, iter_pages, viewer_for

CURRENT_LINK = "current"
_RELEASE_NAME_RE = re.compile(r"v(\d+)")


@contextmanager
def public_urlconf():
    previous = get_urlconf()
    set_urlconf(PUBLIC_URLCONF)
    try:
        yield
    finally:
        set_urlconf(previous)


def render_page(page, variant):
    with public_urlconf(), plain_static_urls():
        return render_to_string(page.template, {**page.context, "user": viewer_for(variant)})


def render_error(code):
    with public_urlconf(), plain_static_urls():
        return render_to_string(f"{code}.html")


def build_root():
    return Path(settings.SITE_BUILD_ROOT)


def release_dir(version):
    return build_root() / "releases" / f"v{version}"


def build_release(version):
    """書き出して releases/v<version>/ を作る。途中で失敗したら何も残さない。"""
    final = release_dir(version)
    if final.exists():
        raise FileExistsError(f"{final} はすでに存在します。")

    final.parent.mkdir(parents=True, exist_ok=True)
    work = final.parent / f".{final.name}-{uuid.uuid4().hex}"
    try:
        page_count = _write_release(work, version)
        work.rename(final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    return page_count


def _write_release(root, version):
    page_count = 0
    for variant in VARIANTS:
        for page in iter_pages(variant):
            _write_text(root / variant / page.file_path, render_page(page, variant))
            page_count += 1

    for code in ERROR_CODES:
        _write_text(root / "errors" / f"{code}.html", render_error(code))

    for static_dir in settings.STATICFILES_DIRS:
        shutil.copytree(static_dir, root / "static", dirs_exist_ok=True)
    shutil.copy2(settings.BASE_DIR / "static" / "service-worker.js", root / "public" / "service-worker.js")

    _link_tree(Path(settings.MEDIA_ROOT), root / "media")

    _write_text(
        root / "release.json",
        json.dumps({"version": version, "built_at": timezone.now().isoformat()}, ensure_ascii=False),
    )
    return page_count


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _link_tree(source, destination):
    # メディアはバージョンごとに複製すると重いので、できればハードリンクにする
    destination.mkdir(parents=True, exist_ok=True)
    if not source.is_dir():
        return
    for directory, _, files in os.walk(source):
        target_dir = destination / Path(directory).relative_to(source)
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in files:
            source_file = Path(directory) / name
            try:
                os.link(source_file, target_dir / name)
            except OSError:
                shutil.copy2(source_file, target_dir / name)


def activate(version):
    """current の向き先を差し替える。rename で入れ替えるので配信が途切れない。"""
    target = release_dir(version)
    if not target.is_dir():
        raise FileNotFoundError(f"バージョン {version} の書き出しが見つかりません。")

    temporary_link = build_root() / f".{CURRENT_LINK}-{uuid.uuid4().hex}"
    os.symlink(Path("releases") / target.name, temporary_link)
    os.replace(temporary_link, build_root() / CURRENT_LINK)


def active_version():
    try:
        target = os.readlink(build_root() / CURRENT_LINK)
    except OSError:
        return None
    match = _RELEASE_NAME_RE.fullmatch(Path(target).name)
    return int(match.group(1)) if match else None


def active_deployment():
    version = active_version()
    if version is None:
        return None
    return Deployment.objects.filter(version=version, status=Deployment.Status.READY).first()


def has_unpublished_changes():
    deployment = active_deployment()
    if deployment is None:
        return True
    changed_at = ContentRevision.last_changed_at()
    return changed_at is not None and changed_at > deployment.created_at


def deploy(description="", user=None):
    """新しいバージョンを書き出して公開する。失敗しても公開中のバージョンはそのまま。"""
    with transaction.atomic():
        latest = Deployment.objects.aggregate(latest=Max("version"))["latest"] or 0
        deployment = Deployment.objects.create(
            version=latest + 1,
            description=description,
            created_by=user if user is not None and user.is_authenticated else None,
        )

    try:
        deployment.page_count = build_release(deployment.version)
        activate(deployment.version)
    except Exception:
        deployment.status = Deployment.Status.FAILED
        deployment.error = traceback.format_exc()
    else:
        deployment.status = Deployment.Status.READY
    deployment.save(update_fields=["status", "page_count", "error"])
    return deployment
