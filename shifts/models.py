from django.conf import settings
from django.db import models


class Role(models.Model):
    name = models.CharField("役割名", max_length=50, unique=True)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "役割"
        verbose_name_plural = "役割"

    def __str__(self):
        return self.name


class Member(models.Model):
    """割り当て先の部員名簿。

    ログインアカウント（accounts.User）の登録が間に合わない場合でも、
    名前だけで割り当てを進められるようにするための存在。アカウントが
    できたら`user`を紐付ければ「自分の担当」ページが使えるようになる。
    """

    name = models.CharField("氏名", max_length=50)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        verbose_name="ログインアカウント",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shift_member",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "部員"
        verbose_name_plural = "部員名簿"

    def __str__(self):
        return self.name


class Event(models.Model):
    title = models.CharField("イベント名", max_length=100)
    date = models.DateField("日付")
    is_active = models.BooleanField("公開", default=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "イベント"
        verbose_name_plural = "イベント"

    def __str__(self):
        return self.title


class Program(models.Model):
    event = models.ForeignKey(
        Event, verbose_name="イベント", on_delete=models.CASCADE, related_name="programs"
    )
    name = models.CharField("種目・項目名", max_length=100)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "種目"
        verbose_name_plural = "種目"

    def __str__(self):
        return f"{self.event.title} / {self.name}"


class Assignment(models.Model):
    program = models.ForeignKey(
        Program, verbose_name="種目", on_delete=models.CASCADE, related_name="assignments"
    )
    role = models.ForeignKey(
        Role, verbose_name="役割", on_delete=models.PROTECT, related_name="assignments"
    )
    member = models.ForeignKey(
        Member,
        verbose_name="担当者",
        on_delete=models.PROTECT,
        related_name="assignments",
    )

    class Meta:
        ordering = ["role__order", "id"]
        verbose_name = "割り当て"
        verbose_name_plural = "割り当て"

    def __str__(self):
        return f"{self.program} - {self.role}: {self.member}"
