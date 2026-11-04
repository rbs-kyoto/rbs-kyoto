from .models import FooterSocialLink, SitePage


def footer_content(request):
    return {
        "footer_site_pages": SitePage.objects.all(),
        "footer_social_links": FooterSocialLink.objects.filter(is_active=True),
    }
