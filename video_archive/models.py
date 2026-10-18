import re
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.db import models


class VideoGroup(models.Model):
    name = models.CharField("グループ名", max_length=100, unique=True)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "Video group"
        verbose_name_plural = "Video groups"

    def __str__(self):
        return self.name


class Video(models.Model):
    title = models.CharField("タイトル", max_length=200)
    url = models.URLField("動画URL")
    description = models.TextField("説明", blank=True)
    group = models.ForeignKey(
        VideoGroup,
        verbose_name="グループ",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="videos",
    )
    event_date = models.DateField("開催日", null=True)
    production_date = models.DateField("制作日", null=True)
    order = models.PositiveIntegerField("表示順", default=0)
    is_active = models.BooleanField("公開", default=True)
    registered_at = models.DateTimeField("登録日時", auto_now_add=True)

    class Meta:
        ordering = ["group__order", "group__name", "order", "-registered_at"]
        verbose_name = "Video"
        verbose_name_plural = "Video"

    def __str__(self):
        return self.title

    def clean(self):
        super().clean()
        if self.url and not self.youtube_embed_url:
            raise ValidationError({"url": "有効なYouTube動画のURLを入力してください。"})

    @property
    def youtube_embed_url(self):
        try:
            parsed_url = urlsplit(self.url)
        except ValueError:
            return ""

        hostname = (parsed_url.hostname or "").lower()

        if hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            if parsed_url.path == "/watch":
                video_id = parse_qs(parsed_url.query).get("v", [""])[0]
            else:
                path_parts = parsed_url.path.strip("/").split("/")
                video_id = (
                    path_parts[1]
                    if len(path_parts) == 2
                    and path_parts[0] in {"embed", "shorts", "live"}
                    else ""
                )
        elif hostname == "youtu.be":
            path_parts = parsed_url.path.strip("/").split("/")
            video_id = path_parts[0] if len(path_parts) == 1 else ""
        else:
            video_id = ""

        if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
            return ""
        return f"https://www.youtube-nocookie.com/embed/{video_id}"
