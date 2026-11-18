from django import forms
from django.contrib.auth import get_user_model

from .models import BeonSessionMember

User = get_user_model()


class SessionAssignmentForm(forms.Form):
    chief = forms.ModelChoiceField(
        queryset=User.objects.all(), label="チーフ",
    )
    director = forms.ModelChoiceField(
        queryset=User.objects.all(), label="ディレクター",
    )
    announcer = forms.ModelChoiceField(
        queryset=User.objects.all(), label="アナウンサー",
    )

    def clean(self):
        cleaned = super().clean()
        users = [
            cleaned.get("chief"),
            cleaned.get("director"),
            cleaned.get("announcer"),
        ]
        users = [user.pk for user in users if user]
        if len(users) != len(set(users)):
            raise forms.ValidationError("同じユーザーを複数の役職に割り当てることはできません。")
        return cleaned

    def save(self, session):
        roles = (
            ("chief", BeonSessionMember.Role.CHIEF),
            ("director", BeonSessionMember.Role.DIRECTOR),
            ("announcer", BeonSessionMember.Role.ANNOUNCER),
        )
        for field, role in roles:
            BeonSessionMember.objects.update_or_create(
                session=session,
                role=role,
                defaults={"user": self.cleaned_data[field]},
            )
