from django.db import models


class Manual(models.Model):
    title = models.CharField("タイトル", max_length=200)
    content = models.TextField("本文(Markdown)", blank=True)
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("公開", default=True)
    uploaded_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ["order", "-uploaded_at"]
        verbose_name = "マニュアル"
        verbose_name_plural = "マニュアル"

    def __str__(self):
        return self.title
