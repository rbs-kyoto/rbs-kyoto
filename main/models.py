from django.db import models
from django_ckeditor_5.fields import CKEditor5Field
from django.utils.html import strip_tags

class Pickup(models.Model):
    title = models.CharField("タイトル", max_length=100)
    image = models.FileField("画像", upload_to="pickup/")
    url = models.URLField("リンク先", blank=True)
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("公開", default=True)

    class Meta:
        ordering = ["order"]
        verbose_name = "Pickup"
        verbose_name_plural = "Pickup"

    def __str__(self):
        return self.title

class News(models.Model):
    title = models.CharField(max_length=200)
    date = models.DateField()
    category = models.CharField(max_length=50)
    caption = CKEditor5Field("本文", config_name="extends")
    image = models.ImageField(upload_to="news/", blank=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "News"
        verbose_name_plural = "News"

    def __str__(self):
        return self.title

    @property
    def has_caption(self):
        if not self.caption:
            return False

        text = strip_tags(self.caption)
        text = text.replace("\xa0", "").strip()

        return bool(text)