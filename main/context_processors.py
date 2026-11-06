from django.conf import settings
from django.templatetags.static import static
from django.utils import timezone

from .models import FooterSocialLink, HeaderLogoSchedule, SitePage


def footer_content(_request):
    today = timezone.localdate()
    header_logo = (
        HeaderLogoSchedule.objects.filter(starts_on__lte=today, ends_on__gte=today)
        .order_by("-starts_on", "-pk")
        .first()
    )
    environment_suffix = "-dev" if settings.DEBUG else ""
    return {
        "footer_site_pages": SitePage.objects.all(),
        "footer_social_links": FooterSocialLink.objects.filter(is_active=True),
        "header_logo_url": (
            header_logo.image.url if header_logo else static("main/img/rbs.svg")
        ),
        "header_logo_dark_url": (
            header_logo.image.url
            if header_logo
            else static("main/img/rbs-dark.svg")
        ),
        "pwa_icon_180_url": static(
            f"main/img/pwa-icon{environment_suffix}-180.png"
        ),
    }
