from django.db import models
from django_ckeditor_5.fields import CKEditor5Field
from django.utils.html import strip_tags

from .sanitizers import sanitize_richtext

class Pickup(models.Model):
    title = models.CharField("タイトル", max_length=100)
    caption = models.CharField("キャッチコピー", max_length=100, blank=True)
    image = models.FileField("画像", upload_to="pickup/")
    url = models.CharField("リンク先", max_length=200, blank=True)
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("公開", default=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "Pickup"
        verbose_name_plural = "Pickup"

    def __str__(self):
        return self.title

class Category(models.Model):
    name = models.CharField("カテゴリ名", max_length=50, unique=True)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Category"
        verbose_name_plural = "Category"

    def __str__(self):
        return self.name

class News(models.Model):
    title = models.CharField(max_length=200)
    date = models.DateField()
    category = models.ForeignKey(
        Category,
        verbose_name="カテゴリ",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="news",
    )
    caption = CKEditor5Field("本文", config_name="extends")
    image = models.ImageField(upload_to="news/", blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_internal = models.BooleanField(default=False)

    class Meta:
        ordering = ["-date"]
        verbose_name = "News"
        verbose_name_plural = "News"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        # 本文は news_detail.html で |safe を通すため、保存の時点で許可リストに
        # 落としておく。管理画面・サイト側フォーム・shell のどれを経由しても
        # 必ずここを通る。
        self.caption = sanitize_richtext(self.caption)
        super().save(*args, **kwargs)

    @property
    def has_caption(self):
        if not self.caption:
            return False

        text = strip_tags(self.caption)
        text = text.replace("\xa0", "").strip()

        return bool(text)