import re
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import models
from PIL import Image, ImageOps, UnidentifiedImageError


def _convert_thumbnail_to_webp(uploaded_file):
    try:
        with Image.open(uploaded_file) as source_image:
            image = ImageOps.exif_transpose(source_image)
            image.thumbnail((1280, 720), Image.Resampling.LANCZOS)
            has_alpha = (
                image.mode in {"RGBA", "LA"}
                or image.mode == "P" and "transparency" in image.info
            )
            image = image.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=82, method=6)
    except (UnidentifiedImageError, OSError) as error:
        raise ValidationError(
            {"thumbnail": "有効な画像ファイルを選択してください。"}
        ) from error

    filename = Path(uploaded_file.name).with_suffix(".webp").name
    return ContentFile(output.getvalue(), name=filename)


class VideoGroup(models.Model):
    name = models.CharField("グループ名", max_length=100, unique=True)
    order = models.PositiveIntegerField("表示順", default=0)

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "動画グループ"
        verbose_name_plural = "動画グループ"

    def __str__(self):
        return self.name


class Video(models.Model):
    title = models.CharField("タイトル", max_length=200)
    url = models.URLField("動画URL")
    thumbnail = models.ImageField(
        "サムネイル画像",
        upload_to="video_archive/thumbnails/",
        blank=True,
    )
    description = models.TextField("説明", blank=True)
    has_subtitles = models.BooleanField("字幕あり", default=False)
    subtitle_language = models.CharField("字幕言語", max_length=100, blank=True)
    subtitle_notes = models.TextField("字幕の補足情報", blank=True)
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
        verbose_name = "動画"
        verbose_name_plural = "動画"

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if self.thumbnail and not self.thumbnail._committed:
            self.thumbnail = _convert_thumbnail_to_webp(self.thumbnail)
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if self.url and not self.youtube_embed_url:
            raise ValidationError({"url": "有効なYouTube動画のURLを入力してください。"})

    @property
    def youtube_video_id(self):
        try:
            parsed_url = urlsplit(self.url)
        except ValueError:
            return None

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
            return None
        return video_id

    @property
    def youtube_embed_url(self):
        video_id = self.youtube_video_id
        if video_id is None:
            return ""
        return f"https://www.youtube-nocookie.com/embed/{video_id}?playsinline=1"

    @property
    def youtube_thumbnail_url(self):
        video_id = self.youtube_video_id
        if video_id is None:
            return ""
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
