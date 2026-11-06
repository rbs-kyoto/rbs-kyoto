from datetime import date, timedelta
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import NotificationHistory, WebPushSubscription
from .admin import PickupAdminForm
from .models import FooterSocialLink, HeaderLogoSchedule, News, Pickup, SitePage


class PickupLinkTests(TestCase):
    def _form(self, url):
        return PickupAdminForm(
            data={
                "title": "サイト紹介",
                "url": url,
                "order": "0",
                "is_active": "on",
            },
            files={
                "image": SimpleUploadedFile(
                    "pickup.png",
                    b"pickup image",
                    content_type="image/png",
                ),
            },
        )

    def test_home_relative_pickup_url_is_resolved_from_site_root(self):
        form = self._form("about/")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["url"], "/about/")

    def test_absolute_pickup_url_is_preserved(self):
        form = self._form("https://example.com/events/")

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["url"], "https://example.com/events/")

    def test_protocol_relative_pickup_url_is_rejected(self):
        form = self._form("//example.com/events/")

        self.assertFalse(form.is_valid())
        self.assertIn("url", form.errors)

    def test_home_pickup_renders_internal_path(self):
        pickup = Pickup.objects.create(
            title="サイト紹介",
            image=SimpleUploadedFile(
                "pickup.png",
                b"pickup image",
                content_type="image/png",
            ),
            url="/about/",
        )

        response = self.client.get(reverse("main:index"))

        self.assertContains(response, f'href="{pickup.url}"')


class NewsListTests(TestCase):
    def test_homepage_lists_roll_app_for_staff_only(self):
        response = self.client.get(reverse("main:index"))

        self.assertNotContains(response, reverse("roll:list"))

        staff = get_user_model().objects.create_user(
            username="roll-app-staff",
            is_staff=True,
        )
        self.client.force_login(staff)
        response = self.client.get(reverse("main:index"))

        self.assertContains(response, reverse("roll:list"))
        self.assertContains(response, "校内名簿・部員・役職の管理")

    def test_page_title_gets_the_site_name_from_shared_base_template(self):
        response = self.client.get(reverse("main:index"))

        self.assertContains(
            response,
            "<title>洛南高等学校放送部｜rbs京都</title>",
            html=True,
        )

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


class AboutPageTests(TestCase):
    def test_about_page_explains_the_site_and_links_to_sections(self):
        response = self.client.get(reverse("main:about"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "洛南高等学校・洛南高等学校附属中学校の放送部")
        self.assertContains(response, "rbs.svg")
        self.assertContains(response, reverse("main:news_all"))
        self.assertContains(response, reverse("manuals:manual_list"))
        self.assertContains(response, reverse("video_archive:video_list"))
        self.assertContains(response, 'data-logo-stage')
        self.assertContains(response, 'aria-label="rbsロゴ。マウスの動きに合わせて傾きます"')
        self.assertNotContains(response, 'type="range"')
        self.assertContains(response, 'aria-label="紹介ページ"')
        self.assertContains(response, 'data-about-screen', count=3)
        self.assertContains(response, 'data-screen-target', count=3)
        self.assertLess(
            response.content.index(b"data-logo-stage"),
            response.content.index(b"about-intro-title"),
        )


class FooterAndSitePageTests(TestCase):
    def test_footer_lists_information_pages_and_icon_only_social_links(self):
        x_icon_files = {
            "light_icon": SimpleUploadedFile("x-light.svg", b"<svg></svg>"),
            "dark_icon": SimpleUploadedFile("x-dark.svg", b"<svg></svg>"),
            "hover_icon": SimpleUploadedFile("x-hover.svg", b"<svg></svg>"),
        }
        x_link = FooterSocialLink.objects.create(
            label="X公式アカウント",
            url="https://x.com/example",
            **x_icon_files,
        )
        for field_name in ("light_icon", "dark_icon", "hover_icon"):
            self.addCleanup(
                getattr(x_link, field_name).delete,
                save=False,
            )
        instagram_icon_files = {
            "light_icon": SimpleUploadedFile("instagram-light.svg", b"<svg></svg>"),
            "dark_icon": SimpleUploadedFile("instagram-dark.svg", b"<svg></svg>"),
            "hover_icon": SimpleUploadedFile("instagram-hover.svg", b"<svg></svg>"),
        }
        instagram_link = FooterSocialLink.objects.create(
            label="Instagram公式アカウント",
            url="https://www.instagram.com/example/",
            order=1,
            **instagram_icon_files,
        )
        for field_name in ("light_icon", "dark_icon", "hover_icon"):
            self.addCleanup(
                getattr(instagram_link, field_name).delete,
                save=False,
            )
        incomplete_link = FooterSocialLink.objects.create(
            label="追加SNS",
            url="https://example.com/social",
            order=2,
        )

        response = self.client.get(reverse("main:index"))

        for slug, title in SitePage.PAGE_CHOICES:
            self.assertContains(response, reverse("main:site_page", args=[slug]))
            self.assertContains(response, title)
        self.assertContains(response, x_link.url)
        self.assertContains(response, instagram_link.url)
        self.assertContains(response, 'aria-label="X公式アカウント"')
        self.assertContains(response, 'aria-label="Instagram公式アカウント"')
        self.assertContains(response, 'aria-label="公式SNS"')
        self.assertContains(response, 'class="footer__social-icon-image footer__social-icon-image--light"')
        self.assertContains(response, 'class="footer__social-icon-image footer__social-icon-image--dark"')
        self.assertContains(
            response,
            'class="footer__social-icon-image footer__social-icon-image--hover"',
            count=2,
        )
        self.assertContains(response, x_link.light_icon.url)
        self.assertContains(response, x_link.dark_icon.url)
        self.assertContains(response, x_link.hover_icon.url)
        self.assertContains(response, incomplete_link.url)
        self.assertContains(response, 'class="footer__social-icon-fallback">追</span>')

    def test_site_page_renders_database_content_after_sanitizing(self):
        page = SitePage.objects.get(slug="privacy")
        page.content = "<p>登録した本文</p><script>alert(1)</script>"
        page.save()

        response = self.client.get(reverse("main:site_page", args=[page.slug]))

        self.assertNotIn("<script>", page.content)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, page.title)
        self.assertContains(response, "<p>登録した本文</p>", html=True)
        self.assertNotContains(response, "alert(1)")


class HeaderLogoScheduleTests(TestCase):
    def test_scheduled_logo_is_used_for_the_header_during_its_period(self):
        today = timezone.localdate()
        logo = HeaderLogoSchedule.objects.create(
            starts_on=today - timedelta(days=1),
            ends_on=today + timedelta(days=1),
            image=SimpleUploadedFile("campaign.gif", b"gif data", content_type="image/gif"),
        )
        self.addCleanup(logo.image.delete, save=False)

        response = self.client.get(reverse("main:index"))

        self.assertContains(response, f'src="{logo.image.url}"')
        self.assertContains(response, f'data-theme-light-src="{logo.image.url}"')
        self.assertContains(response, f'data-theme-dark-src="{logo.image.url}"')
        self.assertNotContains(response, 'data-theme-dark-src="/static/main/img/rbs-dark.svg"')

    def test_expired_scheduled_logo_is_not_used(self):
        today = timezone.localdate()
        logo = HeaderLogoSchedule.objects.create(
            starts_on=today - timedelta(days=3),
            ends_on=today - timedelta(days=1),
            image=SimpleUploadedFile("expired.svg", b"<svg></svg>"),
        )
        self.addCleanup(logo.image.delete, save=False)

        response = self.client.get(reverse("main:index"))

        self.assertContains(response, 'data-theme-light-src="/static/main/img/rbs.svg"')
        self.assertNotContains(response, logo.image.url)

    def test_schedule_rejects_reversed_and_overlapping_periods(self):
        today = timezone.localdate()
        schedule = HeaderLogoSchedule(
            starts_on=today,
            ends_on=today - timedelta(days=1),
            image="header-logos/logo.png",
        )
        with self.assertRaises(ValidationError):
            schedule.clean()

        existing = HeaderLogoSchedule.objects.create(
            starts_on=today,
            ends_on=today + timedelta(days=2),
            image=SimpleUploadedFile("scheduled.svg", b"<svg></svg>"),
        )
        self.addCleanup(existing.image.delete, save=False)
        overlap = HeaderLogoSchedule(
            starts_on=today + timedelta(days=1),
            ends_on=today + timedelta(days=3),
            image="header-logos/overlap.png",
        )
        with self.assertRaises(ValidationError):
            overlap.clean()

    def test_schedule_accepts_animated_image_extensions(self):
        schedule = HeaderLogoSchedule(
            starts_on=timezone.localdate(),
            ends_on=timezone.localdate(),
            image=SimpleUploadedFile(
                "animated.webp",
                b"webp data",
                content_type="image/webp",
            ),
        )

        schedule.full_clean()


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
            '<link rel="manifest" href="/manifest.webmanifest">',
        )
        self.assertContains(response, 'name="apple-mobile-web-app-capable" content="yes"')
        icon_suffix = "-dev" if settings.DEBUG else ""
        self.assertContains(
            response,
            f'<link rel="apple-touch-icon" href="/static/main/img/pwa-icon{icon_suffix}-180.png">',
        )

    def test_manifest_and_service_worker_select_icons_for_each_environment(self):
        for debug, suffix in ((True, "-dev"), (False, "")):
            with self.subTest(debug=debug), override_settings(DEBUG=debug):
                manifest_response = self.client.get(reverse("web_manifest"))
                manifest = json.loads(manifest_response.content)

                self.assertEqual(manifest["start_url"], "/")
                self.assertEqual(manifest["scope"], "/")
                self.assertEqual(manifest["display"], "standalone")
                self.assertTrue(
                    all(
                        f"pwa-icon{suffix}" in icon["src"]
                        for icon in manifest["icons"]
                    )
                )
                for icon in manifest["icons"]:
                    icon_path = (
                        Path(settings.BASE_DIR)
                        / "static"
                        / icon["src"].removeprefix("/static/")
                    )
                    self.assertTrue(icon_path.is_file(), icon_path)

                worker_response = self.client.get(reverse("service_worker"))
                self.assertContains(
                    worker_response,
                    f"/static/main/img/pwa-icon{suffix}-192.png",
                )
                self.assertNotContains(worker_response, "__PWA_ICON_SUFFIX__")

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


class NewsPushNotificationTests(TestCase):
    def setUp(self):
        user = get_user_model().objects.create_user(username="news-subscriber")
        self.subscription = WebPushSubscription.objects.create(
            user=user,
            endpoint="https://fcm.googleapis.com/fcm/send/news-subscriber",
            p256dh="public-key",
            auth="auth-secret",
            news_notifications_enabled=True,
        )

    @patch("main.signals.send_web_push")
    def test_published_public_news_notifies_news_subscribers(self, send_push):
        with self.captureOnCommitCallbacks(execute=True):
            news = News.objects.create(
                title="公演のお知らせ",
                date=date(2026, 11, 5),
                caption="<p>本文</p>",
            )

        send_push.assert_called_once_with(
            self.subscription,
            {
                "title": "新しいお知らせが投稿されました",
                "body": "公演のお知らせ",
                "url": reverse("main:news_detail", args=[news.pk]),
            },
        )

    @patch("main.signals.send_web_push", return_value=True)
    def test_delivered_news_notification_is_saved_once_per_user(self, send_push):
        WebPushSubscription.objects.create(
            user=self.subscription.user,
            endpoint="https://fcm.googleapis.com/fcm/send/news-second-device",
            p256dh="public-key",
            auth="auth-secret",
            news_notifications_enabled=True,
        )

        with self.captureOnCommitCallbacks(execute=True):
            news = News.objects.create(
                title="履歴に残るお知らせ",
                date=date(2026, 11, 5),
                caption="<p>本文</p>",
            )

        self.assertEqual(send_push.call_count, 2)
        history = NotificationHistory.objects.get()
        self.assertEqual(history.user, self.subscription.user)
        self.assertEqual(history.kind, NotificationHistory.Kind.NEWS)
        self.assertEqual(history.body, "履歴に残るお知らせ")
        self.assertEqual(history.url, reverse("main:news_detail", args=[news.pk]))

    @patch("main.signals.send_web_push", return_value=False)
    def test_undelivered_news_notification_is_not_saved(self, send_push):
        with self.captureOnCommitCallbacks(execute=True):
            News.objects.create(
                title="届かなかったお知らせ",
                date=date(2026, 11, 5),
                caption="<p>本文</p>",
            )

        self.assertFalse(NotificationHistory.objects.exists())

    @patch("main.signals.send_web_push")
    def test_draft_and_internal_news_do_not_notify_subscribers(self, send_push):
        with self.captureOnCommitCallbacks(execute=True):
            News.objects.create(
                title="下書き",
                date=date(2026, 11, 5),
                caption="<p>本文</p>",
                is_active=False,
            )
            News.objects.create(
                title="限定公開",
                date=date(2026, 11, 5),
                caption="<p>本文</p>",
                is_internal=True,
            )

        send_push.assert_not_called()

    @patch("main.signals.send_web_push")
    def test_publishing_a_draft_notifies_once(self, send_push):
        news = News.objects.create(
            title="公開した記事",
            date=date(2026, 11, 5),
            caption="<p>本文</p>",
            is_active=False,
        )

        with self.captureOnCommitCallbacks(execute=True):
            news.is_active = True
            news.save()

        send_push.assert_called_once()
