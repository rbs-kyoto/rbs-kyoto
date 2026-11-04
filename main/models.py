from django.db import models
from django.core.validators import FileExtensionValidator
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


class SitePage(models.Model):
    PAGE_CHOICES = [
        ("terms", "ご利用にあたって"),
        ("privacy", "プライバシーポリシー"),
        ("ethics", "技術者倫理方針"),
        ("sitemap", "サイトマップ"),
    ]

    slug = models.SlugField("ページ識別子", max_length=20, choices=PAGE_CHOICES, unique=True)
    title = models.CharField("ページタイトル", max_length=100)
    content = CKEditor5Field("本文", config_name="extends", blank=True)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "固定ページ"
        verbose_name_plural = "固定ページ"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.content = sanitize_richtext(self.content)
        super().save(*args, **kwargs)


class FooterSocialLink(models.Model):
    label = models.CharField("アクセシビリティ用名称", max_length=50)
    url = models.URLField("リンク先")
    light_icon = models.FileField(
        "ライトモード用SVG",
        upload_to="footer/social-icons/",
        blank=True,
        validators=[FileExtensionValidator(["svg"])],
    )
    dark_icon = models.FileField(
        "ダークモード用SVG",
        upload_to="footer/social-icons/",
        blank=True,
        validators=[FileExtensionValidator(["svg"])],
    )
    hover_icon = models.FileField(
        "ホバー用SVG",
        upload_to="footer/social-icons/",
        blank=True,
        validators=[FileExtensionValidator(["svg"])],
    )
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("表示", default=True)

    class Meta:
        ordering = ["order", "pk"]
        verbose_name = "フッターSNSリンク"
        verbose_name_plural = "フッターSNSリンク"

    def __str__(self):
        return self.label

    def _icon_url(self, preferred_icon):
        icon = (
            getattr(self, preferred_icon)
            or self.light_icon
            or self.dark_icon
            or self.hover_icon
        )
        return icon.url if icon else ""

    @property
    def light_icon_url(self):
        return self._icon_url("light_icon")

    @property
    def dark_icon_url(self):
        return self._icon_url("dark_icon")

    @property
    def hover_icon_url(self):
        return self.hover_icon.url if self.hover_icon else ""

    @property
    def has_hover_icon(self):
        return bool(self.hover_icon)