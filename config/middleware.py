from urllib.parse import urlunsplit

from django.conf import settings
from django.http import HttpResponsePermanentRedirect


class CanonicalHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":", 1)[0].lower()
        if (
            request.method in {"GET", "HEAD"}
            and host in {
                settings.CANONICAL_DOMAIN,
                f"www.{settings.CANONICAL_DOMAIN}",
            }
            and host != settings.CANONICAL_HOST
        ):
            canonical_url = urlunsplit(
                (
                    request.scheme,
                    settings.CANONICAL_HOST,
                    request.path,
                    request.META.get("QUERY_STRING", ""),
                    "",
                )
            )
            return HttpResponsePermanentRedirect(canonical_url)

        return self.get_response(request)
