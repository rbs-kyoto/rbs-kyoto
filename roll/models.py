from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models


class Position(models.Model):
    name = models.CharField("役職名", max_length=100, unique=True)
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("使用中", default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "部内役職"
        verbose_name_plural = "部内役職"

    def __str__(self):
        return self.name


class RosterEntry(models.Model):
    GRADE_CHOICES = tuple((str(number), f"{number}年") for number in range(1, 7))
    HOMEROOM_CHOICES = tuple((str(number), f"{number}組") for number in range(1, 10))

    class EntryType(models.TextChoices):
        STUDENT = "student", "生徒"
        FACULTY = "faculty", "教職員"
        ORGANIZATION = "organization", "校内団体"
        OTHER = "other", "その他"

    entry_type = models.CharField(
        "種別",
        max_length=20,
        choices=EntryType.choices,
        default=EntryType.STUDENT,
    )
    name = models.CharField("氏名・団体名", max_length=150)
    name_kana = models.CharField("ふりがな", max_length=150, blank=True)
    school_identifier = models.CharField(
        "校内識別番号",
        max_length=50,
        null=True,
        blank=True,
        unique=True,
    )
    grade = models.CharField("学年", max_length=1, blank=True, choices=GRADE_CHOICES)
    homeroom = models.CharField(
        "組",
        max_length=1,
        blank=True,
        choices=HOMEROOM_CHOICES,
    )
    student_number = models.PositiveIntegerField(
        "出席番号",
        null=True,
        blank=True,
        validators=[MinValueValidator(1)],
    )
    is_member = models.BooleanField("放送部員", default=False)
    account = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="アカウント",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="roster_entry",
    )
    positions = models.ManyToManyField(
        Position,
        verbose_name="部内役職",
        blank=True,
        related_name="members",
    )
    notes = models.TextField("備考", blank=True)
    created_at = models.DateTimeField("登録日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = [
            "entry_type",
            "grade",
            "homeroom",
            "student_number",
            "name_kana",
            "name",
        ]
        verbose_name = "名簿"
        verbose_name_plural = "名簿"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(grade="") | models.Q(grade__in=[str(n) for n in range(1, 7)]),
                name="roll_grade_is_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(homeroom="")
                | models.Q(homeroom__in=[str(n) for n in range(1, 10)]),
                name="roll_homeroom_is_valid",
            ),
        ]

    def __str__(self):
        school_class = []
        if self.grade:
            school_class.append(f"{self.grade}年")
        if self.homeroom:
            school_class.append(f"{self.homeroom}組")
        if self.student_number is not None:
            school_class.append(f"{self.student_number}番")
        suffix = f"（{' '.join(school_class)}）" if school_class else ""
        return f"{self.name}{suffix}"

    @property
    def is_person(self):
        return self.entry_type != self.EntryType.ORGANIZATION
