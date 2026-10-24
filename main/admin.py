from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.html import format_html
from urllib.parse import urljoin, urlsplit
from unfold.admin import ModelAdmin
from unfold.widgets import UnfoldAdminTextInputWidget
from publisher.admin_ui import LivePreviewMixin
from .models import Pickup, News, Category


def _thumbnail(file):
    if not file:
        return "—"
    return format_html('<img src="{}" alt="" style="height:2.5rem;border-radius:.25rem">', file.url)


class PickupAdminForm(forms.ModelForm):
    url = forms.CharField(
        label="リンク先",
        required=False,
        max_length=200,
        widget=UnfoldAdminTextInputWidget,
        help_text="サイト内は /about/ のようなパス、外部サイトは https:// から入力してください。",
    )

    class Meta:
        model = Pickup
        fields = "__all__"

    def clean_url(self):
        value = self.cleaned_data["url"].strip()
        if not value:
            return ""

        parsed_url = urlsplit(value)
        if parsed_url.scheme or parsed_url.netloc:
            URLValidator()(value)
            return value

        if value.startswith("//") or "\\" in value:
            raise ValidationError("リンク先にはサイト内のパスか、有効なURLを入力してください。")

        return urljoin("/", value)


@admin.register(Pickup)
class PickupAdmin(LivePreviewMixin, ModelAdmin):
    form = PickupAdminForm
    list_display = ("image_thumbnail", "title", "caption", "order", "is_active")
    list_display_links = ("image_thumbnail", "title")
    list_editable = ("order", "is_active")
    search_fields = ("title", "caption")
    ordering = ("order",)

    @admin.display(description="画像")
    def image_thumbnail(self, obj):
        return _thumbnail(obj.image)

@admin.register(Category)
class CategoryAdmin(ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    ordering = ("order", "name")

@admin.register(News)
class NewsAdmin(LivePreviewMixin, ModelAdmin):
    list_display = ("image_thumbnail", "title", "date", "category", "is_active", "is_internal")
    list_display_links = ("image_thumbnail", "title")
    list_filter = ("category", "is_active", "is_internal")
    list_editable = ("is_active",)
    search_fields = ("title",)
    ordering = ("-date",)

    @admin.display(description="画像")
    def image_thumbnail(self, obj):
        return _thumbnail(obj.image)
