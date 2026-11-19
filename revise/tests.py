from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.testing import make_member
from accounts.models import NotificationHistory

from .models import ProofreadRole, RevisePost


class ReviseBoardTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user(
            username="revise-member",
            password="Revise-pass-123",
        )
        make_member(self.member)
        self.reviewer = get_user_model().objects.create_user(
            username="revise-reviewer",
            password="Reviewer-pass-123",
        )
        make_member(self.reviewer)
        ProofreadRole.objects.create(user=self.reviewer)

    def test_post_creates_notification_for_reviewers(self):
        self.client.force_login(self.member)

        response = self.client.post(
            reverse("revise:new"),
            {
                "title": "文化祭のお知らせ",
                "body": "文化祭を開催します。",
                "instruction": "45秒に収めてください。",
                "target_seconds": "45",
            },
        )

        post = RevisePost.objects.get(title="文化祭のお知らせ")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            NotificationHistory.objects.filter(
                user=self.reviewer,
                kind="revise",
                url=f"/revise/{post.pk}/",
            ).exists()
        )

    def test_author_and_reviewer_can_toggle_close(self):
        post = RevisePost.objects.create(
            author=self.member,
            title="Close対象",
            body="原稿です。",
        )
        self.client.force_login(self.member)
        self.client.post(reverse("revise:toggle_close", args=[post.pk]))
        post.refresh_from_db()
        self.assertEqual(post.status, RevisePost.Status.CLOSED)

        self.client.force_login(self.reviewer)
        self.client.post(reverse("revise:toggle_close", args=[post.pk]))
        post.refresh_from_db()
        self.assertEqual(post.status, RevisePost.Status.OPEN)

    def test_superuser_without_role_cannot_proofread(self):
        post = RevisePost.objects.create(
            author=self.member,
            title="添削対象",
            body="原稿です。",
        )
        superuser = get_user_model().objects.create_superuser(
            username="revise-super",
            email="revise@example.com",
            password="Super-pass-123",
        )
        self.client.force_login(superuser)

        response = self.client.get(
            reverse("revise:proofread", args=[post.pk])
        )

        self.assertEqual(response.status_code, 403)

    def test_all_six_observations_are_required(self):
        post = RevisePost.objects.create(
            author=self.member,
            title="添削対象",
            body="原稿です。",
        )
        self.client.force_login(self.reviewer)

        response = self.client.post(
            reverse("revise:proofread", args=[post.pk]),
            {
                "revised_body": "添正文です。",
                "length_status": "指摘なし",
                "numbers_status": "指摘なし",
                "notation_status": "指摘なし",
                "grammar_status": "指摘なし",
                "readability_status": "指摘なし",
                "rewrite_status": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "6観点")

    def test_detail_shows_proofread_button_only_for_role_holder(self):
        post = RevisePost.objects.create(
            author=self.member,
            title="添削ボタン確認",
            body="原稿です。",
        )

        self.client.force_login(self.member)
        response = self.client.get(reverse("revise:detail", args=[post.pk]))
        self.assertNotContains(response, "添削する")

        self.client.force_login(self.reviewer)
        response = self.client.get(reverse("revise:detail", args=[post.pk]))
        self.assertContains(response, "添削する")
