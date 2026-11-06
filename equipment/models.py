from datetime import date
import re
import secrets
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.db.models import Sum
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone

from .numbering import generate_inventory_number


class Category(models.Model):
    code = models.CharField(
        "分類記号",
        max_length=1,
        unique=True,
        validators=[
            RegexValidator(
                regex=r"^[A-Z]$",
                message="分類記号はA〜Zの大文字1文字で指定してください。",
            )
        ],
    )
    name = models.CharField("分類名", max_length=100)
    english_name = models.CharField("英語名", max_length=100)
    examples = models.TextField("主な対象", blank=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "備品分類"
        verbose_name_plural = "備品分類"

    def __str__(self):
        return f"{self.code}：{self.name}"


class StorageLocation(models.Model):
    name = models.CharField("保管場所名", max_length=100)
    code = models.CharField("場所コード", max_length=30, blank=True)
    parent = models.ForeignKey(
        "self",
        verbose_name="上位保管場所",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )
    description = models.TextField("詳細", blank=True)
    notes = models.TextField("備考", blank=True)
    is_active = models.BooleanField("使用中", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "保管場所"
        verbose_name_plural = "保管場所"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "name"],
                name="equipment_unique_sibling_location",
            )
        ]

    def __str__(self):
        if self.parent_id:
            return f"{self.parent} / {self.name}"
        return self.name


class Manufacturer(models.Model):
    name = models.CharField("メーカー名", max_length=100, unique=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "メーカー"
        verbose_name_plural = "メーカー"

    def __str__(self):
        return self.name


class EquipmentModelManager(models.Manager):
    def resolve(self, category, name, manufacturer=None, model_number="", unit="個"):
        """Return the model (機種) with these attributes, creating it if needed."""
        model = self.filter(
            category=category,
            name=name,
            manufacturer=manufacturer,
            model_number=model_number,
            unit=unit,
        ).first()
        if model is None:
            model = self.create(
                category=category,
                name=name,
                manufacturer=manufacturer,
                model_number=model_number,
                unit=unit,
            )
        return model


class EquipmentModel(models.Model):
    """機種: what is shared by every unit of the same kind of equipment."""

    category = models.ForeignKey(
        Category,
        verbose_name="分類",
        on_delete=models.PROTECT,
        related_name="equipment_models",
    )
    name = models.CharField("備品名", max_length=200)
    manufacturer = models.ForeignKey(
        Manufacturer,
        verbose_name="メーカー",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="equipment_models",
    )
    model_number = models.CharField("型番", max_length=100, blank=True)
    unit = models.CharField("単位", max_length=20, default="個")
    image = models.ImageField("画像", upload_to="equipment/", blank=True)

    objects = EquipmentModelManager()

    class Meta:
        ordering = ["name"]
        verbose_name = "機種"
        verbose_name_plural = "機種"
        indexes = [models.Index(fields=["name"])]

    def __str__(self):
        return self.name


MODEL_FIELDS = ("category", "name", "manufacturer", "model_number", "unit", "image")


class EquipmentManager(models.Manager):
    def create(self, **kwargs):
        """Accept the 機種 fields directly and resolve the model for the caller."""
        if "model" not in kwargs and any(key in kwargs for key in MODEL_FIELDS):
            image = kwargs.pop("image", "")
            model = EquipmentModel.objects.resolve(
                category=kwargs.pop("category"),
                name=kwargs.pop("name"),
                manufacturer=kwargs.pop("manufacturer", None),
                model_number=kwargs.pop("model_number", ""),
                unit=kwargs.pop("unit", "個"),
            )
            if image and not model.image:
                model.image = image
                model.save(update_fields=["image"])
            kwargs["model"] = model
        return super().create(**kwargs)


class Equipment(models.Model):
    """個体(備品): one physical item, or one counted lot of identical items."""

    class Condition(models.TextChoices):
        NORMAL = "normal", "正常"
        INSPECTION = "inspection", "要点検"
        REPAIR = "repair", "修理中"
        BROKEN = "broken", "故障"
        DISABLED = "disabled", "使用停止"
        LOST = "lost", "紛失"

    # Only these can be lent. 修理中・故障・使用停止・紛失 cannot.
    LOANABLE_CONDITIONS = frozenset({"normal", "inspection"})

    class Currency(models.TextChoices):
        JPY = "JPY", "円"
        USD = "USD", "米ドル"
        EUR = "EUR", "ユーロ"

    inventory_number = models.CharField(
        "備品番号", max_length=20, unique=True, blank=True
    )
    qr_inventory_number = models.CharField(
        "QRコード用備品番号",
        max_length=20,
        unique=True,
        default="",
        editable=False,
    )
    qr_token = models.CharField(
        "QRコードID",
        max_length=20,
        unique=True,
        default="",
        editable=False,
    )
    model = models.ForeignKey(
        EquipmentModel,
        verbose_name="機種",
        on_delete=models.PROTECT,
        related_name="items",
    )
    serial_number = models.CharField("製造番号", max_length=100, blank=True)
    receipt_number = models.CharField("レシート番号", max_length=100, blank=True)
    quantity = models.PositiveIntegerField(
        "保有数量", validators=[MinValueValidator(1)]
    )
    manager = models.ForeignKey(
        "roll.Position",
        verbose_name="管理担当役職",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="managed_equipment",
    )
    location = models.ForeignKey(
        StorageLocation,
        verbose_name="保管場所",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment",
    )
    purchased_on = models.DateField("購入日", null=True, blank=True)
    purchase_price = models.DecimalField(
        "購入価格",
        max_digits=12,
        decimal_places=0,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)],
    )
    purchase_currency = models.CharField(
        "通貨",
        max_length=3,
        choices=Currency.choices,
        default=Currency.JPY,
    )
    purchase_vendor = models.CharField("購入先", max_length=200, blank=True)
    warranty_expiry = models.DateField("保証期限", null=True, blank=True)
    expected_lifespan_years = models.PositiveSmallIntegerField(
        "法定耐用年数", null=True, blank=True
    )
    notes = models.TextField("備考", blank=True)
    condition = models.CharField(
        "備品の状態",
        max_length=12,
        choices=Condition.choices,
        default=Condition.NORMAL,
    )
    is_active = models.BooleanField("管理中", default=True)
    unregistered_at = models.DateTimeField("登録解除日時", null=True, blank=True)
    unregistered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="登録解除者",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="unregistered_equipment",
    )
    unregistration_reason = models.TextField("登録解除理由", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="登録者",
        on_delete=models.SET_NULL,
        null=True,
        related_name="registered_equipment",
    )
    last_modified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="最終更新者",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_equipment",
    )
    created_at = models.DateTimeField("登録日時", auto_now_add=True)
    updated_at = models.DateTimeField("最終更新日時", auto_now=True)

    class Meta:
        ordering = ["inventory_number"]
        verbose_name = "備品"
        verbose_name_plural = "備品"
        indexes = [
            models.Index(fields=["model", "is_active"]),
            models.Index(fields=["serial_number"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="equipment_quantity_at_least_one",
            )
        ]

    objects = EquipmentManager()

    # Shared attributes live on the 機種; expose them so callers (and
    # templates) can keep reading equipment.name, equipment.unit, ...
    @property
    def category(self):
        return self.model.category

    @property
    def name(self):
        return self.model.name

    @property
    def manufacturer(self):
        return self.model.manufacturer

    @property
    def model_number(self):
        return self.model.model_number

    @property
    def unit(self):
        return self.model.unit

    @property
    def image(self):
        return self.model.image

    def __str__(self):
        return f"{self.inventory_number} {self.name}"

    def _lines(self):
        # Uses the prefetch cache when the caller prefetched "loan_lines__returns".
        return list(self.loan_lines.all())

    @property
    def outstanding_quantity(self):
        """Units currently out: lent minus returned, summed over open lines."""
        return sum(line.remaining_quantity for line in self._lines())

    @property
    def stored_quantity(self):
        return max(self.quantity - self.outstanding_quantity, 0)

    @property
    def available_quantity(self):
        if self.condition not in self.LOANABLE_CONDITIONS:
            return 0
        return self.stored_quantity

    @property
    def usage_status(self):
        current = [line for line in self._lines() if line.remaining_quantity]
        if not current:
            return "保管中" if self.stored_quantity else "在庫なし"
        if (
            self.stored_quantity == 0
            and len({line.usage_type for line in current}) == 1
        ):
            return current[0].get_usage_type_display()
        return "一部貸出・持出中"

    @property
    def expected_end_date(self):
        if self.purchased_on is None or self.expected_lifespan_years is None:
            return None
        try:
            return self.purchased_on.replace(
                year=self.purchased_on.year + self.expected_lifespan_years
            )
        except ValueError:
            return date(
                self.purchased_on.year + self.expected_lifespan_years,
                2,
                28,
            )

    @property
    def manager_members(self):
        """Roster people currently holding the managing position."""
        if self.manager_id is None:
            return []
        return list(self.manager.members.order_by("name"))

    def assign_identifiers(self):
        if not self.inventory_number:
            if not self.model_id:
                raise ValidationError("機種を指定してから備品番号を付番してください。")
            self.inventory_number = generate_inventory_number(
                self.model.category.code
            )
        if not self.qr_token:
            alphabet = string.ascii_letters + string.digits
            self.qr_token = "".join(secrets.choice(alphabet) for _ in range(12))
        if not self.qr_inventory_number:
            self.qr_inventory_number = self.inventory_number

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._original_model_id = instance.model_id
        return instance

    def save(self, *args, **kwargs):
        self.assign_identifiers()
        super().save(*args, **kwargs)
        # Moving to another 機種 may leave the old one without any item.
        original = getattr(self, "_original_model_id", None)
        if original and original != self.model_id:
            EquipmentModel.objects.filter(pk=original, items__isnull=True).delete()
        self._original_model_id = self.model_id


class Loan(models.Model):
    """One lending/carry-out operation: who, where to, when. Items are in lines."""

    class UsageType(models.TextChoices):
        LENDING = "lending", "貸出中"
        CARRY_OUT = "carry_out", "持出中"

    usage_type = models.CharField("区分", max_length=12, choices=UsageType.choices)
    destination = models.CharField(
        "貸出・持出先",
        max_length=200,
        help_text="貸出時点の表示名のスナップショット。名簿の変更後も記録として残す。",
    )
    destination_entry = models.ForeignKey(
        "roll.RosterEntry",
        verbose_name="名簿上の貸出・持出先",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="equipment_loans",
    )
    responsible_person = models.ForeignKey(
        "roll.RosterEntry",
        verbose_name="責任者",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="responsible_loans",
    )
    recipient = models.CharField("受取担当者", max_length=100, blank=True)
    started_at = models.DateTimeField("開始日時", default=timezone.now)
    due_at = models.DateTimeField("返却予定日時", null=True, blank=True)
    purpose = models.CharField("用途", max_length=250, blank=True)
    notes = models.TextField("備考", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="登録者",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_equipment_loans",
    )
    created_at = models.DateTimeField("登録日時", auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-pk"]
        verbose_name = "貸出・持出"
        verbose_name_plural = "貸出・持出"

    def __str__(self):
        return f"{self.get_usage_type_display()} {self.destination}"

    @property
    def remaining_quantity(self):
        return sum(line.remaining_quantity for line in self.lines.all())

    @property
    def is_overdue(self):
        return bool(
            self.remaining_quantity and self.due_at and self.due_at < timezone.now()
        )

    @property
    def status(self):
        lines = list(self.lines.all())
        if not any(line.remaining_quantity for line in lines):
            return "返却済み"
        if self.is_overdue:
            return "期限超過"
        if any(line.returned_quantity for line in lines):
            return "一部返却"
        return self.get_usage_type_display()


class LoanLine(models.Model):
    """An item (and how many of it) that is part of a loan."""

    loan = models.ForeignKey(Loan, on_delete=models.CASCADE, related_name="lines")
    equipment = models.ForeignKey(
        Equipment, on_delete=models.CASCADE, related_name="loan_lines"
    )
    quantity = models.PositiveIntegerField(
        "数量", validators=[MinValueValidator(1)]
    )

    class Meta:
        ordering = ["-loan__started_at", "-loan_id", "-pk"]
        verbose_name = "貸出明細"
        verbose_name_plural = "貸出明細"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="equipment_loanline_quantity_at_least_one",
            ),
        ]

    def __str__(self):
        return f"{self.equipment} - {self.loan.destination}"

    def get_usage_type_display(self):
        return self.loan.get_usage_type_display()

    @property
    def returned_quantity(self):
        return sum(record.quantity for record in self.returns.all())

    @property
    def remaining_quantity(self):
        return max(self.quantity - self.returned_quantity, 0)

    @property
    def is_overdue(self):
        return bool(
            self.remaining_quantity
            and self.loan.due_at
            and self.loan.due_at < timezone.now()
        )

    @property
    def status(self):
        if not self.remaining_quantity:
            return "返却済み"
        if self.is_overdue:
            return "期限超過"
        if self.returned_quantity:
            return "一部返却"
        return self.loan.get_usage_type_display()


LOAN_ATTRIBUTES = frozenset(
    {
        "usage_type",
        "destination",
        "destination_entry",
        "destination_entry_id",
        "responsible_person",
        "recipient",
        "started_at",
        "due_at",
        "purpose",
        "notes",
        "created_by",
        "created_at",
    }
)


def _loan_attribute(name):
    # Read straight from the header, so lists and templates can treat a line
    # like a lending record (line.destination, line.due_at, ...).
    return property(lambda self: getattr(self.loan, name))


for _name in LOAN_ATTRIBUTES:
    setattr(LoanLine, _name, _loan_attribute(_name))


@receiver(post_delete, sender=LoanLine)
def delete_loan_without_lines(sender, instance, **kwargs):
    """A loan whose last line is gone (e.g. its item was deleted) has no meaning."""
    Loan.objects.filter(pk=instance.loan_id, lines__isnull=True).delete()


class ReturnRecord(models.Model):
    class Condition(models.TextChoices):
        NORMAL = "normal", "問題なし"
        INSPECTION = "inspection", "要点検"
        FAULTY = "faulty", "故障"
        MISSING = "missing", "紛失"
        DAMAGED = "damaged", "破損"  # legacy; new returns use 故障

    line = models.ForeignKey(
        LoanLine, on_delete=models.CASCADE, related_name="returns"
    )
    quantity = models.PositiveIntegerField(
        "返却数量", validators=[MinValueValidator(1)]
    )
    returned_at = models.DateTimeField("実際の返却日時", default=timezone.now)
    confirmed_by = models.CharField("返却確認者", max_length=100, blank=True)
    condition = models.CharField(
        "返却時の状態", max_length=10, choices=Condition.choices, default=Condition.NORMAL
    )
    condition_details = models.TextField("故障・紛失の内容", blank=True)
    notes = models.TextField("備考", blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="処理者",
        on_delete=models.SET_NULL,
        null=True,
        related_name="processed_equipment_returns",
    )
    created_at = models.DateTimeField("処理日時", auto_now_add=True)

    class Meta:
        ordering = ["-returned_at", "-pk"]
        verbose_name = "返却記録"
        verbose_name_plural = "返却記録"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="equipment_return_quantity_at_least_one",
            ),
        ]

    def __str__(self):
        return f"{self.line.equipment} - {self.quantity}{self.line.equipment.unit}"


class EquipmentReminderDelivery(models.Model):
    subscription = models.ForeignKey(
        "accounts.WebPushSubscription",
        on_delete=models.CASCADE,
        related_name="equipment_reminders",
    )
    line = models.ForeignKey(
        LoanLine,
        on_delete=models.CASCADE,
        related_name="reminder_deliveries",
    )
    due_at_snapshot = models.DateTimeField()
    days_until_due = models.IntegerField()
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "subscription",
                    "line",
                    "due_at_snapshot",
                    "days_until_due",
                ],
                name="equipment_unique_reminder_delivery",
            ),
        ]
        verbose_name = "返却期限通知履歴"
        verbose_name_plural = "返却期限通知履歴"


class EquipmentHistory(models.Model):
    """Append-only log of everything that happens to an equipment record.

    Write through ``equipment.events.record_event`` only.
    """

    class Kind(models.TextChoices):
        REGISTER = "register", "登録"
        UPDATE = "update", "項目変更"
        LOAN = "loan", "貸出・持出"
        RETURN = "return", "返却"
        STATUS = "status", "状態変更"
        UNREGISTER = "unregister", "登録解除"
        REACTIVATE = "reactivate", "再有効化"
        IMPORT = "import", "CSV取り込み"

    equipment = models.ForeignKey(
        Equipment, on_delete=models.CASCADE, related_name="history"
    )
    kind = models.CharField(
        "種類", max_length=12, choices=Kind.choices, default=Kind.UPDATE
    )
    loan_line = models.ForeignKey(
        LoanLine,
        verbose_name="貸出明細",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    changed_at = models.DateTimeField("変更日時", auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="変更者",
        on_delete=models.SET_NULL,
        null=True,
        related_name="equipment_changes",
    )
    field_name = models.CharField("変更項目", max_length=100)
    old_value = models.TextField("変更前", blank=True)
    new_value = models.TextField("変更後", blank=True)
    reason = models.TextField("変更理由", blank=True)

    class Meta:
        ordering = ["-changed_at", "-pk"]
        indexes = [models.Index(fields=["kind", "changed_at"])]
        verbose_name = "備品変更履歴"
        verbose_name_plural = "備品変更履歴"

    def __str__(self):
        return f"{self.equipment} - {self.field_name}"


class QRDesign(models.Model):
    color_validator = RegexValidator(
        regex=r"^#[0-9a-fA-F]{6}$", message="色は #RRGGBB 形式で入力してください。"
    )
    foreground = models.CharField(
        "前景色",
        max_length=7,
        default="#000000",
        validators=[color_validator],
    )
    background = models.CharField(
        "背景色",
        max_length=7,
        default="#ffffff",
        validators=[color_validator],
    )
    box_size = models.PositiveSmallIntegerField("出力サイズ", default=10)
    border = models.PositiveSmallIntegerField("余白", default=4)

    class Meta:
        verbose_name = "QRコード設定"
        verbose_name_plural = "QRコード設定"

    def __str__(self):
        return "QRコード共通設定"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        return cls.objects.first() or cls()
