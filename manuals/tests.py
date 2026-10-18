from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Manual


class ManualListTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="member",
            password="test-password",
        )
        self.manual = Manual.objects.create(title="部内案内")

    def test_manual_list_uses_archive_style_items(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse("manuals:manual_list"))

        self.assertContains(response, 'class="manual-list__item"')
        self.assertContains(response, self.manual.title)
        self.assertContains(response, "詳細を見る")
