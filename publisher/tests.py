import os
import shutil
import tempfile
from datetime import date
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from main.models import News
from maintenance.models import MaintenanceSetting
from manuals.models import Manual
from video_archive.models import Video

from . import builder
from .models import Deployment
from .pages import page_file_path


class BuildRootMixin:
    def setUp(self):
        super().setUp()
        self.build_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.build_root, ignore_errors=True)
        settings_override = override_settings(SITE_BUILD_ROOT=self.build_root)
        settings_override.enable()
        self.addCleanup(settings_override.disable)

    def read(self, version, variant, path, query=None):
        file = builder.release_dir(version) / variant / page_file_path(path, query)
        return file.read_text(encoding="utf-8")


class PageFilePathTests(TestCase):
    def test_query_variants_follow_the_gate_layout(self):
        self.assertEqual(page_file_path("/"), "index.html")
        self.assertEqual(page_file_path("/news/3/"), "news/3/index.html")
        self.assertEqual(page_file_path("/news/", {"page": "2"}), "news/_q/page-2/index.html")
        self.assertEqual(
            page_file_path("/videos/1/", {"year": "2026", "sort": "date"}),
            "videos/1/_q/sort-date/year-2026/index.html",
        )

    def test_unexpected_query_values_are_ignored(self):
        self.assertEqual(page_file_path("/news/", {"page": "../x"}), "news/index.html")
        self.assertEqual(page_file_path("/news/", {"other": "1"}), "news/index.html")


class BuildTests(BuildRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.public_news = News.objects.create(title="公開ニュース", date=date(2026, 10, 1), caption="<p>a</p>")
        self.internal_news = News.objects.create(
            title="部内ニュース", date=date(2026, 10, 2), caption="<p>b</p>", is_internal=True
        )
        self.draft_news = News.objects.create(
            title="下書きニュース", date=date(2026, 10, 3), caption="<p>c</p>", is_active=False
        )
        self.manual = Manual.objects.create(title="手順書", content="# a")
        self.video = Video.objects.create(
            title="文化祭動画", url="https://youtu.be/dQw4w9WgXcQ", event_date=date(2026, 5, 1)
        )

    def test_public_variant_excludes_member_and_draft_content(self):
        deployment = builder.deploy("初回")

        self.assertEqual(deployment.status, Deployment.Status.READY)
        index = self.read(1, "public", "/")
        self.assertIn("公開ニュース", index)
        self.assertNotIn("部内ニュース", index)
        self.assertNotIn("下書きニュース", index)
        self.assertIn('href="/accounts/login/"', index)
        release = builder.release_dir(1)
        self.assertFalse((release / "public" / page_file_path(f"/news/{self.internal_news.pk}/")).exists())
        self.assertFalse((release / "public" / "manuals").exists())
        self.assertFalse((release / "public" / "videos").exists())

    def test_members_variant_includes_member_content_without_edit_links(self):
        builder.deploy()

        index = self.read(1, "members", "/")
        self.assertIn("部内ニュース", index)
        self.assertNotIn("下書きニュース", index)
        self.assertIn('href="/accounts/mypage/"', index)
        self.assertNotIn("編集する", self.read(1, "members", f"/news/{self.public_news.pk}/"))
        self.assertIn("手順書", self.read(1, "members", "/manuals/", {"sort": "title"}))
        self.assertIn(
            'href="/videos/year/2026/"',
            self.read(1, "members", f"/videos/{self.video.pk}/", {"year": "2026"}),
        )

    def test_release_contains_error_pages_static_files_and_service_worker(self):
        builder.deploy()

        release = builder.release_dir(1)
        self.assertTrue((release / "errors" / "404.html").is_file())
        self.assertTrue((release / "static" / "main" / "css" / "base.css").is_file())
        self.assertTrue((release / "public" / "service-worker.js").is_file())

    def test_each_deploy_adds_a_version_and_older_ones_can_be_reactivated(self):
        builder.deploy("1つ目")
        builder.deploy("2つ目")

        self.assertEqual(builder.active_version(), 2)
        self.assertEqual(os.readlink(self.build_root / "current"), "releases/v2")

        builder.activate(1)

        self.assertEqual(builder.active_version(), 1)

    def test_failed_build_keeps_the_current_version_and_leaves_nothing_behind(self):
        builder.deploy()

        with mock.patch.object(builder, "render_error", side_effect=RuntimeError("boom")):
            deployment = builder.deploy("壊れる")

        self.assertEqual(deployment.status, Deployment.Status.FAILED)
        self.assertIn("boom", deployment.error)
        self.assertEqual(builder.active_version(), 1)
        self.assertEqual(sorted(path.name for path in (self.build_root / "releases").iterdir()), ["v1"])

    def test_content_changes_after_a_deploy_are_reported_as_unpublished(self):
        self.assertTrue(builder.has_unpublished_changes())
        builder.deploy()
        self.assertFalse(builder.has_unpublished_changes())

        self.public_news.title = "更新"
        self.public_news.save()

        self.assertTrue(builder.has_unpublished_changes())


@override_settings(ROOT_URLCONF="config.urls_admin", SITE_ROLE="admin")
class AdminHostTests(BuildRootMixin, TestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.staff = User.objects.create_user("staff", "staff@example.com", "pass", is_staff=True)
        self.member = User.objects.create_user("member", "member@example.com", "pass")
        self.internal_news = News.objects.create(
            title="部内ニュース", date=date(2026, 10, 2), caption="<p>b</p>", is_internal=True
        )

    def test_dashboard_is_staff_only(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("publisher:dashboard"))
        self.assertEqual(response.status_code, 302)

        self.client.force_login(self.staff)
        response = self.client.get(reverse("publisher:dashboard"))
        self.assertContains(response, "まだ公開されていません")
        self.assertContains(response, "未公開の変更あり")

    def test_deploy_and_activate_buttons(self):
        self.client.force_login(self.staff)

        self.client.post(reverse("publisher:deploy"), {"description": "1つ目"})
        self.client.post(reverse("publisher:deploy"), {"description": "2つ目"})
        response = self.client.post(reverse("publisher:activate", args=[1]), follow=True)

        self.assertEqual(builder.active_version(), 1)
        self.assertContains(response, "バージョン 1 を公開しました。")
        self.assertEqual(Deployment.objects.get(version=2).created_by, self.staff)

    def test_deploy_requires_post(self):
        self.client.force_login(self.staff)
        response = self.client.get(reverse("publisher:deploy"))
        self.assertEqual(response.status_code, 405)

    def test_preview_renders_latest_content_with_links_kept_inside_preview(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("publisher:preview", args=["members"]))

        self.assertContains(response, "部内ニュース")
        self.assertContains(response, 'href="/deploy/preview/members/news/"')
        self.assertContains(response, 'href="/static/main/css/base.css"')
        self.assertFalse((self.build_root / "releases").exists())

    def test_preview_explains_member_only_pages_in_public_variant(self):
        self.client.force_login(self.staff)

        response = self.client.get(
            reverse("publisher:preview", args=["public", f"news/{self.internal_news.pk}/"])
        )

        self.assertContains(response, "部員限定", status_code=404)

    def test_preview_is_staff_only(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("publisher:preview", args=["members"]))
        self.assertEqual(response.status_code, 302)

    def test_unknown_url_uses_site_error_page(self):
        response = self.client.get("/no-such-page/")
        self.assertContains(response, "Not Found", status_code=404)

    def test_maintenance_mode_does_not_block_admin_host(self):
        setting = MaintenanceSetting.get_solo()
        setting.mode = MaintenanceSetting.Mode.EMERGENCY
        setting.save()
        self.client.force_login(self.staff)

        response = self.client.get(reverse("publisher:dashboard"))

        self.assertEqual(response.status_code, 200)
