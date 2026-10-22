from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django import forms

from .models import SuperuserGrantCredential, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("RBS", {"fields": ("display_name",)}),
    )


class SuperuserGrantCredentialAdminForm(forms.ModelForm):
    password = forms.CharField(
        label="昇格パスワード",
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="設定・変更する場合のみ入力してください。平文では保存されません。",
    )

    class Meta:
        model = SuperuserGrantCredential
        fields = ()

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if self.instance._state.adding and not password:
            raise forms.ValidationError("昇格パスワードを入力してください。")
        return password

    def save(self, commit=True):
        credential = super().save(commit=False)
        password = self.cleaned_data.get("password")
        if password:
            credential.set_password(password)
        if commit:
            credential.save()
        return credential


@admin.register(SuperuserGrantCredential)
class SuperuserGrantCredentialAdmin(admin.ModelAdmin):
    form = SuperuserGrantCredentialAdminForm

    def has_add_permission(self, request):
        return request.user.is_superuser and not SuperuserGrantCredential.objects.exists()

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser