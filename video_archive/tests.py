from datetime import date

from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Video, VideoGroup
from .utils import format_fiscal_year


class VideoListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member",
            password="test-password",
        )
        self.active_video = Video.objects.create(
            title="公開動画",
            url="https://www.youtube.com/watch?v=abcdefghijk",
            event_date=date(2026, 5, 1),
            production_date=date(2026, 5, 10),
        )
        self.inactive_video = Video.objects.create(
            title="非公開動画",
            url="https://youtu.be/lmnopqrstuv",
            is_active=False,
            event_date=date(2024, 10, 1),
        )
        self.previous_fiscal_year_video = Video.objects.create(
            title="前年度動画",
            url="https://youtu.be/zyxwvutsrqp",
            event_date=date(2026, 3, 31),
        )
        self.url = reverse("video_archive:video_list")

    def test_homepage_links_to_video_archive(self):
        response = self.client.get(reverse("main:index"))

        self.assertContains(response, "Video Archive")
        self.assertContains(response, self.url)

    def test_login_is_required(self):
        response = self.client.get(self.url)

        self.assertRedirects(response, f"{reverse('accounts:login')}?next={self.url}")

    def test_members_only_see_years_with_active_videos(self):
        self.client.force_login(self.user)

        response = self.client.get(self.url)

        self.assertContains(response, reverse("video_archive:video_year_list", args=[2026]))
        self.assertContains(response, reverse("video_archive:video_year_list", args=[2025]))
        self.assertNotContains(response, reverse("video_archive:video_year_list", args=[2024]))

    def test_year_list_uses_april_to_march_fiscal_year(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_year_list", args=[2026])
        )

        self.assertContains(response, self.active_video.title)
        self.assertContains(response, "令和８年度")
        self.assertNotContains(response, self.inactive_video.title)
        self.assertNotContains(response, self.previous_fiscal_year_video.title)

    def test_year_list_includes_march_in_previous_fiscal_year(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_year_list", args=[2025])
        )

        self.assertContains(response, self.previous_fiscal_year_video.title)

    def test_staff_can_see_inactive_videos(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_year_list", args=[2024])
        )

        self.assertContains(response, self.inactive_video.title)

    def test_videos_are_grouped_in_the_list(self):
        group = VideoGroup.objects.create(name="大会")
        self.active_video.group = group
        self.active_video.save()
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_year_list", args=[2026])
        )

        self.assertContains(response, "大会")
        self.assertContains(response, "開催日 2026.05.01")
        self.assertContains(response, "制作日 2026.05.10")

    def test_detail_embeds_youtube_video(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_detail", args=[self.active_video.pk]),
            {"year": 2026},
        )

        self.assertContains(
            response,
            'data-embed-url="https://www.youtube-nocookie.com/embed/abcdefghijk"',
        )
        self.assertContains(response, "<iframe")
        self.assertContains(response, "<dialog")
        self.assertContains(response, "音声なし")
        self.assertContains(response, "音声あり")
        self.assertContains(
            response,
            reverse("video_archive:video_year_list", args=[2026]),
        )

    def test_detail_without_fiscal_year_returns_to_year_selection(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_detail", args=[self.active_video.pk])
        )

        self.assertContains(response, reverse("video_archive:video_list"))

    def test_detail_hides_inactive_video_from_members(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("video_archive:video_detail", args=[self.inactive_video.pk])
        )

        self.assertEqual(response.status_code, 404)

    def test_non_youtube_urls_are_rejected(self):
        video = Video(title="不正URL", url="https://example.com/video")

        with self.assertRaises(ValidationError):
            video.full_clean()

    def test_fiscal_year_uses_japanese_era(self):
        self.assertEqual(format_fiscal_year(2026), "令和８年度")
        self.assertEqual(format_fiscal_year(2019), "令和元年度")
        self.assertEqual(format_fiscal_year(1989), "平成元年度")
