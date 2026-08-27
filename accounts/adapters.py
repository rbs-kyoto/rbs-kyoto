from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from django.contrib import messages
from django.shortcuts import redirect

class RakunanSocialAccountAdapter(DefaultSocialAccountAdapter):
    
    def pre_social_login(self, request, sociallogin):
        email = (sociallogin.user.email or "").lower().strip()

        if not email.endswith("@rakunan-h.ed.jp"):
            messages.error(
                request,
                "ログイン権限がありません。@rakunan-h.ed.jp のアカウントでログインしてください。",
            )
            raise ImmediateHttpResponse(
                redirect("accounts:login")
            )
        
        if sociallogin.is_existing:
            user = sociallogin.user
            if not user.is_staff:
                user.is_staff = True
                user.save(update_fields=["is_staff"])

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        user.is_staff = True
        user.save(update_fields=["is_staff"])

        return user