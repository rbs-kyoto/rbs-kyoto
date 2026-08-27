from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.exceptions import ImmediateHttpResponse
from allauth.socialaccount.models import SocialAccount
from django.contrib import messages
from django.shortcuts import redirect
from accounts.models import User

class RakunanSocialAccountAdapter(DefaultSocialAccountAdapter):

    def pre_social_login(self, request, sociallogin):
        email = (sociallogin.user.email or "").lower().strip()
        if not email.endswith("@rakunan-h.ed.jp"):
            messages.error(
                request,
                "権限がありません。組織管理（末尾が @rakunan-h.ed.jp）のアカウントでログインしてください。",
            )
            raise ImmediateHttpResponse(
                redirect("accounts:login")
            )

        if sociallogin.is_existing:
            user = sociallogin.user
            if not user.is_staff:
                user.is_staff = True
                user.save(update_fields=["is_staff"])

            return

        google_username = email.split("@", 1)[0]
        username_user = User.objects.filter(
            username__iexact=google_username
        ).first()

        email_user = User.objects.filter(
            email__iexact=email
        ).first()
        if (
            username_user is not None
            and email_user is not None
            and username_user.pk != email_user.pk
        ):
            messages.error(
                request,
                "既存ユーザーとの紐付け先を特定できません。管理者にお問い合わせください。",
            )
            raise ImmediateHttpResponse(
                redirect("accounts:login")
            )

        existing_user = username_user or email_user

        if existing_user is not None:
            if SocialAccount.objects.filter(
                user=existing_user,
                provider="google",
            ).exists():
                messages.error(
                    request,
                    "このユーザーにはすでにGoogleアカウントが紐付いています。",
                )
                raise ImmediateHttpResponse(
                    redirect("accounts:login")
                )

            sociallogin.token = None
            request.session["google_link_user_id"] = existing_user.pk
            request.session["google_link_sociallogin"] = sociallogin.serialize()

            raise ImmediateHttpResponse(
                redirect("accounts:google_link_confirm")
            )

    def save_user(self, request, sociallogin, form=None):
        user = super().save_user(request, sociallogin, form)
        user.is_staff = True
        user.save(update_fields=["is_staff"])

        return user