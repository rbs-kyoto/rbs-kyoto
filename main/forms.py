from django import forms
from .models import News


class NewsForm(forms.ModelForm):
    class Meta:
        model = News
        fields = [
            "title",
            "date",
            "category",
            "caption",
            "image",
            "is_active",
            "visibility",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "site-form__input"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "site-form__input"}),
            "category": forms.Select(attrs={"class": "site-form__input"}),
            "visibility": forms.Select(attrs={"class": "site-form__input"}),
        }
        labels = {
            "title": "タイトル",
            "date": "日付",
            "category": "カテゴリ",
            "caption": "本文",
            "image": "画像",
            "is_active": "公開する",
            "visibility": "公開範囲",
        }
        error_messages = {
            "title": {"required": "タイトルを入力してください。"},
            "date": {"required": "日付を入力してください。"},
            "caption": {"required": "本文を入力してください。"},
        }
