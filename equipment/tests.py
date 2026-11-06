import json
from datetime import date, datetime, timedelta
from io import StringIO
from unittest.mock import patch

import qrcode
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from pywebpush import WebPushException
from requests import Response

from .numbering import generate_inventory_number
from .models import (
    Category,
    Equipment,
    EquipmentModel,
    EquipmentHistory,
    EquipmentReminderDelivery,
    Manufacturer,
    Loan,
    LoanLine,
    ReturnRecord,
    StorageLocation,
)
from .testing import make_usage
from accounts.models import WebPushSubscription
from roll.models import Position, RosterEntry


class EquipmentDueReminderCommandTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="push-borrower")
        self.entry = RosterEntry.objects.create(
            name="通知先",
            entry_type=RosterEntry.EntryType.STUDENT,
            account=self.user,
        )
        self.equipment = Equipment.objects.create(
            category=Category.objects.get(code="A"),
            inventory_number="A-PUSH-1",
            name="通知用マイク",
            quantity=20,
            unit="本",
        )
        self.subscription = WebPushSubscription.objects.create(
            user=self.user,
            endpoint="https://fcm.googleapis.com/fcm/send/push-borrower",
            p256dh="public-key",
            auth="auth-secret",
        )
        self.today = date(2026, 11, 5)

    def create_usage_due_in(self, days):
        due_date = self.today + timedelta(days=days)
        due_at = timezone.make_aware(datetime.combine(due_date, datetime.min.time()))
        return make_usage(
            equipment=self.equipment,
            usage_type=Loan.UsageType.LENDING,
            destination=str(self.entry),
            destination_entry=self.entry,
            quantity=1,
            due_at=due_at,
        )

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="public",
        WEBPUSH_VAPID_PRIVATE_KEY="private",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    @patch("equipment.management.commands.send_equipment_due_reminders.webpush")
    def test_sends_each_requested_reminder_once(self, send_push):
        for days in (7, 3, 1, 0, -3, -6):
            self.create_usage_due_in(days)

        with patch(
            "equipment.management.commands.send_equipment_due_reminders.timezone.localdate",
            return_value=self.today,
        ):
            output = StringIO()
            call_command("send_equipment_due_reminders", stdout=output)
            self.assertIn("Sent 6 equipment reminder(s).", output.getvalue())

            call_command("send_equipment_due_reminders", stdout=StringIO())

        self.assertEqual(send_push.call_count, 6)
        self.assertEqual(EquipmentReminderDelivery.objects.count(), 6)
        bodies = [
            json.loads(call.kwargs["data"])["body"]
            for call in send_push.call_args_list
        ]
        self.assertIn("「通知用マイク」の返却期限まであと7日です。 未返却：1本", bodies)
        self.assertIn("「通知用マイク」の返却期限まであと3日です。 未返却：1本", bodies)
        self.assertIn("「通知用マイク」の返却期限は本日です！ 未返却：1本", bodies)
        self.assertIn("「通知用マイク」の返却期限を過ぎています！ 未返却：1本", bodies)

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="public",
        WEBPUSH_VAPID_PRIVATE_KEY="private",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    @patch("equipment.management.commands.send_equipment_due_reminders.webpush")
    def test_does_not_send_for_returned_usage_or_unscheduled_dates(self, send_push):
        returned_usage = self.create_usage_due_in(7)
        ReturnRecord.objects.create(line=returned_usage, quantity=1)
        self.create_usage_due_in(5)

        with patch(
            "equipment.management.commands.send_equipment_due_reminders.timezone.localdate",
            return_value=self.today,
        ):
            call_command("send_equipment_due_reminders", stdout=StringIO())

        send_push.assert_not_called()
        self.assertFalse(EquipmentReminderDelivery.objects.exists())

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="public",
        WEBPUSH_VAPID_PRIVATE_KEY="private",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    @patch("equipment.management.commands.send_equipment_due_reminders.webpush")
    def test_does_not_send_when_equipment_reminders_are_disabled(self, send_push):
        self.create_usage_due_in(7)
        self.subscription.equipment_reminders_enabled = False
        self.subscription.save(update_fields=["equipment_reminders_enabled"])

        with patch(
            "equipment.management.commands.send_equipment_due_reminders.timezone.localdate",
            return_value=self.today,
        ):
            call_command("send_equipment_due_reminders", stdout=StringIO())

        send_push.assert_not_called()
        self.assertFalse(EquipmentReminderDelivery.objects.exists())

    @override_settings(
        WEBPUSH_VAPID_PUBLIC_KEY="public",
        WEBPUSH_VAPID_PRIVATE_KEY="private",
        WEBPUSH_VAPID_SUBJECT="mailto:admin@example.com",
    )
    @patch("equipment.management.commands.send_equipment_due_reminders.webpush")
    def test_removes_expired_push_subscriptions(self, send_push):
        self.create_usage_due_in(7)
        response = Response()
        response.status_code = 410
        send_push.side_effect = WebPushException("expired", response=response)

        with patch(
            "equipment.management.commands.send_equipment_due_reminders.timezone.localdate",
            return_value=self.today,
        ):
            call_command("send_equipment_due_reminders", stdout=StringIO())

        self.assertFalse(WebPushSubscription.objects.filter(pk=self.subscription.pk).exists())
        self.assertFalse(EquipmentReminderDelivery.objects.exists())


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

        self.equipment.model.category = Category.objects.get(code="C")
        self.equipment.model.save()
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
        usage = make_usage(
            equipment=self.equipment,
            usage_type=Loan.UsageType.LENDING,
            destination="テスト貸出先",
            quantity=1,
        )
        ReturnRecord.objects.create(
            line=usage,
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
        self.assertFalse(LoanLine.objects.filter(pk=usage.pk).exists())
        self.assertFalse(ReturnRecord.objects.filter(line_id=usage.pk).exists())
        self.assertFalse(
            EquipmentHistory.objects.filter(equipment_id=self.equipment.pk).exists()
        )

    def _register_payload(self, category, name):
        return {
            "category": category.pk,
            "name": name,
            "quantity": "1",
            "unit": "個",
            "purchase_currency": Equipment.Currency.JPY,
            "condition": Equipment.Condition.NORMAL,
        }

    def test_register_records_actor_and_initial_history(self):
        with patch("equipment.numbering.timezone.localdate", return_value=date(2026, 10, 23)):
            response = self.client.post(
                reverse("equipment:register"),
                self._register_payload(Category.objects.get(code="W"), "事務用ノート"),
            )

        self.assertEqual(response.status_code, 302)
        created = Equipment.objects.get(model__name="事務用ノート")
        self.assertEqual(created.inventory_number, "W-26000001")
        self.assertEqual(created.qr_inventory_number, "W-26000001")
        self.assertEqual(created.created_by, self.user)
        self.assertTrue(
            EquipmentHistory.objects.filter(
                equipment=created, field_name="登録"
            ).exists()
        )

    def test_serial_increments_per_category_and_fiscal_year(self):
        Equipment.objects.create(
            category=self.category_a,
            inventory_number="A-26000007",
            name="登録済み",
            quantity=1,
        )
        Equipment.objects.create(
            category=Category.objects.get(code="D"),
            inventory_number="D-26000003",
            name="別分類",
            quantity=1,
        )

        with patch("equipment.numbering.timezone.localdate", return_value=date(2026, 10, 23)):
            self.client.post(
                reverse("equipment:register"),
                self._register_payload(self.category_a, "次の備品"),
            )

        self.assertEqual(
            Equipment.objects.get(model__name="次の備品").inventory_number, "A-26000008"
        )

    def test_fiscal_year_switches_in_april(self):
        self.assertEqual(generate_inventory_number("A", date(2027, 3, 31)), "A-26000001")
        self.assertEqual(generate_inventory_number("A", date(2027, 4, 1)), "A-27000001")

    def test_number_ignores_purchase_date(self):
        with patch("equipment.numbering.timezone.localdate", return_value=date(2026, 10, 23)):
            response = self.client.post(
                reverse("equipment:register"),
                {
                    **self._register_payload(self.category_a, "購入日だけ古い備品"),
                    "purchased_on": "2024-06-15",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            Equipment.objects.get(model__name="購入日だけ古い備品").inventory_number,
            "A-26000001",
        )

    def test_edit_can_select_existing_manufacturer(self):
        sony = Manufacturer.objects.create(name="SONY")
        response = self.client.post(
            reverse("equipment:edit", args=[self.equipment.pk]),
            self._edit_payload(manufacturer=sony.pk),
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.manufacturer, sony)
        self.assertTrue(
            EquipmentHistory.objects.filter(
                equipment=self.equipment,
                field_name="メーカー",
                new_value="SONY",
            ).exists()
        )

    def test_edit_can_add_new_manufacturer_from_form(self):
        response = self.client.post(
            reverse("equipment:edit", args=[self.equipment.pk]),
            self._edit_payload(new_manufacturer="  Shure  "),
        )
        self.assertEqual(response.status_code, 302)
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.manufacturer.name, "Shure")
        self.assertEqual(Manufacturer.objects.filter(name="Shure").count(), 1)
        self.assertTrue(
            EquipmentHistory.objects.filter(
                equipment=self.equipment, field_name="メーカー"
            ).exists()
        )

    def test_new_manufacturer_reuses_existing_name_ignoring_case(self):
        existing = Manufacturer.objects.create(name="Shure")
        self.client.post(
            reverse("equipment:edit", args=[self.equipment.pk]),
            self._edit_payload(new_manufacturer="shure"),
        )
        self.equipment.refresh_from_db()
        self.assertEqual(self.equipment.manufacturer, existing)
        self.assertEqual(Manufacturer.objects.count(), 1)

    def _edit_payload(self, **overrides):
        payload = {
            "category": self.category_a.pk,
            "name": "テストマイク",
            "manufacturer": "",
            "model_number": "",
            "serial_number": "",
            "receipt_number": "",
            "quantity": "5",
            "unit": "本",
            "manager": "",
            "location": "",
            "purchased_on": "",
            "purchase_price": "",
            "purchase_currency": Equipment.Currency.JPY,
            "purchase_vendor": "",
            "warranty_expiry": "",
            "expected_lifespan_years": "",
            "notes": "",
            "condition": Equipment.Condition.NORMAL,
        }
        payload.update(overrides)
        return payload

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
                "usage_type": Loan.UsageType.LENDING,
                "destination_selection": "other",
                "other_destination": "放送室",
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
        self.assertFalse(Loan.objects.exists())
        self.assertContains(response, "貸出可能数量を超えています")

    def test_lending_destination_can_be_selected_from_roll(self):
        response = self.client.post(
            reverse("equipment:lending_register"),
            {
                "equipment": self.equipment.pk,
                "usage_type": Loan.UsageType.LENDING,
                "destination_selection": str(self.responsible_person.pk),
                "other_destination": "",
                "responsible_person": str(self.responsible_person.pk),
                "recipient": "受取者",
                "quantity": "1",
                "started_at": "2026-10-01T10:00",
                "due_at": "",
                "purpose": "収録",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        usage = LoanLine.objects.get()
        self.assertEqual(usage.destination_entry, self.responsible_person)
        self.assertEqual(usage.destination, str(self.responsible_person))
        self.assertRedirects(
            response,
            reverse("equipment:usage_detail", args=[usage.pk]),
        )

    def test_lending_destination_other_option_accepts_free_text(self):
        response = self.client.post(
            reverse("equipment:lending_register"),
            {
                "equipment": self.equipment.pk,
                "usage_type": Loan.UsageType.CARRY_OUT,
                "destination_selection": "other",
                "other_destination": "校外の収録会場",
                "responsible_person": str(self.responsible_person.pk),
                "recipient": "受取者",
                "quantity": "1",
                "started_at": "2026-10-01T10:00",
                "due_at": "",
                "purpose": "収録",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 302)
        usage = LoanLine.objects.get()
        self.assertIsNone(usage.destination_entry)
        self.assertEqual(usage.destination, "校外の収録会場")

    def test_lending_destination_other_option_requires_free_text(self):
        response = self.client.post(
            reverse("equipment:lending_register"),
            {
                "equipment": self.equipment.pk,
                "usage_type": Loan.UsageType.CARRY_OUT,
                "destination_selection": "other",
                "other_destination": "",
                "responsible_person": str(self.responsible_person.pk),
                "recipient": "",
                "quantity": "1",
                "started_at": "2026-10-01T10:00",
                "due_at": "",
                "purpose": "",
                "notes": "",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Loan.objects.exists())
        self.assertContains(response, "その他の貸出・持出先を入力してください")

    def test_lending_form_lists_roster_destinations_and_other(self):
        response = self.client.get(reverse("equipment:lending_register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'value="{self.responsible_person.pk}"')
        self.assertContains(response, f">{self.responsible_person}</option>")
        self.assertContains(response, 'value="other">その他</option>')

    def test_partial_returns_update_available_quantity_without_overwriting_history(self):
        usage = make_usage(
            equipment=self.equipment,
            usage_type=Loan.UsageType.LENDING,
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

        position = Position.objects.create(name="機材班長")
        response = self.client.get(reverse("equipment:register"))
        rendered_form = response.content.decode()

        self.assertContains(response, 'class="equipment__field-pair"')
        self.assertContains(
            response,
            f'<option value="{position.pk}">{position.name}</option>',
        )
        self.assertContains(response, "管理担当役職")
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
                        "※「QRコード」は株式会社デンソーウェーブの登録商標です。",
                    )

    def test_scanner_page_displays_qr_trademark_notice(self):
        response = self.client.get(reverse("equipment:scan_camera"))

        self.assertContains(
            response,
            "※「QRコード」は株式会社デンソーウェーブの登録商標です。",
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
        make_usage(
            equipment=self.equipment,
            usage_type=Loan.UsageType.LENDING,
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


class EquipmentCsvIoTests(TestCase):
    def setUp(self):
        self.staff = get_user_model().objects.create_user(
            username="csv-staff", password="pw-123456", is_staff=True
        )
        self.member = get_user_model().objects.create_user(
            username="csv-member", password="pw-123456"
        )
        self.category = Category.objects.get(code="A")
        self.location = StorageLocation.objects.create(name="放送室")
        self.manager = Position.objects.create(name="機材班長")
        holder = RosterEntry.objects.create(
            name="班長の人", entry_type=RosterEntry.EntryType.STUDENT
        )
        holder.positions.add(self.manager)

    def _upload(self, text, user=None, encoding="utf-8-sig"):
        self.client.force_login(user or self.staff)
        upload = SimpleUploadedFile(
            "equipment.csv", text.encode(encoding), content_type="text/csv"
        )
        return self.client.post(reverse("equipment:import"), {"csv_file": upload})

    def test_import_creates_equipment_with_auto_number_and_manufacturer(self):
        csv_text = (
            "備品名,分類,メーカー,型番,保有数量,単位,管理担当役職,保管場所,購入日,購入価格,通貨,備品の状態\n"
            "ワイヤレスマイク,A,SONY,UWP-D21,4,本,機材班長,放送室,2026/04/10,\"120,000\",米ドル,要点検\n"
            "ミキサー,音響機器,sony,,1,,,,,,,\n"
        )
        with patch("equipment.numbering.timezone.localdate", return_value=date(2026, 10, 23)):
            response = self._upload(csv_text)

        self.assertContains(response, "2件の備品を登録しました")
        first = Equipment.objects.get(model__name="ワイヤレスマイク")
        second = Equipment.objects.get(model__name="ミキサー")
        self.assertEqual(first.inventory_number, "A-26000001")
        self.assertEqual(second.inventory_number, "A-26000002")
        self.assertEqual(first.manufacturer, second.manufacturer)
        self.assertEqual(Manufacturer.objects.count(), 1)
        self.assertEqual(first.manager, self.manager)
        self.assertEqual(first.location, self.location)
        self.assertEqual(first.purchased_on, date(2026, 4, 10))
        self.assertEqual(first.purchase_price, 120000)
        self.assertEqual(first.purchase_currency, "USD")
        self.assertEqual(first.condition, Equipment.Condition.INSPECTION)
        self.assertEqual(second.unit, "個")
        self.assertEqual(first.created_by, self.staff)
        self.assertTrue(
            EquipmentHistory.objects.filter(equipment=first, field_name="登録").exists()
        )

    def test_import_accepts_shift_jis(self):
        response = self._upload("備品名,分類,保有数量\nテープ,A,2\n", encoding="cp932")
        self.assertContains(response, "1件の備品を登録しました")

    def test_import_is_all_or_nothing_and_reports_row_numbers(self):
        csv_text = (
            "備品名,分類,保有数量,保管場所\n"
            "正常な行,A,1,\n"
            "分類なし,ZZ,1,\n"
            "場所なし,A,1,倉庫\n"
            "数量ゼロ,A,0,\n"
        )
        response = self._upload(csv_text)

        self.assertContains(response, "3行目: 分類「ZZ」が見つかりません")
        self.assertContains(response, "4行目: 保管場所「倉庫」が見つかりません")
        self.assertContains(response, "5行目: 保有数量は1以上")
        self.assertFalse(Equipment.objects.exists())

    def test_import_rejects_unknown_manager_position(self):
        response = self._upload("備品名,分類,保有数量,管理担当役職\nテープ,A,1,存在しない役職\n")
        self.assertContains(response, "管理担当役職「存在しない役職」が役職に見つかりません")
        self.assertFalse(Equipment.objects.exists())

    def test_detail_shows_position_and_current_holders(self):
        item = Equipment.objects.create(
            category=self.category, name="表示確認", quantity=1, manager=self.manager
        )
        self.client.force_login(self.member)
        response = self.client.get(reverse("equipment:detail", args=[item.pk]))
        self.assertContains(response, "機材班長（班長の人）")

    def test_import_requires_columns(self):
        response = self._upload("備品名,メーカー\nマイク,SONY\n")
        self.assertContains(response, "CSVに次の列が必要です")
        self.assertFalse(Equipment.objects.exists())

    def test_import_ignores_reference_columns_and_never_updates(self):
        existing = Equipment.objects.create(
            category=self.category, inventory_number="A-26000001", name="既存", quantity=1
        )
        csv_text = "備品番号,備品名,分類,保有数量,利用状況\nA-26000001,既存を上書きしたい,A,9,保管中\n"
        with patch("equipment.numbering.timezone.localdate", return_value=date(2026, 10, 23)):
            self._upload(csv_text)

        existing.refresh_from_db()
        self.assertEqual(existing.name, "既存")
        created = Equipment.objects.get(model__name="既存を上書きしたい")
        self.assertEqual(created.inventory_number, "A-26000002")

    def test_import_is_staff_only(self):
        self.client.force_login(self.member)
        self.assertEqual(self.client.get(reverse("equipment:import")).status_code, 302)
        response = self._upload("備品名,分類,保有数量\nテープ,A,2\n", user=self.member)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Equipment.objects.exists())

    def test_export_can_be_imported_again(self):
        manufacturer = Manufacturer.objects.create(name="Shure")
        Equipment.objects.create(
            category=self.category,
            name="往復テスト",
            manufacturer=manufacturer,
            quantity=3,
            unit="本",
            manager=self.manager,
            location=self.location,
            purchased_on=date(2026, 5, 1),
            purchase_price=5000,
            purchase_currency=Equipment.Currency.JPY,
            condition=Equipment.Condition.REPAIR,
            notes="メモ, カンマ入り",
        )
        self.client.force_login(self.member)
        exported = self.client.get(reverse("equipment:list"), {"export": "csv"})
        text = exported.content.decode("utf-8-sig")
        self.assertTrue(text.startswith("備品番号,備品名,分類,メーカー"))

        response = self._upload(text)
        self.assertContains(response, "1件の備品を登録しました")
        copy = Equipment.objects.exclude(
            pk=Equipment.objects.order_by("pk").first().pk
        ).get()
        self.assertEqual(copy.name, "往復テスト")
        self.assertEqual(copy.manufacturer, manufacturer)
        self.assertEqual(copy.manager, self.manager)
        self.assertEqual(copy.location, self.location)
        self.assertEqual(copy.purchase_price, 5000)
        self.assertEqual(copy.condition, Equipment.Condition.REPAIR)
        self.assertEqual(copy.notes, "メモ, カンマ入り")


class EquipmentInfoButtonTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="info-user", password="pw-123456", is_staff=True
        )
        self.client.force_login(self.user)
        self.item = Equipment.objects.create(
            category=Category.objects.get(code="A"),
            inventory_number="A-26000001",
            name="説明確認",
            quantity=2,
        )
        self.usage = make_usage(
            equipment=self.item,
            usage_type=Loan.UsageType.LENDING,
            destination="放送室",
            quantity=1,
        )

    def test_every_field_of_every_form_has_an_explanation(self):
        from .forms import (
            EquipmentForm,
            EquipmentImportForm,
            QRDesignForm,
            ReturnRecordForm,
            StorageLocationForm,
            LoanForm,
        )

        for form_class in (
            EquipmentForm,
            EquipmentImportForm,
            QRDesignForm,
            ReturnRecordForm,
            StorageLocationForm,
            LoanForm,
        ):
            form = form_class()
            for name, field in form.fields.items():
                with self.subTest(form=form_class.__name__, field=name):
                    self.assertTrue(field.info_text)

    def test_forms_render_toggle_button_and_hidden_note(self):
        pages = [
            (reverse("equipment:register"), "備品の種類による分類です"),
            (reverse("equipment:lending_register"), "他の人や団体に貸して、相手が使う場合"),
            (reverse("equipment:return", args=[self.usage.pk]), "今回返却する個数です"),
            (reverse("equipment:location_register"), "保管場所の名前です"),
            (reverse("equipment:settings"), "QRコードの色です"),
            (reverse("equipment:import"), "CSVダウンロード"),
        ]
        for url, text in pages:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'class="equipment__info-button"')
                self.assertContains(response, 'aria-expanded="false"')
                self.assertContains(response, text)
                self.assertContains(response, "equipment/info.js")

    def test_lending_explains_difference_between_lending_and_carry_out(self):
        response = self.client.get(reverse("equipment:lending_register"))
        self.assertContains(response, "貸出：")
        self.assertContains(response, "持出：")


class EquipmentEventTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="event-user", password="pw-123456", is_staff=True
        )
        self.client.force_login(self.user)
        self.item = Equipment.objects.create(
            category=Category.objects.get(code="A"),
            inventory_number="A-26000001",
            name="履歴確認",
            quantity=2,
        )

    def test_record_event_stores_kind_and_defaults_field_name_to_label(self):
        from .events import Kind, record_event

        event = record_event(self.item, Kind.STATUS, self.user, old_value="正常", new_value="故障")
        self.assertEqual(event.kind, "status")
        self.assertEqual(event.field_name, "状態変更")
        self.assertEqual((event.old_value, event.new_value), ("正常", "故障"))

    def test_record_event_rejects_unknown_kind(self):
        from .events import record_event

        with self.assertRaises(ValueError):
            record_event(self.item, "nonsense", self.user)

    def test_workflow_records_one_kind_per_action(self):
        self.client.post(
            reverse("equipment:unregister", args=[self.item.pk]), {"reason": "不要"}
        )
        self.client.post(reverse("equipment:reactivate", args=[self.item.pk]))
        kinds = list(
            EquipmentHistory.objects.filter(equipment=self.item)
            .order_by("pk")
            .values_list("kind", flat=True)
        )
        self.assertEqual(kinds, ["unregister", "reactivate"])

    def test_condition_change_is_a_status_event_and_other_changes_are_updates(self):
        payload = {
            "category": self.item.category.pk,
            "name": "履歴確認2",
            "quantity": "2",
            "unit": "個",
            "purchase_currency": Equipment.Currency.JPY,
            "condition": Equipment.Condition.BROKEN,
        }
        self.client.post(reverse("equipment:edit", args=[self.item.pk]), payload)
        by_field = dict(
            EquipmentHistory.objects.filter(equipment=self.item).values_list(
                "field_name", "kind"
            )
        )
        self.assertEqual(by_field["備品の状態"], "status")
        self.assertEqual(by_field["備品名"], "update")

    def test_history_cannot_be_added_or_edited_in_admin(self):
        from django.contrib import admin

        model_admin = admin.site._registry[EquipmentHistory]
        request = type("R", (), {"user": self.user})()
        self.assertFalse(model_admin.has_add_permission(request))
        self.assertFalse(model_admin.has_change_permission(request))

    def test_legacy_history_rows_are_converted_by_field_name(self):
        import importlib

        migration = importlib.import_module("equipment.migrations.0014_history_kind")
        convert = migration.kind_for_legacy_entry
        self.assertEqual(convert("登録", ""), "register")
        self.assertEqual(convert("貸出・持出", ""), "loan")
        self.assertEqual(convert("返却", ""), "return")
        self.assertEqual(convert("備品の状態", "故障"), "status")
        self.assertEqual(convert("登録状態", "登録解除"), "unregister")
        self.assertEqual(convert("登録状態", "管理中"), "reactivate")
        self.assertEqual(convert("備品名", ""), "update")


class EquipmentModelSplitTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="model-user", password="pw-123456", is_staff=True
        )
        self.client.force_login(self.user)
        self.category = Category.objects.get(code="A")
        self.maker = Manufacturer.objects.create(name="Shure")

    def _create(self, **overrides):
        values = dict(
            category=self.category,
            name="ワイヤレスマイク",
            manufacturer=self.maker,
            model_number="SM58",
            unit="本",
            quantity=1,
        )
        values.update(overrides)
        return Equipment.objects.create(**values)

    def _payload(self, item, **overrides):
        payload = {
            "category": item.model.category_id,
            "name": item.model.name,
            "manufacturer": item.model.manufacturer_id or "",
            "model_number": item.model.model_number,
            "unit": item.model.unit,
            "quantity": str(item.quantity),
            "purchase_currency": Equipment.Currency.JPY,
            "condition": item.condition,
        }
        payload.update(overrides)
        return payload

    def test_items_with_same_attributes_share_one_model(self):
        first = self._create()
        second = self._create()
        self.assertEqual(first.model_id, second.model_id)
        self.assertEqual(EquipmentModel.objects.count(), 1)
        self.assertNotEqual(first.inventory_number, second.inventory_number)

    def test_item_exposes_model_attributes(self):
        item = self._create()
        self.assertEqual(item.name, "ワイヤレスマイク")
        self.assertEqual(item.unit, "本")
        self.assertEqual(item.manufacturer, self.maker)
        self.assertEqual(item.category, self.category)
        self.assertEqual(item.model_number, "SM58")

    def test_registering_twice_reuses_the_model(self):
        for _ in range(2):
            self.client.post(
                reverse("equipment:register"),
                {
                    "category": self.category.pk,
                    "name": "ワイヤレスマイク",
                    "manufacturer": self.maker.pk,
                    "model_number": "SM58",
                    "unit": "本",
                    "quantity": "1",
                    "purchase_currency": Equipment.Currency.JPY,
                    "condition": Equipment.Condition.NORMAL,
                },
            )
        self.assertEqual(Equipment.objects.count(), 2)
        self.assertEqual(EquipmentModel.objects.count(), 1)

    def test_editing_one_item_does_not_change_its_siblings(self):
        first = self._create()
        second = self._create()
        self.client.post(
            reverse("equipment:edit", args=[first.pk]),
            self._payload(first, name="名前を変えた1本"),
        )
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertEqual(first.name, "名前を変えた1本")
        self.assertEqual(second.name, "ワイヤレスマイク")
        self.assertNotEqual(first.model_id, second.model_id)
        self.assertEqual(EquipmentModel.objects.count(), 2)

    def test_renaming_the_only_item_removes_the_unused_model(self):
        item = self._create()
        self.client.post(
            reverse("equipment:edit", args=[item.pk]),
            self._payload(item, name="改名後"),
        )
        item.refresh_from_db()
        self.assertEqual(item.name, "改名後")
        self.assertEqual(EquipmentModel.objects.count(), 1)

    def test_renaming_keeps_the_photo(self):
        item = self._create()
        item.model.image = "equipment/photo.png"
        item.model.save()
        self.client.post(
            reverse("equipment:edit", args=[item.pk]),
            self._payload(item, name="写真つき改名", image=""),
        )
        item.refresh_from_db()
        self.assertEqual(item.model.name, "写真つき改名")
        self.assertEqual(item.model.image.name, "equipment/photo.png")

    def test_search_and_filter_use_model_attributes(self):
        self._create()
        self._create(name="ミキサー", manufacturer=None, model_number="MX1")
        response = self.client.get(reverse("equipment:list"), {"q": "SM58"})
        self.assertContains(response, "ワイヤレスマイク")
        self.assertNotContains(response, "ミキサー")
        response = self.client.get(reverse("equipment:list"), {"q": "Shure"})
        self.assertContains(response, "ワイヤレスマイク")
        response = self.client.get(
            reverse("equipment:list"), {"category": self.category.pk}
        )
        self.assertContains(response, "ミキサー")

    def test_category_count_includes_items_across_models(self):
        self._create()
        self._create(name="ミキサー", model_number="MX1")
        response = self.client.get(reverse("equipment:categories"))
        counts = {c.code: c.equipment_count for c in response.context["categories"]}
        self.assertEqual(counts["A"], 2)


class StatusAndReturnTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="status-user", password="pw-123456", is_staff=True
        )
        self.client.force_login(self.user)
        self.category = Category.objects.get(code="A")

    def _item(self, quantity=1, **kwargs):
        return Equipment.objects.create(
            category=self.category,
            name=kwargs.pop("name", "マイク"),
            quantity=quantity,
            unit="本",
            **kwargs,
        )

    def _loan(self, item, quantity):
        return make_usage(
            equipment=item,
            usage_type=Loan.UsageType.LENDING,
            destination="放送室",
            quantity=quantity,
            created_by=self.user,
        )

    def _return(self, line, quantity, condition="normal", details=""):
        return self.client.post(
            reverse("equipment:return", args=[line.pk]),
            {
                "quantity": str(quantity),
                "returned_at": "2026-10-02T10:00",
                "confirmed_by": "確認者",
                "condition": condition,
                "condition_details": details,
                "notes": "",
            },
        )

    # --- status transitions
    def test_change_status_follows_the_transition_table(self):
        from .services import change_status

        item = self._item()
        change_status(item, Equipment.Condition.BROKEN, self.user)
        item.refresh_from_db()
        self.assertEqual(item.condition, "broken")
        with self.assertRaises(ValidationError):
            change_status(item, Equipment.Condition.NORMAL, self.user)
        change_status(item, Equipment.Condition.REPAIR, self.user)
        change_status(item, Equipment.Condition.NORMAL, self.user)
        item.refresh_from_db()
        self.assertEqual(item.condition, "normal")

    def test_change_status_records_a_status_event_and_can_be_forced(self):
        from .services import change_status

        item = self._item()
        change_status(item, Equipment.Condition.INSPECTION, self.user, reason="定期点検")
        event = EquipmentHistory.objects.get(equipment=item, kind="status")
        self.assertEqual((event.old_value, event.new_value), ("正常", "要点検"))
        self.assertEqual(event.reason, "定期点検")
        change_status(item, Equipment.Condition.LOST, self.user, force=True)
        item.refresh_from_db()
        self.assertEqual(item.condition, "lost")
        self.assertFalse(change_status(item, Equipment.Condition.LOST, self.user))

    def test_edit_form_only_offers_allowed_statuses(self):
        item = self._item()
        item.condition = Equipment.Condition.BROKEN
        item.save()
        response = self.client.get(reverse("equipment:edit", args=[item.pk]))
        form = response.context["form"]
        self.assertEqual(
            {value for value, _ in form.fields["condition"].choices},
            {"broken", "repair"},
        )

    def test_edit_rejects_a_status_that_is_not_allowed(self):
        item = self._item()
        item.condition = Equipment.Condition.BROKEN
        item.save()
        payload = {
            "category": self.category.pk,
            "name": "マイク",
            "quantity": "1",
            "unit": "本",
            "purchase_currency": "JPY",
            "condition": Equipment.Condition.NORMAL,
        }
        response = self.client.post(reverse("equipment:edit", args=[item.pk]), payload)
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.condition, "broken")

    def test_edit_applies_an_allowed_status_through_change_status(self):
        item = self._item()
        payload = {
            "category": self.category.pk,
            "name": "マイク",
            "quantity": "1",
            "unit": "本",
            "purchase_currency": "JPY",
            "condition": Equipment.Condition.DISABLED,
        }
        self.client.post(reverse("equipment:edit", args=[item.pk]), payload)
        item.refresh_from_db()
        self.assertEqual(item.condition, "disabled")
        event = EquipmentHistory.objects.get(equipment=item, kind="status")
        self.assertEqual(event.new_value, "使用停止")

    # --- returns
    def test_returning_everything_faulty_makes_the_item_broken(self):
        item = self._item(quantity=2)
        line = self._loan(item, 2)
        self._return(line, 2, "faulty", "断線")
        item.refresh_from_db()
        self.assertEqual(item.condition, "broken")
        self.assertEqual(item.available_quantity, 0)
        self.assertEqual(Equipment.objects.count(), 1)

    def test_partial_faulty_return_splits_those_units_into_their_own_item(self):
        item = self._item(quantity=5)
        line = self._loan(item, 3)
        self._return(line, 3, "faulty", "1本が断線")  # all three came back faulty
        item.refresh_from_db()
        # Only 3 of 5 units are faulty: they get their own item.
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.condition, "normal")
        broken = Equipment.objects.exclude(pk=item.pk).get()
        self.assertEqual((broken.quantity, broken.condition), (3, "broken"))
        self.assertEqual(broken.model_id, item.model_id)
        self.assertNotEqual(broken.inventory_number, item.inventory_number)
        self.assertTrue(
            EquipmentHistory.objects.filter(
                equipment=broken, kind="register", reason__contains=item.inventory_number
            ).exists()
        )
        self.assertEqual(item.available_quantity, 2)

    def test_missing_return_marks_units_lost_and_lost_can_be_found_again(self):
        from .services import change_status

        item = self._item(quantity=1)
        line = self._loan(item, 1)
        self._return(line, 1, "missing")
        item.refresh_from_db()
        self.assertEqual(item.condition, "lost")
        change_status(item, Equipment.Condition.NORMAL, self.user)
        item.refresh_from_db()
        self.assertEqual(item.available_quantity, 1)

    def test_return_for_inspection_keeps_the_item_lendable(self):
        item = self._item(quantity=1)
        line = self._loan(item, 1)
        self._return(line, 1, "inspection")
        item.refresh_from_db()
        self.assertEqual(item.condition, "inspection")
        self.assertEqual(item.available_quantity, 1)

    def test_normal_return_changes_nothing_and_events_link_to_the_line(self):
        item = self._item(quantity=2)
        line = self._loan(item, 2)
        self._return(line, 1)
        item.refresh_from_db()
        self.assertEqual(item.condition, "normal")
        self.assertEqual(item.available_quantity, 1)
        event = EquipmentHistory.objects.get(equipment=item, kind="return")
        self.assertEqual(event.loan_line, line)

    def test_return_above_remaining_quantity_is_rejected(self):
        item = self._item(quantity=2)
        line = self._loan(item, 1)
        response = self._return(line, 2)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "返却可能数量を超えています")
        self.assertFalse(ReturnRecord.objects.exists())

    def test_return_form_does_not_offer_the_legacy_damaged_choice(self):
        item = self._item()
        line = self._loan(item, 1)
        response = self.client.get(reverse("equipment:return", args=[line.pk]))
        values = {v for v, _ in response.context["form"].fields["condition"].choices}
        self.assertEqual(values, {"normal", "inspection", "faulty", "missing"})

    # --- loans
    def test_create_loan_with_several_items_records_one_event_per_item(self):
        from .services import create_loan

        first, second = self._item(), self._item(name="ミキサー")
        loan = create_loan(
            self.user,
            [(first.pk, 1), (second.pk, 1)],
            usage_type=Loan.UsageType.CARRY_OUT,
            destination="体育館",
        )
        self.assertEqual(loan.lines.count(), 2)
        for item in (first, second):
            event = EquipmentHistory.objects.get(equipment=item, kind="loan")
            self.assertEqual(event.loan_line.loan, loan)

    def test_create_loan_rejects_unlendable_duplicate_or_excess(self):
        from .services import LoanError, create_loan

        broken = self._item()
        broken.condition = Equipment.Condition.BROKEN
        broken.save()
        ok = self._item(name="別のマイク", quantity=2)
        fields = {"usage_type": Loan.UsageType.LENDING, "destination": "x"}
        with self.assertRaises(LoanError):
            create_loan(self.user, [(broken.pk, 1)], **fields)
        with self.assertRaises(LoanError):
            create_loan(self.user, [(ok.pk, 1), (ok.pk, 1)], **fields)
        with self.assertRaises(LoanError):
            create_loan(self.user, [(ok.pk, 3)], **fields)
        self.assertFalse(Loan.objects.exists())

    def test_deleting_an_item_removes_loans_left_without_lines(self):
        item = self._item()
        line = self._loan(item, 1)
        loan_id = line.loan_id
        item.delete()
        self.assertFalse(Loan.objects.filter(pk=loan_id).exists())
