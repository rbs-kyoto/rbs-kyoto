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
            "is_internal",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "site-form__input"}),
            "date": forms.DateInput(attrs={"type": "date", "class": "site-form__input"}),
            "category": forms.TextInput(attrs={"class": "site-form__input"}),
        }
