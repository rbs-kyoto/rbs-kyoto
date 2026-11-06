from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("equipment", "0010_equipmentreminderdelivery")]
AFTER = [("places", "0002_place_kinds"), ("equipment", "0011_move_location_to_places")]


class StorageLocationMigrationTests(TransactionTestCase):
    """equipment.StorageLocation → places.Place の移行で、データ(主キー・関連)が保たれること。"""

    serialized_rollback = True  # 初期データ(分類など)を、テスト後に元へ戻す

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        executor = MigrationExecutor(connection)
        return executor.loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(AFTER)  # 他のテストのため、最新の状態へ戻す
        super().tearDown()

    def test_existing_locations_and_equipment_survive_the_move(self):
        old = self.migrate(BEFORE)
        StorageLocation = old.get_model("equipment", "StorageLocation")
        Equipment = old.get_model("equipment", "Equipment")
        Category = old.get_model("equipment", "Category")

        room = StorageLocation.objects.create(name="部室", code="R1")
        shelf = StorageLocation.objects.create(name="棚A", parent=room, is_active=False)
        item = Equipment.objects.create(
            category=Category.objects.get(code="A"),
            inventory_number="A-MOVE-1",
            name="移行テスト用マイク",
            quantity=3,
            location=shelf,
        )
        room_pk, shelf_pk, item_pk = room.pk, shelf.pk, item.pk

        new = self.migrate(AFTER)
        Place = new.get_model("places", "Place")
        Equipment = new.get_model("equipment", "Equipment")

        moved_room = Place.objects.get(pk=room_pk)
        moved_shelf = Place.objects.get(pk=shelf_pk)
        self.assertEqual((moved_room.name, moved_room.code), ("部室", "R1"))
        self.assertEqual(moved_shelf.parent_id, room_pk)
        self.assertFalse(moved_shelf.is_active)
        # 既存の場所は「機材の保管場所」のまま。予定の場所には、管理者が選んだものだけを使う
        self.assertTrue(moved_room.is_storage)
        self.assertFalse(moved_room.is_venue)
        self.assertEqual(Equipment.objects.get(pk=item_pk).location_id, shelf_pk)


# ---------------------------------------------------------------- 共通関数・API・画面

from datetime import datetime, timedelta  # noqa: E402
from unittest import mock  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.test import TestCase  # noqa: E402
from django.urls import reverse  # noqa: E402
from django.utils import timezone  # noqa: E402

from schedule.models import Event  # noqa: E402

from . import registry, services  # noqa: E402
from .models import Place  # noqa: E402


def jst(*args):
    return timezone.make_aware(datetime(*args))


class PlaceTreeTests(TestCase):
    def setUp(self):
        self.school = Place.objects.create(name="校舎", is_venue=True)
        self.studio = Place.objects.create(name="放送室", parent=self.school, is_venue=True)
        self.booth = Place.objects.create(name="ブース", parent=self.studio, is_venue=True)
        self.gym = Place.objects.create(name="体育館", is_venue=True)

    def test_related_ids_include_ancestors_and_descendants(self):
        self.assertEqual(self.studio.related_ids(), {self.school.pk, self.studio.pk, self.booth.pk})
        self.assertEqual(self.gym.related_ids(), {self.gym.pk})

    def test_str_shows_the_path(self):
        self.assertEqual(str(self.booth), "校舎 / 放送室 / ブース")

    def test_venues_and_storage_places_are_separate(self):
        shelf = Place.objects.create(name="棚", is_storage=True, is_venue=False)
        inactive = Place.objects.create(name="閉鎖", is_venue=True, is_active=False)
        self.assertIn(self.gym, services.venues())
        self.assertNotIn(shelf, services.venues())
        self.assertNotIn(inactive, services.venues())
        self.assertIn(shelf, services.storage_places())


class FindConflictsTests(TestCase):
    def setUp(self):
        self.room = Place.objects.create(name="部室", is_venue=True)
        self.shelf = Place.objects.create(name="棚", parent=self.room, is_venue=True)
        self.other = Place.objects.create(name="体育館", is_venue=True)

    def use(self, place, key=1, start=None, end=None, source="fake"):
        start = start or jst(2026, 11, 10, 13)
        return registry.PlaceUse(
            source=source, key=key, title=f"利用{key}", start=start,
            end=end or start + timedelta(hours=1), place=place, url="/x/",
        )

    def provider(self, uses):
        seen = {}

        def provide(place_ids, start, end):
            seen["ids"] = set(place_ids)
            return [u for u in uses if u.place.pk in place_ids]

        provide.seen = seen
        return provide

    def test_providers_are_asked_with_related_places(self):
        provide = self.provider([self.use(self.room)])
        with mock.patch.dict(registry.PROVIDERS, {"fake": provide}, clear=True):
            conflicts = services.find_conflicts(self.shelf, jst(2026, 11, 10, 13), jst(2026, 11, 10, 14))
        self.assertEqual(provide.seen["ids"], {self.room.pk, self.shelf.pk})
        self.assertEqual([c.title for c in conflicts], ["利用1"])  # 親の部屋を押さえている

    def test_other_places_do_not_conflict_and_exclude_works(self):
        uses = [self.use(self.other, key=1), self.use(self.room, key=2)]
        with mock.patch.dict(registry.PROVIDERS, {"fake": self.provider(uses)}, clear=True):
            window = (jst(2026, 11, 10, 13), jst(2026, 11, 10, 14))
            self.assertEqual([c.key for c in services.find_conflicts(self.room, *window)], [2])
            self.assertEqual(services.find_conflicts(self.room, *window, exclude={"fake": 2}), [])
            self.assertFalse(services.is_available(self.room, *window))

    def test_no_place_means_no_conflict(self):
        self.assertEqual(services.find_conflicts(None, jst(2026, 11, 10, 13), jst(2026, 11, 10, 14)), [])

    def test_results_are_sorted_by_start(self):
        uses = [
            self.use(self.room, key=1, start=jst(2026, 11, 10, 15)),
            self.use(self.room, key=2, start=jst(2026, 11, 10, 13)),
        ]
        with mock.patch.dict(registry.PROVIDERS, {"fake": self.provider(uses)}, clear=True):
            result = services.find_conflicts(self.room, jst(2026, 11, 10, 12), jst(2026, 11, 10, 18))
        self.assertEqual([c.key for c in result], [2, 1])


class PlaceApiTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.member = User.objects.create_user("member", password="pw")
        self.school = Place.objects.create(name="校舎", is_venue=True, is_storage=False)
        self.studio = Place.objects.create(name="放送室", parent=self.school, is_venue=True, code="S1")
        self.shelf = Place.objects.create(name="棚A", parent=self.studio, is_venue=False)
        self.closed = Place.objects.create(name="旧部室", is_venue=True, is_active=False)
        self.event = Event.objects.create(
            title="定例会", start=jst(2026, 11, 10, 13), end=jst(2026, 11, 10, 15), place=self.studio
        )

    def get(self, name, *args, **params):
        self.client.force_login(self.member)
        return self.client.get(reverse(name, args=args), params)

    def test_login_required_returns_json_401(self):
        response = self.client.get(reverse("places_api:list"))
        self.assertEqual(response.status_code, 401)
        self.assertIn("error", response.json())

    def test_list_filters(self):
        names = lambda **p: [x["name"] for x in self.get("places_api:list", **p).json()["places"]]  # noqa: E731
        self.assertEqual(sorted(names(kind="venue")), sorted(["校舎", "放送室"]))  # 停止中は出ない
        self.assertEqual(sorted(names(kind="storage")), sorted(["放送室", "棚A"]))
        self.assertIn("旧部室", names(kind="all", include_inactive="1"))
        self.assertEqual(names(q="棚"), ["棚A"])
        self.assertEqual(self.get("places_api:list", kind="bogus").status_code, 400)

    def test_list_item_shape(self):
        item = next(p for p in self.get("places_api:list").json()["places"] if p["name"] == "放送室")
        self.assertEqual(
            item,
            {"id": self.studio.pk, "name": "放送室", "code": "S1", "path": "校舎 / 放送室",
             "parent_id": self.school.pk, "is_active": True, "is_storage": True, "is_venue": True},
        )

    def test_detail_has_ancestors_and_children(self):
        data = self.get("places_api:detail", self.studio.pk).json()
        self.assertEqual([a["name"] for a in data["ancestors"]], ["校舎"])
        self.assertEqual([c["name"] for c in data["children"]], ["棚A"])
        self.assertEqual(self.get("places_api:detail", 99999).status_code, 404)

    def test_usage_reports_conflicts_from_schedule(self):
        data = self.get(
            "places_api:usage", self.studio.pk, start="2026-11-10T14:00", end="2026-11-10T16:00"
        ).json()
        self.assertFalse(data["available"])
        self.assertEqual(data["conflicts"][0]["title"], "定例会")
        self.assertEqual(data["conflicts"][0]["source"], "schedule")
        self.assertEqual(data["conflicts"][0]["place_path"], "校舎 / 放送室")
        self.assertTrue(data["conflicts"][0]["url"].startswith(f"/schedule/{self.event.pk}/"))

    def test_usage_is_available_at_other_times_and_places(self):
        free_time = self.get("places_api:usage", self.studio.pk, start="2026-11-10T16:00", end="2026-11-10T17:00").json()
        self.assertTrue(free_time["available"])
        other = self.get("places_api:usage", self.closed.pk, start="2026-11-10T13:00", end="2026-11-10T14:00").json()
        self.assertTrue(other["available"])

    def test_usage_considers_parent_and_child_places(self):
        child = self.get("places_api:usage", self.shelf.pk, start="2026-11-10T13:30", end="2026-11-10T14:00").json()
        parent = self.get("places_api:usage", self.school.pk, start="2026-11-10T13:30", end="2026-11-10T14:00").json()
        self.assertFalse(child["available"])
        self.assertFalse(parent["available"])

    def test_usage_accepts_dates_and_offsets_and_exclude(self):
        whole_day = self.get("places_api:usage", self.studio.pk, start="2026-11-10", end="2026-11-10").json()
        self.assertFalse(whole_day["available"])
        offset = self.get(
            "places_api:usage", self.studio.pk, start="2026-11-10T14:00:00+09:00", end="2026-11-10T14:30:00+09:00"
        ).json()
        self.assertFalse(offset["available"])
        excluded = self.get(
            "places_api:usage", self.studio.pk, start="2026-11-10T14:00", end="2026-11-10T15:00",
            exclude=f"schedule:{self.event.pk}",
        ).json()
        self.assertTrue(excluded["available"])

    def test_usage_validates_parameters(self):
        url = "places_api:usage"
        self.assertEqual(self.get(url, self.studio.pk).status_code, 400)
        self.assertEqual(self.get(url, self.studio.pk, start="x", end="y").status_code, 400)
        self.assertEqual(self.get(url, self.studio.pk, start="2026-11-11", end="2026-11-10").status_code, 400)
        self.assertEqual(self.get(url, self.studio.pk, start="2026-01-01", end="2028-01-01").status_code, 400)


class PlaceManagementTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("staff", password="pw", is_staff=True)
        self.member = User.objects.create_user("member", password="pw")

    def test_only_staff_can_manage(self):
        self.client.force_login(self.member)
        for name in ("places:list", "places:create"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 302)

    def test_staff_creates_a_venue_and_the_form_defaults_to_venue(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse("places:create"))
        self.assertTrue(page.context["form"].initial["is_venue"])
        response = self.client.post(
            reverse("places:create"),
            {"name": "体育館", "is_venue": "on", "is_active": "on"},
        )
        self.assertRedirects(response, reverse("places:list"))
        place = Place.objects.get(name="体育館")
        self.assertTrue(place.is_venue)
        self.assertFalse(place.is_storage)

    def test_parent_cannot_be_itself_or_a_descendant(self):
        top = Place.objects.create(name="校舎")
        child = Place.objects.create(name="放送室", parent=top)
        self.client.force_login(self.staff)
        response = self.client.post(
            reverse("places:edit", args=[top.pk]),
            {"name": "校舎", "parent": child.pk, "is_active": "on"},
        )
        self.assertEqual(response.status_code, 200)
        top.refresh_from_db()
        self.assertIsNone(top.parent)

    def test_list_shows_hierarchy_and_flags(self):
        top = Place.objects.create(name="校舎", is_venue=True)
        Place.objects.create(name="放送室", parent=top, is_venue=True)
        self.client.force_login(self.staff)
        self.assertContains(self.client.get(reverse("places:list")), "校舎 / 放送室")


class EventLocationMigrationTests(TransactionTestCase):
    """予定の自由入力の場所が、場所マスターへ移る(一致→紐付け、不一致・曖昧→メモへ退避)。"""

    serialized_rollback = True

    # 移行後の状態に places を含めるため、places 側の最新も一緒に指定する
    BEFORE = [("schedule", "0004_attendance_reminder_delivery"), ("places", "0002_place_kinds")]
    AFTER = [("schedule", "0005_event_place"), ("places", "0002_place_kinds")]

    def migrate(self, targets):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(targets)
        return MigrationExecutor(connection).loader.project_state(targets).apps

    def tearDown(self):
        self.migrate(self.AFTER)
        super().tearDown()

    def test_free_text_locations_move_to_the_master(self):
        old = self.migrate(self.BEFORE)
        OldEvent = old.get_model("schedule", "Event")
        OldPlace = old.get_model("places", "Place")
        from django.utils import timezone as tz

        gym = OldPlace.objects.create(name="体育館", is_venue=False)
        OldPlace.objects.create(name="部室", parent=None)
        OldPlace.objects.create(name="部室", parent=gym)  # 同名が2件=曖昧
        now = tz.now()
        matched = OldEvent.objects.create(title="A", start=now, location="体育館")
        ambiguous = OldEvent.objects.create(title="B", start=now, location="部室", description="既存のメモ")
        unmatched = OldEvent.objects.create(title="C", start=now, location="ギャラリー")
        blank = OldEvent.objects.create(title="D", start=now, location="")

        new = self.migrate(self.AFTER)
        Event = new.get_model("schedule", "Event")
        Place = new.get_model("places", "Place")

        matched = Event.objects.get(pk=matched.pk)
        self.assertEqual(matched.place.name, "体育館")
        self.assertTrue(Place.objects.get(name="体育館").is_venue)  # 使われたので、予定の場所として使えるように

        ambiguous = Event.objects.get(pk=ambiguous.pk)
        self.assertIsNone(ambiguous.place)
        self.assertEqual(ambiguous.description, "【場所】部室\n既存のメモ")

        unmatched = Event.objects.get(pk=unmatched.pk)
        self.assertIsNone(unmatched.place)
        self.assertEqual(unmatched.description, "【場所】ギャラリー")

        blank = Event.objects.get(pk=blank.pk)
        self.assertIsNone(blank.place)
        self.assertEqual(blank.description, "")
