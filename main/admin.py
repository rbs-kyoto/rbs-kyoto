from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from urllib.parse import urljoin, urlsplit
from .models import Pickup, News, Category


class PickupAdminForm(forms.ModelForm):
    url = forms.CharField(
        label="リンク先",
        required=False,
        max_length=200,
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
class PickupAdmin(admin.ModelAdmin):
    form = PickupAdminForm
    list_display = ("title", "caption", "order", "is_active")
    list_editable = ("order", "is_active")
    ordering = ("order",)

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "order")
    list_editable = ("order",)
    ordering = ("order", "name")

@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ("title", "date", "category", "is_active", "is_internal")
    list_filter = ("category", "is_active")
    list_editable = ("is_active",)
    ordering = ("-date",)
