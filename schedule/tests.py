from datetime import date, datetime
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from equipment.models import Category, Equipment, Loan, LoanLine, ReturnRecord
from equipment.testing import make_usage
from roll.models import RosterEntry

from accounts.models import WebPushSubscription

from .models import (
    Assignment,
    Attendance,
    AttendanceReminderDelivery,
    Event,
    EventEquipment,
    UsageLink,
)
from .recurrence import expand


def jst(*args):
    return timezone.make_aware(datetime(*args))


def formset_data(rows=(), initial=0, equipment=()):
    """割当部員・使用機材フォームセットの POST データ。

    rows は (member_pk, role)、equipment は (equipment_pk, quantity) の並び。
    """
    data = {
        "assignments-TOTAL_FORMS": str(len(rows)),
        "assignments-INITIAL_FORMS": str(initial),
        "assignments-MIN_NUM_FORMS": "0",
        "assignments-MAX_NUM_FORMS": "1000",
        "equipment_items-TOTAL_FORMS": str(len(equipment)),
        "equipment_items-INITIAL_FORMS": "0",
        "equipment_items-MIN_NUM_FORMS": "0",
        "equipment_items-MAX_NUM_FORMS": "1000",
    }
    for i, (member, role) in enumerate(rows):
        data[f"assignments-{i}-member"] = str(member)
        data[f"assignments-{i}-role"] = role
    for i, (item, quantity) in enumerate(equipment):
        data[f"equipment_items-{i}-equipment"] = str(item)
        data[f"equipment_items-{i}-quantity"] = str(quantity)
    return data


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
                **formset_data(),
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
                **formset_data(),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Event.objects.filter(title="NG").exists())

    def test_staff_edit_and_delete(self):
        self.client.force_login(self.staff)
        self.client.post(
            reverse("schedule:event_edit", args=[self.event.pk]),
            {
                "title": "大会(改)",
                "start": "2026-11-10T10:00",
                "recurrence": "none",
                **formset_data(initial=0),
            },
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


class AssignmentTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.alice_user = User.objects.create_user("alice", password="pw")
        self.bob_user = User.objects.create_user("bob", password="pw")
        self.outsider_user = User.objects.create_user("outsider", password="pw")
        self.alice = RosterEntry.objects.create(name="Alice", is_member=True, account=self.alice_user)
        self.bob = RosterEntry.objects.create(name="Bob", is_member=True, account=self.bob_user)
        self.nonmember = RosterEntry.objects.create(name="Teacher", is_member=False)
        RosterEntry.objects.create(name="Outsider", is_member=True, account=self.outsider_user)

    def create_event(self, **extra):
        self.client.force_login(self.staff)
        data = {
            "title": "撮影",
            "start": "2026-11-10T13:00",
            "recurrence": "none",
            "ask_attendance": "on",
            **formset_data([(self.alice.pk, "カメラ"), (self.bob.pk, "音声")]),
            **extra,
        }
        response = self.client.post(reverse("schedule:event_create"), data)
        return Event.objects.get(title=data["title"]), response

    def test_staff_assigns_members_with_roles(self):
        event, response = self.create_event()
        self.assertRedirects(response, reverse("schedule:event_detail", args=[event.pk]))
        roles = {a.member.name: a.role for a in event.assignments.all()}
        self.assertEqual(roles, {"Alice": "カメラ", "Bob": "音声"})
        self.assertTrue(event.ask_attendance)

    def test_non_member_cannot_be_assigned(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("schedule:event_create"),
            {
                "title": "NG",
                "start": "2026-11-10T13:00",
                "recurrence": "none",
                **formset_data([(self.nonmember.pk, "")]),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Event.objects.filter(title="NG").exists())

    def test_same_member_twice_is_rejected(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("schedule:event_create"),
            {
                "title": "重複",
                "start": "2026-11-10T13:00",
                "recurrence": "none",
                **formset_data([(self.alice.pk, "A"), (self.alice.pk, "B")]),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Event.objects.filter(title="重複").exists())

    def test_detail_lists_assignees_to_logged_in_users(self):
        event, _ = self.create_event()
        self.client.force_login(self.outsider_user)
        response = self.client.get(reverse("schedule:event_detail", args=[event.pk]))
        self.assertContains(response, "Alice")
        self.assertContains(response, "カメラ")
        self.assertNotContains(response, 'name="status"')  # 割当外は回答フォームなし


class AttendanceTests(AssignmentTests):
    def respond(self, user, event, day="2026-11-10", status="attend", comment=""):
        self.client.force_login(user)
        return self.client.post(
            reverse("schedule:event_respond", args=[event.pk]),
            {"date": day, "status": status, "comment": comment},
        )

    def test_assigned_member_can_respond_and_change(self):
        event, _ = self.create_event()
        response = self.respond(self.alice_user, event, comment="少し遅れます")
        self.assertEqual(response.status_code, 302)
        record = Attendance.objects.get()
        self.assertEqual((record.status, record.comment), ("attend", "少し遅れます"))

        self.respond(self.alice_user, event, status="absent")
        self.assertEqual(Attendance.objects.count(), 1)
        self.assertEqual(Attendance.objects.get().status, "absent")

    def test_form_shown_only_to_assigned_member(self):
        event, _ = self.create_event()
        self.client.force_login(self.alice_user)
        url = reverse("schedule:event_detail", args=[event.pk])
        self.assertContains(self.client.get(url), 'name="status"')
        self.client.force_login(self.outsider_user)
        self.assertNotContains(self.client.get(url), 'name="status"')

    def test_unassigned_user_and_staff_cannot_respond(self):
        event, _ = self.create_event()
        self.assertEqual(self.respond(self.outsider_user, event).status_code, 403)
        self.assertEqual(self.respond(self.staff, event).status_code, 403)
        self.assertEqual(Attendance.objects.count(), 0)

    def test_cannot_respond_when_attendance_is_off(self):
        event, _ = self.create_event(title="出欠なし", ask_attendance="")
        self.assertEqual(self.respond(self.alice_user, event).status_code, 404)

    def test_invalid_status_is_not_saved(self):
        event, _ = self.create_event()
        self.respond(self.alice_user, event, status="maybe")
        self.assertEqual(Attendance.objects.count(), 0)

    def test_date_must_be_a_real_occurrence(self):
        event, _ = self.create_event()
        self.assertEqual(self.respond(self.alice_user, event, day="2026-11-11").status_code, 404)

    def test_recurring_event_is_answered_per_date(self):
        event, _ = self.create_event(
            title="定例会", start="2026-11-04T16:00", recurrence="weekly"
        )
        self.respond(self.alice_user, event, day="2026-11-04", status="attend")
        self.respond(self.alice_user, event, day="2026-11-11", status="absent")
        self.assertEqual(
            {(a.date.isoformat(), a.status) for a in Attendance.objects.all()},
            {("2026-11-04", "attend"), ("2026-11-11", "absent")},
        )
        self.client.force_login(self.bob_user)
        url = reverse("schedule:event_detail", args=[event.pk])
        response = self.client.get(url, {"date": "2026-11-11"})
        self.assertEqual(response.context["summary"]["欠席"], 1)
        self.assertEqual(response.context["summary"]["未回答"], 1)
        self.assertEqual(self.client.get(url, {"date": "2026-11-04"}).context["summary"]["出席"], 1)

    def test_deleting_event_removes_assignments_and_responses(self):
        event, _ = self.create_event()
        self.respond(self.alice_user, event)
        self.client.force_login(self.staff)
        self.client.post(reverse("schedule:event_delete", args=[event.pk]))
        self.assertEqual(Assignment.objects.count(), 0)
        self.assertEqual(Attendance.objects.count(), 0)


class EquipmentLinkTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.member = User.objects.create_user("member", password="pw")
        category = Category.objects.get(code="A")
        self.mic = Equipment.objects.create(
            category=category, inventory_number="A-SCH-1", name="ワイヤレスマイク",
            quantity=2, unit="本",
        )
        self.camera = Equipment.objects.create(
            category=category, inventory_number="A-SCH-2", name="カメラ",
            quantity=1, unit="台",
        )

    def make_event(self, title, start, quantity=1, equipment=None, end=None, **extra):
        event = Event.objects.create(title=title, start=start, end=end, **extra)
        EventEquipment.objects.create(
            event=event, equipment=equipment or self.mic, quantity=quantity
        )
        return event

    def status_of(self, event, day):
        self.client.force_login(self.member)
        response = self.client.get(
            reverse("schedule:event_detail", args=[event.pk]), {"date": day}
        )
        return response, [row["status"] for row in response.context["equipment_rows"]]

    def test_staff_attaches_equipment_to_event(self):
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("schedule:event_create"),
            {
                "title": "撮影",
                "start": "2026-11-10T13:00",
                "end": "2026-11-10T16:00",
                "recurrence": "none",
                **formset_data(equipment=[(self.mic.pk, 2), (self.camera.pk, 1)]),
            },
        )
        event = Event.objects.get(title="撮影")
        self.assertRedirects(response, reverse("schedule:event_detail", args=[event.pk]))
        self.assertEqual(
            {(i.equipment.name, i.quantity) for i in event.equipment_items.all()},
            {("ワイヤレスマイク", 2), ("カメラ", 1)},
        )

    def test_member_cannot_attach_equipment(self):
        self.client.force_login(self.member)
        response = self.client.post(reverse("schedule:event_create"), {"title": "x"})
        self.assertEqual(response.status_code, 302)  # staff限定なのでログインへ
        self.assertFalse(Event.objects.exists())

    def test_planned_equipment_without_conflict_is_ok(self):
        event = self.make_event("撮影", jst(2026, 11, 10, 13), end=jst(2026, 11, 10, 16))
        response, statuses = self.status_of(event, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["ok"])
        self.assertContains(response, "予約OK")

    def test_quantity_over_stock_is_short(self):
        event = self.make_event("多すぎ", jst(2026, 11, 10, 13), quantity=3)
        _, statuses = self.status_of(event, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["short"])

    def test_overlapping_events_conflict_but_can_be_saved(self):
        self.make_event("A", jst(2026, 11, 10, 13), quantity=2, end=jst(2026, 11, 10, 16))
        b = self.make_event("B", jst(2026, 11, 10, 15), quantity=1, end=jst(2026, 11, 10, 17))
        response, statuses = self.status_of(b, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["conflict"])
        self.assertContains(response, "予定「A」が 2本 使用予定です")

    def test_same_equipment_at_different_times_is_not_a_conflict(self):
        self.make_event("A", jst(2026, 11, 10, 9), quantity=2, end=jst(2026, 11, 10, 11))
        b = self.make_event("B", jst(2026, 11, 10, 15), quantity=2, end=jst(2026, 11, 10, 17))
        _, statuses = self.status_of(b, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["ok"])

    def test_broken_equipment_is_unavailable(self):
        self.mic.condition = Equipment.Condition.BROKEN
        self.mic.save()
        event = self.make_event("撮影", jst(2026, 11, 10, 13))
        _, statuses = self.status_of(event, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["unavailable"])

    def test_outstanding_lending_outside_events_counts_as_conflict(self):
        make_usage(
            equipment=self.camera, usage_type="lending", destination="他部活", quantity=1,
            started_at=jst(2026, 11, 9, 10), due_at=jst(2026, 11, 12, 10),
        )
        event = self.make_event("撮影", jst(2026, 11, 10, 13), equipment=self.camera)
        _, statuses = self.status_of(event, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["conflict"])
        self.assertIn("他部活", statuses[0].reasons[0])

    def test_lending_button_prefills_equipment_form_for_staff_only(self):
        event = self.make_event(
            "撮影", jst(2026, 11, 10, 13), quantity=2, end=jst(2026, 11, 10, 16)
        )
        url = reverse("schedule:event_detail", args=[event.pk]) + "?date=2026-11-10"
        self.client.force_login(self.member)
        self.assertNotContains(self.client.get(url), "貸出登録")
        self.client.force_login(self.staff)
        response = self.client.get(url)
        self.assertContains(response, "貸出登録")
        link = response.context["equipment_rows"][0]["lending_url"]
        self.assertIn(f"equipment={self.mic.pk}", link)
        self.assertIn("quantity=2", link)
        self.assertIn("started_at=2026-11-10T13%3A00", link)
        self.assertIn("due_at=2026-11-10T16%3A00", link)

        # The link puts the item in the lending cart and opens the form with the
        # event's details (quantity, times, purpose, schedule link) carried over.
        form_page = self.client.get(link, follow=True)
        form = form_page.context["form"]
        row = form_page.context["rows"][0]
        self.assertEqual(row["equipment"].pk, self.mic.pk)
        self.assertEqual(row["quantity"], 2)
        self.assertEqual(form.initial["purpose"], "撮影")
        self.assertEqual(form.initial["started_at"], "2026-11-10T13:00")
        self.assertEqual(form.initial["due_at"], "2026-11-10T16:00")
        self.assertContains(form_page, 'name="schedule_item"')
        self.assertContains(form_page, 'name="schedule_date"')

    def test_cart_actions_keep_the_schedule_link_and_typed_details(self):
        event = self.make_event(
            "撮影", jst(2026, 11, 10, 13), quantity=2, end=jst(2026, 11, 10, 16)
        )
        item = event.equipment_items.get()
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("equipment:cart_add"),
            {
                "equipment": [item.equipment_id],
                f"quantity_{item.equipment_id}": "2",
                "schedule_item": item.pk,
                "schedule_date": "2026-11-10",
                "purpose": "撮影",
                "started_at": "2026-11-10T13:00",
            },
            follow=True,
        )
        self.assertContains(response, 'name="schedule_item"')
        self.assertEqual(response.context["form"].initial["purpose"], "撮影")

    def register_lending(self, user, event, day="2026-11-10", quantity=2):
        item = event.equipment_items.get()
        self.client.force_login(user)
        return self.client.post(
            reverse("equipment:lending_register"),
            {
                "equipment": item.equipment_id,
                "usage_type": "lending",
                "destination_selection": "other",
                "other_destination": "放送部",
                "quantity": quantity,
                "started_at": "2026-11-10T13:00",
                "due_at": "2026-11-10T16:00",
                "schedule_item": item.pk,
                "schedule_date": day,
            },
        )

    def test_lending_registration_links_and_shows_lent_then_returned(self):
        event = self.make_event(
            "撮影", jst(2026, 11, 10, 13), quantity=2, end=jst(2026, 11, 10, 16)
        )
        response = self.register_lending(self.staff, event)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        link = UsageLink.objects.get()
        self.assertEqual(link.date.isoformat(), "2026-11-10")

        _, statuses = self.status_of(event, "2026-11-10")
        self.assertEqual((statuses[0].code, statuses[0].label), ("lent", "貸出中"))

        ReturnRecord.objects.create(line=link.usage, quantity=2)
        _, statuses = self.status_of(event, "2026-11-10")
        self.assertEqual([s.code for s in statuses], ["returned"])

    def test_non_staff_lending_is_not_linked(self):
        event = self.make_event("撮影", jst(2026, 11, 10, 13), quantity=2)
        self.register_lending(self.member, event)
        self.assertEqual(Loan.objects.count(), 1)
        self.assertEqual(UsageLink.objects.count(), 0)

    def test_link_for_non_occurrence_date_is_ignored(self):
        event = self.make_event("撮影", jst(2026, 11, 10, 13), quantity=2)
        self.register_lending(self.staff, event, day="2026-11-20")
        self.assertEqual(UsageLink.objects.count(), 0)

    def test_recurring_event_lending_is_per_date(self):
        event = self.make_event(
            "定例会", jst(2026, 11, 4, 16), quantity=1,
            recurrence=Event.Recurrence.WEEKLY, end=jst(2026, 11, 4, 17),
        )
        self.register_lending(self.staff, event, day="2026-11-04", quantity=1)
        _, first = self.status_of(event, "2026-11-04")
        _, second = self.status_of(event, "2026-11-11")
        self.assertEqual([first[0].code, second[0].code], ["lent", "ok"])

    def test_upcoming_problems_are_listed_for_recurring_events(self):
        self.make_event("単発", jst(2026, 11, 11, 16), quantity=2, end=jst(2026, 11, 11, 17))
        event = self.make_event(
            "定例会", jst(2026, 11, 4, 16), quantity=1,
            recurrence=Event.Recurrence.WEEKLY, end=jst(2026, 11, 4, 17),
        )
        response, _ = self.status_of(event, "2026-11-04")
        problems = [(d.isoformat(), s.code) for d, s in response.context["equipment_problems"]]
        self.assertEqual(problems, [("2026-11-11", "conflict")])
        self.assertContains(response, "今後の回に、機材の競合や不足があります")

    def test_deleting_event_keeps_usage_record(self):
        event = self.make_event("撮影", jst(2026, 11, 10, 13), quantity=2)
        self.register_lending(self.staff, event)
        self.client.force_login(self.staff)
        self.client.post(reverse("schedule:event_delete", args=[event.pk]))
        self.assertEqual(UsageLink.objects.count(), 0)
        self.assertEqual(Loan.objects.count(), 1)


SEND = "schedule.management.commands.send_attendance_reminders.send_web_push"
NOW = timezone.make_aware(datetime(2026, 11, 10, 9, 0))


class AttendanceReminderTests(TestCase):
    """2026-11-10 09:00 に毎朝のコマンドを実行した想定。"""

    def setUp(self):
        User = get_user_model()
        self.alice_user = User.objects.create_user("alice", password="pw")
        self.bob_user = User.objects.create_user("bob", password="pw")
        self.alice = RosterEntry.objects.create(name="Alice", is_member=True, account=self.alice_user)
        self.bob = RosterEntry.objects.create(name="Bob", is_member=True, account=self.bob_user)
        self.carol = RosterEntry.objects.create(name="Carol", is_member=True)  # アカウント未連携
        self.alice_sub = self.subscribe(self.alice_user, "https://fcm.googleapis.com/a", enabled=True)
        self.bob_sub = self.subscribe(self.bob_user, "https://fcm.googleapis.com/b", enabled=False)

    def subscribe(self, user, endpoint, enabled):
        return WebPushSubscription.objects.create(
            user=user, endpoint=endpoint, p256dh="k", auth="a",
            schedule_reminders_enabled=enabled,
        )

    def make_event(self, start, members=None, ask=True, **extra):
        event = Event.objects.create(title=extra.pop("title", "撮影"), start=start, ask_attendance=ask, **extra)
        for member in members or (self.alice, self.bob, self.carol):
            Assignment.objects.create(event=event, member=member)
        return event

    def run_command(self, *args, send=None):
        out = StringIO()
        with mock.patch("django.utils.timezone.now", return_value=NOW), mock.patch(
            SEND, side_effect=send or (lambda sub, payload: True)
        ) as sender:
            call_command("send_attendance_reminders", *args, stdout=out, stderr=StringIO())
        return sender, out.getvalue()

    def test_sends_only_to_unanswered_members_who_enabled_the_reminder(self):
        event = self.make_event(jst(2026, 11, 13, 16))  # 3日前
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 1)  # alice のみ(bob は無効、carol は連携なし)
        subscription, payload = sender.call_args.args
        self.assertEqual(subscription, self.alice_sub)
        self.assertEqual(payload["title"], "出欠のお願い")
        self.assertIn("撮影", payload["body"])
        self.assertIn("11月13日(金) 16:00", payload["body"])
        self.assertIn("あと3日", payload["body"])
        self.assertEqual(payload["url"], f"/schedule/{event.pk}/?date=2026-11-13")

    def test_answered_members_are_skipped(self):
        event = self.make_event(jst(2026, 11, 13, 16))
        Attendance.objects.create(
            assignment=event.assignments.get(member=self.alice),
            date=date(2026, 11, 13),
            status="absent",
        )
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 0)

    def test_only_three_days_one_day_and_same_day(self):
        self.make_event(jst(2026, 11, 12, 16), title="2日後")
        self.make_event(jst(2026, 11, 14, 16), title="4日後")
        self.make_event(jst(2026, 11, 11, 16), title="前日")
        self.make_event(jst(2026, 11, 10, 15), title="当日")
        sender, _ = self.run_command()
        titles = sorted(call.args[1]["body"].split("」")[0] for call in sender.call_args_list)
        self.assertEqual(titles, ["「前日", "「当日"])
        bodies = " ".join(call.args[1]["body"] for call in sender.call_args_list)
        self.assertIn("本日", bodies)
        self.assertIn("あと1日", bodies)

    def test_events_that_already_ended_today_are_skipped(self):
        self.make_event(jst(2026, 11, 10, 7), end=jst(2026, 11, 10, 8), title="終了済み")
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 0)

    def test_all_day_event_today_is_still_reminded(self):
        self.make_event(jst(2026, 11, 10, 0), all_day=True, title="終日")
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 1)
        self.assertNotIn(":", sender.call_args.args[1]["body"].split("の出欠")[0].split("」")[1])

    def test_events_without_attendance_are_ignored(self):
        self.make_event(jst(2026, 11, 13, 16), ask=False)
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 0)

    def test_not_sent_twice_for_the_same_day_but_sent_for_the_next_stage(self):
        self.make_event(jst(2026, 11, 13, 16))
        self.run_command()
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 0)  # 同じ3日前の分は二重送信しない
        self.assertEqual(AttendanceReminderDelivery.objects.count(), 1)

        later = timezone.make_aware(datetime(2026, 11, 12, 9, 0))  # 翌日=前日の段階
        with mock.patch("django.utils.timezone.now", return_value=later), mock.patch(
            SEND, return_value=True
        ) as sender:
            call_command("send_attendance_reminders", stdout=StringIO(), stderr=StringIO())
        self.assertEqual(sender.call_count, 1)  # 11/12 から見て 11/13 は「前日」の段階なので送る
        self.assertIn("あと1日", sender.call_args.args[1]["body"])
        self.assertEqual(AttendanceReminderDelivery.objects.count(), 2)

    def test_recurring_event_is_reminded_per_occurrence(self):
        self.make_event(
            jst(2026, 11, 3, 16), recurrence=Event.Recurrence.WEEKLY, title="定例会"
        )  # 11/10(当日) と 11/17 だが、11/10 の16:00 はまだ先
        sender, _ = self.run_command()
        self.assertEqual(sender.call_count, 1)
        self.assertEqual(sender.call_args.args[1]["url"].split("date=")[1], "2026-11-10")

    def test_dead_subscription_does_not_record_a_delivery(self):
        self.make_event(jst(2026, 11, 13, 16))
        self.run_command(send=lambda sub, payload: False)
        self.assertEqual(AttendanceReminderDelivery.objects.count(), 0)

    def test_failures_are_reported_but_other_sends_continue(self):
        from pywebpush import WebPushException

        self.subscribe(self.bob_user, "https://fcm.googleapis.com/b2", enabled=True)
        self.make_event(jst(2026, 11, 13, 16))

        def flaky(subscription, payload):
            if subscription.endpoint.endswith("/b2"):
                raise WebPushException("boom")
            return True

        with self.assertRaises(CommandError):
            self.run_command(send=flaky)
        self.assertEqual(AttendanceReminderDelivery.objects.count(), 1)  # alice 分は記録済み

    def test_configuration_error_stops_with_a_clear_message(self):
        from accounts.push import PushConfigurationError

        self.make_event(jst(2026, 11, 13, 16))

        def broken(subscription, payload):
            raise PushConfigurationError("not configured")

        with self.assertRaisesMessage(CommandError, "Web Push の設定を確認してください"):
            self.run_command(send=broken)

    def test_dry_run_sends_nothing_and_records_nothing(self):
        self.make_event(jst(2026, 11, 13, 16))
        sender, output = self.run_command("--dry-run")
        self.assertEqual(sender.call_count, 0)
        self.assertEqual(AttendanceReminderDelivery.objects.count(), 0)
        self.assertIn("[dry-run] Alice", output)

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="pub",
        WEBPUSH_VAPID_PRIVATE_KEY="priv",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    def test_mypage_shows_the_new_notification_setting(self):
        self.client.force_login(self.alice_user)
        response = self.client.get(reverse("accounts:mypage"))
        self.assertContains(response, "出欠リマインド通知")
        self.assertContains(response, 'data-notification-type="schedule"')

    def test_preference_is_exposed_and_toggleable_independently(self):
        self.client.force_login(self.bob_user)
        url = reverse("accounts:push_subscription_preferences")
        response = self.client.get(url, {"endpoint": self.bob_sub.endpoint})
        self.assertFalse(response.json()["schedule_reminders_enabled"])
        equipment_before = response.json()["equipment_reminders_enabled"]

        with mock.patch("accounts.views.send_web_push", return_value=True):
            response = self.client.post(
                url,
                data='{"endpoint": "%s", "type": "schedule", "enabled": true}' % self.bob_sub.endpoint,
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200)
        self.bob_sub.refresh_from_db()
        self.assertTrue(self.bob_sub.schedule_reminders_enabled)
        self.assertEqual(self.bob_sub.equipment_reminders_enabled, equipment_before)


class PlaceIntegrationTests(TestCase):
    def setUp(self):
        from places.models import Place

        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.member = User.objects.create_user("member", password="pw")
        self.school = Place.objects.create(name="校舎", is_venue=True)
        self.studio = Place.objects.create(name="放送室", parent=self.school, is_venue=True)
        self.gym = Place.objects.create(name="体育館", is_venue=True)
        self.shelf = Place.objects.create(name="棚A", is_venue=False)

    def make_event(self, title, start, end=None, place=None, **extra):
        return Event.objects.create(title=title, start=start, end=end, place=place, **extra)

    def conflicts(self, event, day):
        self.client.force_login(self.member)
        response = self.client.get(reverse("schedule:event_detail", args=[event.pk]), {"date": day})
        return response, response.context["place_warnings"]

    def post_event(self, **extra):
        self.client.force_login(self.staff)
        return self.client.post(
            reverse("schedule:event_create"),
            {"title": "収録", "start": "2026-11-10T13:00", "recurrence": "none", **formset_data(), **extra},
        )

    def test_schedule_registers_itself_as_a_place_provider(self):
        from places.registry import PROVIDERS

        self.assertIn("schedule", PROVIDERS)

    def test_form_offers_only_active_venues(self):
        self.client.force_login(self.staff)
        queryset = self.client.get(reverse("schedule:event_create")).context["form"].fields["place"].queryset
        self.assertEqual({p.name for p in queryset}, {"校舎", "放送室", "体育館"})

    def test_staff_sets_a_place(self):
        response = self.post_event(place=self.studio.pk)
        event = Event.objects.get(title="収録")
        self.assertRedirects(response, reverse("schedule:event_detail", args=[event.pk]))
        self.assertEqual(event.place, self.studio)

    def test_place_is_optional(self):
        self.post_event()
        self.assertIsNone(Event.objects.get(title="収録").place)

    def test_non_venue_place_cannot_be_chosen(self):
        response = self.post_event(place=self.shelf.pk)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Event.objects.filter(title="収録").exists())

    def test_existing_place_stays_selectable_after_it_stops_being_a_venue(self):
        event = self.make_event("既存", jst(2026, 11, 10, 13), place=self.gym)
        self.gym.is_venue = False
        self.gym.save()
        self.client.force_login(self.staff)
        form = self.client.get(reverse("schedule:event_edit", args=[event.pk])).context["form"]
        self.assertIn(self.gym, form.fields["place"].queryset)

    def test_detail_and_week_show_the_place_path(self):
        event = self.make_event("収録", jst(2026, 11, 10, 13), place=self.studio)
        self.client.force_login(self.member)
        self.assertContains(self.client.get(reverse("schedule:event_detail", args=[event.pk])), "校舎 / 放送室")
        self.assertContains(self.client.get(reverse("schedule:week"), {"date": "2026-11-10"}), "校舎 / 放送室")

    def test_overlapping_events_in_the_same_place_warn_but_both_exist(self):
        a = self.make_event("A", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15), place=self.studio)
        b = self.make_event("B", jst(2026, 11, 10, 14), jst(2026, 11, 10, 16), place=self.studio)
        response, warnings = self.conflicts(b, "2026-11-10")
        self.assertEqual([w.title for w in warnings], ["A"])
        self.assertContains(response, "同じ場所")
        self.assertContains(response, "A</a>")
        self.assertEqual([w.title for w in self.conflicts(a, "2026-11-10")[1]], ["B"])

    def test_no_conflict_when_times_or_places_differ(self):
        base = self.make_event("A", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15), place=self.studio)
        self.make_event("別の時間", jst(2026, 11, 10, 16), jst(2026, 11, 10, 17), place=self.studio)
        self.make_event("別の場所", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15), place=self.gym)
        self.make_event("場所なし", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15))
        self.assertEqual(self.conflicts(base, "2026-11-10")[1], [])

    def test_parent_and_child_places_conflict(self):
        room = self.make_event("放送室", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15), place=self.studio)
        building = self.make_event("校舎全体", jst(2026, 11, 10, 14), jst(2026, 11, 10, 16), place=self.school)
        self.assertEqual([w.title for w in self.conflicts(room, "2026-11-10")[1]], ["校舎全体"])
        self.assertEqual([w.title for w in self.conflicts(building, "2026-11-10")[1]], ["放送室"])

    def test_all_day_event_conflicts_with_timed_event_the_same_day(self):
        timed = self.make_event("収録", jst(2026, 11, 10, 13), jst(2026, 11, 10, 14), place=self.gym)
        self.make_event("大会", jst(2026, 11, 10, 0), all_day=True, place=self.gym)
        self.assertEqual([w.title for w in self.conflicts(timed, "2026-11-10")[1]], ["大会"])

    def test_a_recurring_event_blocks_every_week(self):
        single = self.make_event("単発", jst(2026, 11, 18, 16), jst(2026, 11, 18, 17), place=self.studio)
        self.make_event(
            "定例会", jst(2026, 11, 4, 16), jst(2026, 11, 4, 17), place=self.studio,
            recurrence=Event.Recurrence.WEEKLY,
        )
        self.assertEqual([w.title for w in self.conflicts(single, "2026-11-18")[1]], ["定例会"])
        self.assertEqual(self.conflicts(single, "2026-11-18")[1][0].start.date(), date(2026, 11, 18))

    def test_upcoming_conflicts_of_a_recurring_event_are_listed(self):
        recurring = self.make_event(
            "定例会", jst(2026, 11, 4, 16), jst(2026, 11, 4, 17), place=self.studio,
            recurrence=Event.Recurrence.WEEKLY,
        )
        self.make_event("単発", jst(2026, 11, 18, 16), jst(2026, 11, 18, 17), place=self.studio)
        self.client.force_login(self.member)
        response = self.client.get(reverse("schedule:event_detail", args=[recurring.pk]), {"date": "2026-11-04"})
        self.assertEqual(response.context["place_warnings"], [])
        upcoming = response.context["place_upcoming"]
        self.assertEqual([(d.isoformat(), [u.title for u in uses]) for d, uses in upcoming], [("2026-11-18", ["単発"])])
        self.assertContains(response, "今後の回にも")

    def test_event_without_a_place_never_warns(self):
        event = self.make_event("場所なし", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15))
        self.make_event("同時刻", jst(2026, 11, 10, 13), jst(2026, 11, 10, 15))
        self.assertEqual(self.conflicts(event, "2026-11-10")[1], [])

    def test_form_page_wires_up_the_live_conflict_check(self):
        event = self.make_event("収録", jst(2026, 11, 10, 13), place=self.studio)
        self.client.force_login(self.staff)
        response = self.client.get(reverse("schedule:event_edit", args=[event.pk]))
        self.assertContains(response, 'data-places-api="/api/places/"')
        self.assertContains(response, f'data-event-id="{event.pk}"')
        self.assertContains(response, 'id="place-live-warning"')
