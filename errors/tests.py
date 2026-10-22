from pathlib import Path

from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, TestCase
from django.urls import reverse

from . import views


class ErrorPreviewTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="test-password",
        )
        self.preview_urls = {
            400: reverse("preview_400"),
            403: reverse("preview_403"),
            404: reverse("preview_404"),
            500: reverse("preview_500"),
            513: reverse("preview_513"),
            418: reverse("preview_418"),
        }
        self.preview_icons = {
            400: "sentiment_dissatisfied",
            403: "gpp_bad",
            404: "search_off",
            500: "error",
            513: "error",
            418: "emoji_food_beverage",
        }
    def test_preview_pages_are_available_to_superusers(self):
        self.client.force_login(self.superuser)

        for code, url in self.preview_urls.items():
            with self.subTest(code=code):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, str(code))
                self.assertContains(response, self.preview_icons[code])
                self.assertContains(response, "main/css/error.css")

    def test_preview_pages_require_login(self):
        for code, url in self.preview_urls.items():
            with self.subTest(code=code):
                response = self.client.get(url)

                self.assertRedirects(
                    response,
                    f"{reverse('accounts:login')}?next={url}",
                )

    def test_preview_pages_are_forbidden_to_non_superusers(self):
        staff_user = get_user_model().objects.create_user(
            username="staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff_user)

        for code, url in self.preview_urls.items():
            with self.subTest(code=code):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 403)
                self.assertContains(response, "403", status_code=403)

    def test_mypage_only_shows_error_preview_to_superusers(self):
        response = self.client.get(reverse("accounts:mypage"))
        self.assertRedirects(
            response,
            f"{reverse('accounts:login')}?next={reverse('accounts:mypage')}",
        )

        staff_user = get_user_model().objects.create_user(
            username="staff",
            password="test-password",
            is_staff=True,
        )
        self.client.force_login(staff_user)
        response = self.client.get(reverse("accounts:mypage"))
        self.assertNotContains(response, "エラーページをプレビュー")

        self.client.force_login(self.superuser)
        response = self.client.get(reverse("accounts:mypage"))
        self.assertContains(response, "エラーページをプレビュー")
        for code, url in self.preview_urls.items():
            self.assertContains(response, f'href="{url}"')
            if code == 418:
                self.assertContains(response, self.preview_icons[code])
            else:
                self.assertContains(response, f"main/img/icons/{self.preview_icons[code]}.svg")

    def test_django_error_handlers_render_matching_pages_and_status_codes(self):
        request = RequestFactory().get("/")
        handlers = (
            (400, views.bad_request, Exception("bad request")),
            (403, views.permission_denied, PermissionDenied()),
            (404, views.page_not_found, Exception("not found")),
            (500, views.server_error, None),
        )
        for code, handler, exception in handlers:
            with self.subTest(code=code):
                if exception is None:
                    response = handler(request)
                else:
                    response = handler(request, exception)

                self.assertEqual(response.status_code, code)
                self.assertIn(str(code), response.content.decode())

    def test_hidden_teapot_page_returns_http_418_with_error_page_style(self):
        response = self.client.get(reverse("teapot"))

        self.assertEqual(response.status_code, 418)
        self.assertContains(response, "418", status_code=418)
        self.assertContains(response, "I'm a teapot", status_code=418)
        self.assertContains(response, "main/css/error.css", status_code=418)

        homepage = self.client.get(reverse("main:index"))
        self.assertNotContains(homepage, reverse("teapot"))

    def test_service_worker_is_available_for_site_scope(self):
        response = self.client.get(reverse("service_worker"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Service-Worker-Allowed"], "/")
        self.assertEqual(response["Cache-Control"], "no-cache")
        worker_source = b"".join(response.streaming_content).decode()
        self.assertIn('const CACHE_NAME = "rbs-offline-v2"', worker_source)
        self.assertIn("caches.open(CACHE_NAME)", worker_source)

        homepage = self.client.get(reverse("main:index"))
        self.assertContains(homepage, "main/js/service_worker.js")

    def test_offline_page_is_self_contained_and_contains_inline_svg(self):
        offline_page = (
            Path(settings.BASE_DIR) / "static" / "offline.html"
        ).read_text(encoding="utf-8")

        self.assertIn("<svg", offline_page)
        self.assertIn("<path", offline_page)
        self.assertIn('viewBox="0 0 48 48"', offline_page)
        self.assertIn("stroke-linecap", offline_page)
        self.assertNotIn("fonts.googleapis.com", offline_page)
        self.assertNotIn("<link", offline_page)
        self.assertNotIn("<img", offline_page)
        self.assertIn("再読み込み", offline_page)
