from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .importer import import_roster_csv
from .models import Position, RosterEntry


class RosterImportTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="roll-staff",
            is_staff=True,
        )
        self.client.force_login(self.staff)
        self.position = Position.objects.create(name="部長")

    def upload(self, content, filename="roster.csv"):
        return SimpleUploadedFile(filename, content.encode("utf-8"))

    def test_import_registers_students_staff_and_organizations(self):
        csv_content = (
            "種別,氏名,ふりがな,校内識別番号,学年,組,部員,役職\n"
            "生徒,山田花子,やまだはなこ,S001,2,3,はい,部長\n"
            "教職員,佐藤太郎,さとうたろう,T001,,,,\n"
            "校内団体,放送部,,,,,,\n"
        )

        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "新規 3 件")
        student = RosterEntry.objects.get(school_identifier="S001")
        self.assertEqual((student.grade, student.homeroom), ("2", "3"))
        self.assertTrue(student.is_member)
        self.assertEqual(list(student.positions.all()), [self.position])
        self.assertEqual(
            RosterEntry.objects.get(school_identifier="T001").entry_type,
            RosterEntry.EntryType.FACULTY,
        )
        self.assertEqual(
            RosterEntry.objects.get(name="放送部").entry_type,
            RosterEntry.EntryType.ORGANIZATION,
        )

    def test_import_links_account_and_updates_matching_school_identifier(self):
        user = get_user_model().objects.create_user(
            username="student-account",
            email="student@example.com",
        )
        csv_content = (
            "種別,氏名,校内識別番号,部員,アカウント\n"
            "生徒,山田花子,S002,はい,student@example.com\n"
        )

        import_roster_csv(self.upload(csv_content))
        entry = RosterEntry.objects.get(school_identifier="S002")
        self.assertEqual(entry.account, user)

        updated_csv = (
            "種別,氏名,校内識別番号,部員,アカウント\n"
            "生徒,山田花子,S002,いいえ,\n"
        )
        created_count, updated_count = import_roster_csv(self.upload(updated_csv))

        entry.refresh_from_db()
        self.assertEqual((created_count, updated_count), (0, 1))
        self.assertFalse(entry.is_member)
        self.assertIsNone(entry.account)
        self.assertEqual(RosterEntry.objects.filter(school_identifier="S002").count(), 1)

    def test_import_reports_unknown_position_without_partial_import(self):
        csv_content = (
            "種別,氏名,校内識別番号,役職\n"
            "生徒,山田花子,S003,未登録役職\n"
        )

        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "未登録の役職")
        self.assertFalse(RosterEntry.objects.filter(school_identifier="S003").exists())

    def test_import_rejects_non_csv_extension(self):
        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload("氏名\n山田花子", filename="roster.txt")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "拡張子が.csv")

    def test_import_accepts_shift_jis_csv(self):
        uploaded_file = SimpleUploadedFile(
            "roster.csv",
            "氏名\n山田花子".encode("cp932"),
        )

        created_count, updated_count = import_roster_csv(uploaded_file)

        self.assertEqual((created_count, updated_count), (1, 0))
        self.assertTrue(RosterEntry.objects.filter(name="山田花子").exists())

    def test_import_normalizes_legacy_school_class_labels(self):
        csv_content = "氏名,学年,組\n山田花子,高校2年,3組\n"

        import_roster_csv(self.upload(csv_content))

        entry = RosterEntry.objects.get(name="山田花子")
        self.assertEqual((entry.grade, entry.homeroom), ("2", "3"))

    def test_import_accepts_maximum_grade_and_homeroom(self):
        csv_content = "氏名,学年,組\n山田花子,6,9\n"

        import_roster_csv(self.upload(csv_content))

        entry = RosterEntry.objects.get(name="山田花子")
        self.assertEqual((entry.grade, entry.homeroom), ("6", "9"))

    def test_import_stores_attendance_number_separately_from_school_identifier(self):
        csv_content = (
            "氏名,校内識別番号,学年,組,出席番号\n"
            "山田花子,S01234,2,3,12\n"
        )

        import_roster_csv(self.upload(csv_content))

        entry = RosterEntry.objects.get(name="山田花子")
        self.assertEqual(entry.school_identifier, "S01234")
        self.assertEqual(entry.student_number, 12)

    def test_import_rejects_non_positive_attendance_number(self):
        csv_content = "氏名,出席番号\n山田花子,0\n"

        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "出席番号は1以上の数字")
        self.assertFalse(RosterEntry.objects.exists())

    def test_import_reports_rows_with_more_values_than_headers(self):
        csv_content = "氏名,学年\n山田花子,2,余分な値\n"

        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ヘッダーより多くの列")
        self.assertFalse(RosterEntry.objects.exists())

    def test_import_rejects_grade_or_homeroom_outside_available_ranges(self):
        csv_content = (
            "氏名,学年,組\n"
            "学年不正,7,3\n"
            "組不正,6,10\n"
        )

        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "学年（1〜6）")
        self.assertFalse(RosterEntry.objects.exists())

    def test_import_rejects_account_already_linked_to_another_entry(self):
        user = get_user_model().objects.create_user(username="already-linked")
        RosterEntry.objects.create(
            name="既存部員",
            school_identifier="S004",
            account=user,
        )
        csv_content = (
            "種別,氏名,校内識別番号,アカウント\n"
            "生徒,別の生徒,S005,already-linked\n"
        )

        response = self.client.post(
            reverse("roll:import_csv"),
            {"csv_file": self.upload(csv_content)},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "別の名簿に紐付け済み")
        self.assertFalse(RosterEntry.objects.filter(school_identifier="S005").exists())


class RosterAdminTests(TestCase):
    def test_grade_and_homeroom_are_select_fields_in_admin(self):
        staff = get_user_model().objects.create_superuser(
            username="roll-admin",
            email="roll-admin@example.com",
            password="test-password",
        )
        entry = RosterEntry.objects.create(name="管理テスト")
        self.client.force_login(staff)

        response = self.client.get(
            reverse("admin:roll_rosterentry_change", args=[entry.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<select name="grade"', html=False)
        self.assertContains(response, '<option value="6">6年</option>', html=False)
        self.assertContains(response, '<select name="homeroom"', html=False)
        self.assertContains(response, '<option value="9">9組</option>', html=False)
        self.assertContains(response, '<input type="number" name="student_number"', html=False)

class RosterAccessTests(TestCase):
    def test_roster_and_csv_import_are_staff_only(self):
        user = get_user_model().objects.create_user(username="regular-user")
        self.client.force_login(user)

        response = self.client.get(reverse("roll:list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_roster_list_shows_members_roles_and_accounts(self):
        user = get_user_model().objects.create_user(username="roster-account")
        staff = get_user_model().objects.create_user(
            username="roster-staff",
            is_staff=True,
        )
        position = Position.objects.create(name="会計")
        member = RosterEntry.objects.create(
            name="部員一郎",
            is_member=True,
            account=user,
            grade="2",
            homeroom="3",
            student_number=12,
        )
        member.positions.add(position)
        self.client.force_login(staff)

        response = self.client.get(reverse("roll:list"), {"members": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, member.name)
        self.assertContains(response, position.name)
        self.assertContains(response, user.username)
        self.assertContains(response, "2年 3組 12番")
        self.assertContains(response, "CSVインポート")
