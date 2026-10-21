from datetime import date
import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import News


class NewsListTests(TestCase):
    def test_news_list_uses_archive_style_rows(self):
        news = News.objects.create(
            title="お知らせ",
            date=date(2026, 10, 18),
            caption="記事本文",
        )

        response = self.client.get(reverse("main:news_all"))

        self.assertContains(response, 'class="news-all__item"')
        self.assertContains(response, news.title)
        self.assertContains(response, "詳細を見る")

    def test_page_has_theme_switch_and_dark_logo_variant(self):
        response = self.client.get(reverse("main:index"))

        self.assertContains(response, 'data-theme-mode="light"')
        self.assertContains(response, 'data-theme-mode="dark"')
        self.assertContains(response, "rbs-dark.svg")
        self.assertContains(response, "login-dark.svg")


class CanonicalHostTests(TestCase):
    def test_apex_google_login_redirects_to_www_and_preserves_query(self):
        response = self.client.get(
            "/accounts/google/login/?next=%2Fvideos%2F",
            HTTP_HOST=settings.CANONICAL_DOMAIN,
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"https://{settings.CANONICAL_HOST}/accounts/google/login/?next=%2Fvideos%2F",
        )

    def test_canonical_www_host_is_not_redirected(self):
        response = self.client.get("/", HTTP_HOST=settings.CANONICAL_HOST)

        self.assertEqual(response.status_code, 200)


class ProgressiveWebAppTests(TestCase):
    def test_base_page_links_manifest_and_apple_home_screen_icon(self):
        response = self.client.get(reverse("main:index"))

        self.assertContains(
            response,
            '<link rel="manifest" href="/static/main/manifest.webmanifest">',
        )
        self.assertContains(response, 'name="apple-mobile-web-app-capable" content="yes"')
        self.assertContains(
            response,
            '<link rel="apple-touch-icon" href="/static/main/img/pwa-icon-180.png">',
        )

    def test_manifest_declares_standalone_app_and_install_icons(self):
        manifest_path = Path(settings.BASE_DIR) / "static/main/manifest.webmanifest"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        icon_directory = Path(settings.BASE_DIR) / "static/main/img"

        self.assertEqual(manifest["start_url"], "/")
        self.assertEqual(manifest["scope"], "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(
            {icon["src"].rsplit("/", 1)[-1] for icon in manifest["icons"]},
            {path.name for path in icon_directory.glob("pwa-icon*")},
        )
        for icon in manifest["icons"]:
            icon_path = Path(settings.BASE_DIR) / "static" / icon["src"].removeprefix("/static/")
            self.assertTrue(icon_path.is_file(), icon_path)

    def test_news_without_an_image_uses_the_pwa_icon(self):
        news = News.objects.create(
            title="画像なしのお知らせ",
            date=date(2026, 10, 18),
            caption="本文",
        )

        homepage = self.client.get(reverse("main:index"))
        news_list = self.client.get(reverse("main:news_all"))

        self.assertContains(homepage, 'src="/static/main/img/pwa-icon.svg"')
        self.assertContains(news_list, 'src="/static/main/img/pwa-icon.svg"')
        self.assertContains(news_list, reverse("main:news_detail", args=[news.pk]))


class ErrorPageTests(TestCase):
    def test_not_found_uses_custom_404_page(self):
        with self.settings(DEBUG=False):
            response = self.client.get("/page-that-does-not-exist/")

        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "お探しのページが見つかりませんでした。", status_code=404)
        self.assertContains(response, "404", status_code=404)
        self.assertContains(response, reverse("main:index"), status_code=404)
        self.assertContains(response, reverse("main:news_all"), status_code=404)


class NewsCreateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="editor",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(self.user)
        self.url = reverse("main:news_create")

    def test_valid_post_creates_news_and_redirects_to_detail(self):
        response = self.client.post(
            self.url,
            {
                "title": "新しい記事",
                "date": "2026-10-18",
                "caption": "<p>本文</p>",
                "is_active": "on",
            },
        )

        news = News.objects.get(title="新しい記事")
        self.assertRedirects(
            response,
            reverse("main:news_detail", args=[news.pk]),
        )

    def test_invalid_post_shows_form_errors(self):
        response = self.client.post(self.url, {})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "入力内容を確認してください。")
        self.assertContains(response, "タイトルを入力してください。")
        self.assertContains(response, "日付を入力してください。")
        self.assertContains(response, "本文を入力してください。")
        self.assertEqual(News.objects.count(), 0)

    def test_create_form_defaults_to_publication_enabled(self):
        response = self.client.get(self.url)

        self.assertTrue(response.context["form"]["is_active"].value())
