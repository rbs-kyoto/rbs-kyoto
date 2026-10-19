from datetime import date

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
    def test_google_login_on_www_redirects_to_apex_and_preserves_query(self):
        response = self.client.get(
            "/accounts/google/login/?next=%2Fvideos%2F",
            HTTP_HOST=f"www.{settings.CANONICAL_HOST}",
            HTTP_X_FORWARDED_PROTO="https",
        )

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"https://{settings.CANONICAL_HOST}/accounts/google/login/?next=%2Fvideos%2F",
        )


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
