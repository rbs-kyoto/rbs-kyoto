from datetime import date
from unittest.mock import patch

import qrcode
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    Category,
    Equipment,
    EquipmentHistory,
    ReturnRecord,
    StorageLocation,
    UsageRecord,
)
from roll.models import RosterEntry


class EquipmentWorkflowTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="inventory-user",
            password="test-password-123",
        )
        self.client.force_login(self.user)
        self.category_a = Category.objects.get(code="A")
        self.responsible_person = RosterEntry.objects.create(
            name="担当者",
            entry_type=RosterEntry.EntryType.STUDENT,
        )
        self.equipment = Equipment.objects.create(
            category=self.category_a,
            inventory_number="A-0042",
            name="テストマイク",
            quantity=5,
            unit="本",
            created_by=self.user,
        )

    def test_inventory_number_is_not_rewritten_when_category_changes(self):
        self.assertEqual(self.equipment.inventory_number, "A-0042")
        self.assertEqual(len(self.equipment.qr_token), 12)

        self.equipment.category = Category.objects.get(code="C")
        self.equipment.save()
        self.assertEqual(self.equipment.inventory_number, "A-0042")

    def test_categories_are_stored_in_database(self):
        response = self.client.get(reverse("equipment:categories"))

        self.assertEqual(Category.objects.count(), 26)
        self.assertContains(response, "A〜Z")
        self.assertContains(response, "音響機器")

    def test_category_management_button_opens_admin_category_list(self):
        admin_user = get_user_model().objects.create_superuser(
            username="category-admin",
            password="test-password",
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("equipment:categories"))
        admin_response = self.client.get(
            reverse("admin:equipment_category_changelist")
        )

        self.assertContains(
            response,
            f'href="{reverse("admin:equipment_category_changelist")}"',
        )
        self.assertEqual(admin_response.status_code, 200)

    def test_admin_can_delete_equipment_record(self):
        admin_user = get_user_model().objects.create_user(
            username="equipment-delete-admin",
            is_staff=True,
            is_superuser=True,
        )
        usage = UsageRecord.objects.create(
            equipment=self.equipment,
            usage_type=UsageRecord.UsageType.LENDING,
            destination="テスト貸出先",
            quantity=1,
        )
        ReturnRecord.objects.create(
            usage=usage,
            quantity=1,
        )
        EquipmentHistory.objects.create(
            equipment=self.equipment,
            field_name="備品名",
            old_value="旧名称",
            new_value="テストマイク",
        )
        self.client.force_login(admin_user)
        delete_url = reverse(
            "admin:equipment_equipment_delete",
            args=[self.equipment.pk],
        )

        confirmation = self.client.get(delete_url)
        response = self.client.post(delete_url, {"post": "yes"})

        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, "削除")
        self.assertEqual(
            response.status_code,
            302,
            response.content.decode(),
        )
        self.assertRedirects(response, reverse("admin:equipment_equipment_changelist"))
        self.assertFalse(Equipment.objects.filter(pk=self.equipment.pk).exists())
        self.assertFalse(UsageRecord.objects.filter(pk=usage.pk).exists())
        self.assertFalse(ReturnRecord.objects.filter(usage_id=usage.pk).exists())
        self.assertFalse(
            EquipmentHistory.objects.filter(equipment_id=self.equipment.pk).exists()
        )

    def test_register_records_actor_and_initial_history(self):
        with patch("equipment.numbering.timezone.localdate", return_value=date(2026, 10, 23)):
            response = self.client.post(
                reverse("equipment:register"),
                {
                    "category": Category.objects.get(code="W").pk,
                    "name": "事務用ノート",
                    "quantity": "3",
                    "unit": "冊",
                    "purchase_currency": Equipment.Currency.JPY,
                    "condition": Equipment.Condition.NORMAL,
                },
            )

        self.assertEqual(response.status_code, 302)
        created = Equipment.objects.get(name="事務用ノート")
        self.assertEqual(created.inventory_number, "W-621261023a")
        self.assertEqual(created.created_by, self.user)
        self.assertTrue(
            EquipmentHistory.objects.filter(
                equipment=created, field_name="登録"
            ).exists()
        )

    def test_new_equipment_gets_next_daily_letter_across_categories(self):
        fixed_date = date(2026, 10, 23)
        Equipment.objects.create(
            category=Category.objects.get(code="D"),
            inventory_number="D-621261023a",
            name="同日登録済み備品",
            quantity=1,
        )

        with patch("equipment.numbering.timezone.localdate", return_value=fixed_date):
            response = self.client.post(
                reverse("equipment:register"),
                {
                    "category": self.category_a.pk,
                    "name": "自動番号の備品",
                    "quantity": "1",
                    "unit": "個",
                    "purchase_currency": Equipment.Currency.JPY,
                    "condition": Equipment.Condition.NORMAL,
                },
            )

        self.assertEqual(response.status_code, 302)
        created = Equipment.objects.get(name="自動番号の備品")
        self.assertEqual(created.inventory_number, "A-621261023b")

    def test_new_equipment_uses_purchase_date_for_inventory_number(self):
        response = self.client.post(
            reverse("equipment:register"),
            {
                "category": self.category_a.pk,
                "name": "購入日付番の備品",
                "quantity": "1",
                "unit": "個",
                "purchased_on": "2024-06-15",
                "purchase_currency": Equipment.Currency.JPY,
                "condition": Equipment.Condition.NORMAL,
            },
        )

        self.assertEqual(response.status_code, 302)
        equipment = Equipment.objects.get(name="購入日付番の備品")
        self.assertEqual(equipment.inventory_number, "A-621240615a")

    def test_daily_inventory_number_limit_is_25_across_categories(self):
        fixed_date = date(2026, 10, 23)
        for index, suffix in enumerate("abcdefghijklmnopqrstuvwxy"):
            Equipment.objects.create(
                category=Category.objects.get(code="D" if index % 2 else "A"),
                inventory_number=f"{'D' if index % 2 else 'A'}-621261023{suffix}",
                name=f"同日登録済み備品{index}",
                quantity=1,
            )

        with patch("equipment.numbering.timezone.localdate", return_value=fixed_date):
            response = self.client.post(
                reverse("equipment:register"),
                {
                    "category": self.category_a.pk,
                    "name": "上限超過の備品",
                    "quantity": "1",
                    "unit": "個",
                    "purchase_currency": Equipment.Currency.JPY,
                    "condition": Equipment.Condition.NORMAL,
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Equipment.objects.filter(name="上限超過の備品").exists())
        self.assertContains(response, "上限の25件に達しています")

    def test_edit_records_changed_fields(self):
        response = self.client.post(
            reverse("equipment:edit", args=[self.equipment.pk]),
            {
                "category": self.category_a.pk,
                "name": "編集後マイク",
                "manufacturer": "",
                "model_number": "",
                "serial_number": "",
                "receipt_number": "RC-2026-0042",
                "quantity": "5",
                "unit": "本",
                "manager": "",
                "location": "",
                "purchased_on": "",
                "purchase_price": "",
                "purchase_currency": Equipment.Currency.USD,
                "purchase_vendor": "",
                "warranty_expiry": "",
                "expected_lifespan_years": "",
                "notes": "",
                "condition": Equipment.Condition.NORMAL,
            },
        )

        self.assertEqual(response.status_code, 302)
        change = EquipmentHistory.objects.get(
            equipment=self.equipment, field_name="備品名"
        )
        self.assertEqual(change.old_value, "テストマイク")
        self.assertEqual(change.new_value, "編集後マイク")
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.receipt_number, "RC-2026-0042")
        self.assertEqual(self.equipment.purchase_currency, Equipment.Currency.USD)

    def test_lending_rejects_quantity_above_available_stock(self):
        response = self.client.post(
            reverse("equipment:lending_register"),
            {
                "equipment": self.equipment.pk,
                "usage_type": UsageRecord.UsageType.LENDING,
                "destination": "放送室",
                "responsible_person": str(self.responsible_person.pk),
                "recipient": "受取者",
                "quantity": "6",
                "started_at": "2026-10-01T10:00",
                "due_at": "",
                "purpose": "収録",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(UsageRecord.objects.exists())
        self.assertContains(response, "貸出可能数量を超えています")

    def test_partial_returns_update_available_quantity_without_overwriting_history(self):
        usage = UsageRecord.objects.create(
            equipment=self.equipment,
            usage_type=UsageRecord.UsageType.LENDING,
            destination="学園祭",
            quantity=5,
            created_by=self.user,
        )

        response = self.client.post(
            reverse("equipment:return", args=[usage.pk]),
            {
                "quantity": "2",
                "returned_at": "2026-10-01T10:00",
                "confirmed_by": "確認者",
                "condition": ReturnRecord.Condition.NORMAL,
                "condition_details": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(usage.remaining_quantity, 3)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_quantity, 2)

        self.client.post(
            reverse("equipment:return", args=[usage.pk]),
            {
                "quantity": "3",
                "returned_at": "2026-10-02T10:00",
                "confirmed_by": "確認者",
                "condition": ReturnRecord.Condition.NORMAL,
                "condition_details": "",
                "notes": "",
            },
        )
        self.assertEqual(usage.returns.count(), 2)
        self.assertEqual(usage.remaining_quantity, 0)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_quantity, 5)

    def test_damaged_return_is_not_counted_as_available_stock(self):
        usage = UsageRecord.objects.create(
            equipment=self.equipment,
            usage_type=UsageRecord.UsageType.LENDING,
            destination="収録",
            quantity=2,
            created_by=self.user,
        )
        ReturnRecord.objects.create(
            usage=usage,
            quantity=1,
            condition=ReturnRecord.Condition.DAMAGED,
            processed_by=self.user,
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.available_quantity, 3)

    def test_unregister_is_soft_and_requires_a_reason(self):
        url = reverse("equipment:unregister", args=[self.equipment.pk])
        response = self.client.post(url, {"reason": ""})
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)

        response = self.client.post(url, {"reason": "廃棄"})
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertFalse(self.equipment.is_active)
        self.assertEqual(self.equipment.unregistration_reason, "廃棄")
        self.assertTrue(Equipment.objects.filter(pk=self.equipment.pk).exists())
        self.assertTrue(
            EquipmentHistory.objects.filter(
                equipment=self.equipment, field_name="登録状態"
            ).exists()
        )

    def test_qr_downloads_are_available_in_png_and_svg(self):
        png = self.client.get(reverse("equipment:qr_png", args=[self.equipment.pk]))
        svg = self.client.get(reverse("equipment:qr_svg", args=[self.equipment.pk]))

        self.assertEqual(png["Content-Type"], "image/png")
        self.assertTrue(png.content.startswith(b"\x89PNG"))
        self.assertEqual(svg["Content-Type"], "image/svg+xml")
        self.assertIn(b"<svg", svg.content)

    def test_qr_contains_only_stable_inventory_number_with_high_error_correction(self):
        created_qr_codes = []

        class RecordingQRCode(qrcode.QRCode):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                created_qr_codes.append(self)

            def add_data(self, data, *args, **kwargs):
                self.payload = data
                super().add_data(data, *args, **kwargs)

        with patch("equipment.views.qrcode.QRCode", RecordingQRCode):
            response = self.client.get(
                reverse("equipment:qr_png", args=[self.equipment.pk])
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(created_qr_codes), 1)
        self.assertEqual(created_qr_codes[0].payload, "A-0042")
        self.assertEqual(
            created_qr_codes[0].error_correction,
            qrcode.constants.ERROR_CORRECT_H,
        )

    def test_qr_inventory_number_still_finds_equipment_after_number_change(self):
        self.equipment.inventory_number = "C-0199"
        self.equipment.save()

        response = self.client.get(
            reverse("equipment:scan"), {"q": self.equipment.qr_inventory_number}
        )

        self.assertEqual(self.equipment.qr_inventory_number, "A-0042")
        self.assertRedirects(
            response, reverse("equipment:detail", args=[self.equipment.pk])
        )

    def test_d_format_qr_payload_redirects_to_the_matching_equipment(self):
        equipment = Equipment.objects.create(
            category=Category.objects.get(code="D"),
            inventory_number="D-52610230",
            name="テストSSD",
            quantity=1,
            created_by=self.user,
        )

        with patch("equipment.views.qrcode.QRCode.add_data") as add_data:
            response = self.client.get(
                reverse("equipment:qr_png", args=[equipment.pk])
            )

        add_data.assert_called_once_with("D-52610230")
        scan_response = self.client.get(
            reverse("equipment:scan"), {"q": "D-52610230"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertRedirects(
            scan_response, reverse("equipment:detail", args=[equipment.pk])
        )

    def test_scanner_page_loads_versioned_scanner_script(self):
        response = self.client.get(reverse("equipment:scan_camera"))

        self.assertContains(response, "equipment/vendor/jsQR.min.js?v=1")
        self.assertContains(response, "equipment/scan.js?v=4")
        rendered_page = response.content.decode()
        self.assertLess(
            rendered_page.index("equipment/vendor/jsQR.min.js?v=1"),
            rendered_page.index("equipment/scan.js?v=4"),
        )

    def test_qr_scan_manual_search_input_and_button_share_a_row(self):
        response = self.client.get(reverse("equipment:scan"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="equipment__manual-search"')
        self.assertContains(response, '<input name="q" autocomplete="off" required>')
        self.assertContains(response, ">検索</button>")

    def test_equipment_form_keeps_quantity_and_price_controls_paired(self):
        response = self.client.get(reverse("equipment:register"))
        rendered_form = response.content.decode()

        self.assertContains(response, 'class="equipment__field-pair"')
        self.assertContains(
            response,
            f'<option value="{self.responsible_person.pk}">{self.responsible_person}</option>',
        )
        self.assertContains(response, "レシート番号")
        self.assertContains(response, "法定耐用年数")
        self.assertContains(response, "米ドル")
        self.assertContains(response, "ユーロ")
        self.assertGreater(
            rendered_form.index("購入・保証情報"),
            rendered_form.index("数量・状態"),
        )
        self.assertLess(
            rendered_form.index("購入・保証情報"),
            rendered_form.index("レシート番号"),
        )

    def test_inventory_list_colors_status_text_by_status(self):
        response = self.client.get(reverse("equipment:list"))

        self.assertContains(
            response,
            'class="equipment__status equipment__status--stored"',
        )

    def test_archived_equipment_uses_red_unregistered_status(self):
        self.equipment.is_active = False
        self.equipment.save()

        response = self.client.get(reverse("equipment:list"), {"archived": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "登録解除済み")
        self.assertContains(
            response,
            'class="equipment__status equipment__status--unregistered"',
        )
        self.assertNotContains(response, "equipment__status--stored")

    def test_inventory_list_csv_exports_the_filtered_inventory(self):
        response = self.client.get(reverse("equipment:list"))
        csv_response = self.client.get(response.context["csv_url"])

        self.assertEqual(csv_response.status_code, 200)
        self.assertEqual(csv_response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("A-0042".encode(), csv_response.content)
        self.assertIn("テストマイク".encode(), csv_response.content)

    def test_inventory_list_supports_ten_items_per_page(self):
        for index in range(10):
            Equipment.objects.create(
                category=self.category_a,
                inventory_number=f"A-{index + 100:04d}",
                name=f"一覧テスト備品{index}",
                quantity=1,
                created_by=self.user,
            )

        response = self.client.get(
            reverse("equipment:list"), {"page_size": "10"}
        )

        self.assertEqual(len(response.context["equipment_list"]), 10)
        self.assertEqual(response.context["page_obj"].paginator.count, 11)
        self.assertTrue(response.context["page_obj"].has_next())
        second_page = self.client.get(
            reverse("equipment:list"), {"page_size": "10", "page": "2"}
        )
        self.assertEqual(len(second_page.context["equipment_list"]), 1)

    def test_inventory_pages_render(self):
        pages = [
            (reverse("equipment:dashboard"), "備品管理ダッシュボード"),
            (reverse("equipment:list"), "備品一覧"),
            (reverse("equipment:detail", args=[self.equipment.pk]), "テストマイク"),
            (reverse("equipment:history", args=[self.equipment.pk]), "テストマイクの履歴"),
            (reverse("equipment:qr", args=[self.equipment.pk]), "A-0042 QRコード"),
            (reverse("equipment:lending"), "貸出・持出一覧"),
            (reverse("equipment:categories"), "分類一覧"),
            (reverse("equipment:locations"), "保管場所"),
            (reverse("equipment:settings"), "備品管理設定"),
        ]
        for url, page_title in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f"<title>{page_title}｜rbs京都</title>",
                    html=True,
                )
                if url in {
                    reverse("equipment:dashboard"),
                    reverse("equipment:list"),
                }:
                    self.assertContains(
                        response,
                        'class="common-style reverse equipment__button',
                    )
                if url == reverse("equipment:qr", args=[self.equipment.pk]):
                    self.assertContains(
                        response,
                        'class="common-style white equipment__button',
                    )
                    self.assertContains(
                        response,
                        "QRコードは株式会社デンソーウェーブの登録商標です。",
                    )

    def test_scanner_page_displays_qr_trademark_notice(self):
        response = self.client.get(reverse("equipment:scan_camera"))

        self.assertContains(
            response,
            "QRコードは株式会社デンソーウェーブの登録商標です。",
        )

    def test_equipment_detail_groups_information_and_uses_full_width_without_photo(self):
        response = self.client.get(
            reverse("equipment:detail", args=[self.equipment.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "備品情報")
        self.assertContains(response, "在庫・管理情報")
        self.assertContains(response, "購入・保証情報")
        self.assertContains(response, "備考・登録情報")
        self.assertContains(
            response,
            'class="equipment__detail-layout"',
        )
        self.assertNotContains(response, "equipment__detail-layout--with-photo")

    def test_equipment_forms_use_dark_primary_and_white_cancel_buttons(self):
        response = self.client.get(reverse("equipment:register"))

        for heading in (
            "備品の基本情報",
            "数量・状態",
            "管理情報",
            "購入・保証情報",
            "備考・画像",
        ):
            with self.subTest(heading=heading):
                self.assertContains(response, heading)
        self.assertContains(
            response,
            'class="common-style reverse equipment__button" type="submit"',
        )
        self.assertContains(
            response,
            'class="common-style white equipment__button"',
        )

    def test_unregistered_equipment_can_be_found_and_reactivated(self):
        self.client.post(
            reverse("equipment:unregister", args=[self.equipment.pk]),
            {"reason": "廃棄予定"},
        )

        response = self.client.get(reverse("equipment:list"), {"archived": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.equipment.inventory_number)
        response = self.client.get(
            reverse("equipment:detail", args=[self.equipment.pk]),
            {"show_archived": "1"},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse("equipment:reactivate", args=[self.equipment.pk])
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)

    def test_unregistration_is_blocked_while_items_are_still_issued(self):
        UsageRecord.objects.create(
            equipment=self.equipment,
            usage_type=UsageRecord.UsageType.LENDING,
            destination="撮影",
            quantity=1,
            created_by=self.user,
        )
        response = self.client.post(
            reverse("equipment:unregister", args=[self.equipment.pk]),
            {"reason": "廃棄予定"},
        )

        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertTrue(self.equipment.is_active)
        self.assertEqual(EquipmentHistory.objects.filter(
            equipment=self.equipment, field_name="登録状態"
        ).count(), 0)

    def test_hierarchical_location_form_rejects_cycles(self):
        location = StorageLocation.objects.create(name="部室")
        child = StorageLocation.objects.create(name="棚", parent=location)

        response = self.client.post(
            reverse("equipment:location_edit", args=[location.pk]),
            {
                "name": "部室",
                "code": "",
                "parent": child.pk,
                "description": "",
                "notes": "",
                "is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        location.refresh_from_db()
        self.assertIsNone(location.parent)
        self.assertContains(response, "自分自身を上位保管場所には指定できません")


class EquipmentAccessTests(TestCase):
    def test_all_equipment_pages_require_authentication(self):
        urls = [
            reverse("equipment:dashboard"),
            reverse("equipment:list"),
            reverse("equipment:register"),
            reverse("equipment:scan_camera"),
            reverse("equipment:categories"),
            reverse("equipment:locations"),
            reverse("equipment:lending"),
            reverse("equipment:settings"),
        ]

        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("accounts:login"), response["Location"])
