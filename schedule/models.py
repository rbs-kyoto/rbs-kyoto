from datetime import timedelta

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Event(models.Model):
    class Recurrence(models.TextChoices):
        NONE = "none", "繰り返さない"
        DAILY = "daily", "毎日"
        WEEKLY = "weekly", "毎週"
        MONTHLY = "monthly", "毎月"

    title = models.CharField("タイトル", max_length=200)
    start = models.DateTimeField("開始")
    end = models.DateTimeField("終了", null=True, blank=True)
    all_day = models.BooleanField("終日", default=False)
    place = models.ForeignKey(
        "places.Place",
        verbose_name="場所",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="schedule_events",
    )
    description = models.TextField("メモ", blank=True)
    recurrence = models.CharField(
        "繰り返し",
        max_length=10,
        choices=Recurrence.choices,
        default=Recurrence.NONE,
    )
    recurrence_until = models.DateField("繰り返しの終了日", null=True, blank=True)
    ask_attendance = models.BooleanField("出欠を取る", default=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="作成者",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ["start"]
        verbose_name = "予定"
        verbose_name_plural = "予定"

    def __str__(self):
        return self.title

    @property
    def duration(self):
        if self.end and self.end > self.start:
            return self.end - self.start
        return timedelta(0)


class Assignment(models.Model):
    """予定に割り当てた部員(繰り返し予定では、全回に共通)。"""

    event = models.ForeignKey(
        Event,
        verbose_name="予定",
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    member = models.ForeignKey(
        "roll.RosterEntry",
        verbose_name="部員",
        on_delete=models.CASCADE,
        related_name="schedule_assignments",
        limit_choices_to={"is_member": True},
    )
    role = models.CharField("役割", max_length=100, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "割当部員"
        verbose_name_plural = "割当部員"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "member"], name="schedule_assignment_unique_member"
            ),
        ]

    def __str__(self):
        return f"{self.event} - {self.member.name}"


class Attendance(models.Model):
    """割り当てられた部員の出欠。繰り返し予定は日付ごとに回答する。"""

    class Status(models.TextChoices):
        ATTEND = "attend", "出席"
        ABSENT = "absent", "欠席"
        UNDECIDED = "undecided", "未定"

    assignment = models.ForeignKey(
        Assignment,
        verbose_name="割当",
        on_delete=models.CASCADE,
        related_name="attendances",
    )
    date = models.DateField("対象日")
    status = models.CharField("出欠", max_length=10, choices=Status.choices)
    comment = models.CharField("コメント", max_length=200, blank=True)
    responded_at = models.DateTimeField("回答日時", auto_now=True)

    class Meta:
        ordering = ["date", "assignment_id"]
        verbose_name = "出欠"
        verbose_name_plural = "出欠"
        constraints = [
            models.UniqueConstraint(
                fields=["assignment", "date"], name="schedule_attendance_unique_per_date"
            ),
        ]

    def __str__(self):
        return f"{self.assignment} {self.date} {self.get_status_display()}"


class EventEquipment(models.Model):
    """予定で使う機材と数量(繰り返し予定では、全回に共通)。"""

    event = models.ForeignKey(
        Event,
        verbose_name="予定",
        on_delete=models.CASCADE,
        related_name="equipment_items",
    )
    equipment = models.ForeignKey(
        "equipment.Equipment",
        verbose_name="機材",
        on_delete=models.CASCADE,
        related_name="schedule_items",
    )
    quantity = models.PositiveIntegerField(
        "数量", default=1, validators=[MinValueValidator(1)]
    )

    class Meta:
        ordering = ["id"]
        verbose_name = "使用機材"
        verbose_name_plural = "使用機材"
        constraints = [
            models.UniqueConstraint(
                fields=["event", "equipment"], name="schedule_event_equipment_unique"
            ),
        ]

    def __str__(self):
        return f"{self.event} - {self.equipment.name} x{self.quantity}"


class UsageLink(models.Model):
    """予定の機材と、機材アプリの貸出・持出記録(その回の分)を結ぶ。"""

    item = models.ForeignKey(
        EventEquipment,
        verbose_name="使用機材",
        on_delete=models.CASCADE,
        related_name="usage_links",
    )
    date = models.DateField("対象日")
    usage = models.OneToOneField(
        "equipment.LoanLine",
        verbose_name="貸出・持出記録(明細)",
        on_delete=models.CASCADE,
        related_name="schedule_link",
    )

    class Meta:
        ordering = ["date", "id"]
        verbose_name = "貸出記録の紐付け"
        verbose_name_plural = "貸出記録の紐付け"

    def __str__(self):
        return f"{self.item} {self.date}"


class AttendanceReminderDelivery(models.Model):
    """出欠リマインドを、どの端末に・どの回の・何日前の分まで送ったかの記録(二重送信の防止)。"""

    subscription = models.ForeignKey(
        "accounts.WebPushSubscription",
        on_delete=models.CASCADE,
        related_name="attendance_reminder_deliveries",
    )
    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name="reminder_deliveries",
    )
    date = models.DateField("対象日")
    days_until = models.IntegerField("何日前の通知か")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "出欠リマインド送信記録"
        verbose_name_plural = "出欠リマインド送信記録"
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "assignment", "date", "days_until"],
                name="schedule_attendance_reminder_unique",
            ),
        ]

    def __str__(self):
        return f"{self.assignment} {self.date} ({self.days_until}日前)"
