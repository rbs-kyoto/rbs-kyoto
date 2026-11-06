from datetime import date, datetime

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Event
from .recurrence import expand


def jst(*args):
    return timezone.make_aware(datetime(*args))


class RecurrenceTests(TestCase):
    def test_single_event_in_range(self):
        event = Event.objects.create(title="撮影", start=jst(2026, 11, 5, 15, 0))
        occ = expand([event], date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual([o.first_day for o in occ], [date(2026, 11, 5)])

    def test_weekly_until(self):
        event = Event.objects.create(
            title="定例会",
            start=jst(2026, 11, 4, 16, 0),
            recurrence=Event.Recurrence.WEEKLY,
            recurrence_until=date(2026, 11, 20),
        )
        occ = expand([event], date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(
            [o.first_day for o in occ],
            [date(2026, 11, 4), date(2026, 11, 11), date(2026, 11, 18)],
        )

    def test_weekly_started_before_range(self):
        event = Event.objects.create(
            title="定例会",
            start=jst(2026, 9, 2, 16, 0),
            recurrence=Event.Recurrence.WEEKLY,
        )
        occ = expand([event], date(2026, 11, 1), date(2026, 11, 7))
        self.assertEqual([o.first_day for o in occ], [date(2026, 11, 4)])

    def test_monthly_skips_missing_day(self):
        event = Event.objects.create(
            title="月例",
            start=jst(2026, 1, 31, 10, 0),
            recurrence=Event.Recurrence.MONTHLY,
        )
        occ = expand([event], date(2026, 1, 1), date(2026, 4, 30))
        self.assertEqual(
            [o.first_day for o in occ],
            [date(2026, 1, 31), date(2026, 3, 31)],
        )

    def test_multi_day_event_overlaps_range(self):
        event = Event.objects.create(
            title="合宿",
            start=jst(2026, 10, 30, 0, 0),
            end=jst(2026, 11, 2, 0, 0),
            all_day=True,
        )
        occ = expand([event], date(2026, 11, 1), date(2026, 11, 30))
        self.assertEqual(len(occ), 1)
        self.assertEqual(occ[0].last_day, date(2026, 11, 2))


class ScheduleViewTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user("member", password="pw")
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.event = Event.objects.create(title="大会", start=jst(2026, 11, 10, 9, 0))

    def test_login_required(self):
        response = self.client.get(reverse("schedule:calendar"))
        self.assertEqual(response.status_code, 302)

    def test_member_sees_calendar(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("schedule:calendar"), {"year": 2026, "month": 11})
        self.assertContains(response, "大会")
        self.assertNotContains(response, "予定を追加")

    def test_invalid_month_falls_back(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("schedule:calendar"), {"year": 2026, "month": 13})
        self.assertEqual(response.status_code, 200)

    def test_member_cannot_create(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("schedule:event_create"))
        self.assertEqual(response.status_code, 302)

    def test_member_cannot_delete(self):
        self.client.force_login(self.member)
        self.client.post(reverse("schedule:event_delete", args=[self.event.pk]))
        self.assertTrue(Event.objects.filter(pk=self.event.pk).exists())

    def test_staff_creates_event(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("schedule:event_create"),
            {
                "title": "定例会",
                "start": "2026-11-04T16:00",
                "end": "2026-11-04T17:30",
                "recurrence": "weekly",
                "recurrence_until": "2026-12-31",
            },
        )
        event = Event.objects.get(title="定例会")
        self.assertRedirects(response, reverse("schedule:event_detail", args=[event.pk]))
        self.assertEqual(event.created_by, self.staff)

    def test_end_before_start_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("schedule:event_create"),
            {
                "title": "NG",
                "start": "2026-11-04T16:00",
                "end": "2026-11-04T15:00",
                "recurrence": "none",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Event.objects.filter(title="NG").exists())

    def test_staff_edit_and_delete(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("schedule:event_edit", args=[self.event.pk]),
            {"title": "大会(改)", "start": "2026-11-10T10:00", "recurrence": "none"},
        )
        self.event.refresh_from_db()
        self.assertEqual(self.event.title, "大会(改)")

        response = self.client.post(reverse("schedule:event_delete", args=[self.event.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Event.objects.filter(pk=self.event.pk).exists())


class WeekViewTests(TestCase):
    def setUp(self):
        self.member = get_user_model().objects.create_user("member", password="pw")
        Event.objects.create(
            title="定例会",
            start=jst(2026, 11, 4, 16, 0),
            recurrence=Event.Recurrence.WEEKLY,
        )
        Event.objects.create(
            title="合宿",
            start=jst(2026, 11, 6, 0, 0),
            end=jst(2026, 11, 8, 0, 0),
            all_day=True,
        )

    def get_week(self, **params):
        self.client.force_login(self.member)
        return self.client.get(reverse("schedule:week"), params)

    def test_login_required(self):
        response = self.client.get(reverse("schedule:week"))
        self.assertEqual(response.status_code, 302)

    def test_week_starts_on_monday_and_lists_seven_days(self):
        response = self.get_week(date="2026-11-05")  # 木曜
        days = response.context["days"]
        self.assertEqual(len(days), 7)
        self.assertEqual(days[0]["date"], date(2026, 11, 2))
        self.assertEqual(days[6]["date"], date(2026, 11, 8))

    def test_recurring_and_multi_day_events_are_placed(self):
        response = self.get_week(date="2026-11-05")
        by_date = {d["date"]: [o.event.title for o in d["occurrences"]] for d in response.context["days"]}
        self.assertEqual(by_date[date(2026, 11, 4)], ["定例会"])
        for day in (6, 7, 8):
            self.assertEqual(by_date[date(2026, 11, day)], ["合宿"])
        self.assertEqual(by_date[date(2026, 11, 3)], [])

    def test_recurring_event_appears_in_later_week(self):
        response = self.get_week(date="2026-11-18")
        titles = [o.event.title for d in response.context["days"] for o in d["occurrences"]]
        self.assertEqual(titles, ["定例会"])

    def test_prev_and_next_week(self):
        response = self.get_week(date="2026-11-05")
        self.assertEqual(response.context["prev_date"], date(2026, 10, 26))
        self.assertEqual(response.context["next_date"], date(2026, 11, 9))

    def test_invalid_date_falls_back_to_today(self):
        response = self.get_week(date="not-a-date")
        self.assertEqual(response.status_code, 200)
        today = timezone.localdate()
        self.assertIn(today, [d["date"] for d in response.context["days"]])

    def test_month_view_links_to_week(self):
        self.client.force_login(self.member)
        response = self.client.get(reverse("schedule:calendar"), {"year": 2026, "month": 11})
        self.assertContains(response, reverse("schedule:week") + "?date=2026-11-04")
