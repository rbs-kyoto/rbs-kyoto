class BeonHostMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0].lower()

        if host in {
            "beon.rbs-kyoto.test",
            "beon.rbs-kyoto",
            "beon.rbs-kyoto.org",
        }:
            request.urlconf = "beon.host_urls"

        return self.get_response(request)