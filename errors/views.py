from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render


def _render_error(request, status_code):
    return render(
        request,
        f"{status_code}.html",
        status=status_code,
    )


def bad_request(request, exception):
    return _render_error(request, 400)


def permission_denied(request, exception):
    return _render_error(request, 403)


def page_not_found(request, exception):
    return _render_error(request, 404)


def server_error(request):
    return _render_error(request, 500)


def teapot(request):
    return _render_error(request, 418)


def _preview_error(request, status_code):
    if not request.user.is_superuser:
        raise PermissionDenied
    return render(request, f"{status_code}.html")


@login_required
def preview_400(request):
    return _preview_error(request, 400)


@login_required
def preview_403(request):
    return _preview_error(request, 403)


@login_required
def preview_404(request):
    return _preview_error(request, 404)


@login_required
def preview_500(request):
    return _preview_error(request, 500)


@login_required
def preview_513(request):
    return _preview_error(request, 513)


@login_required
def preview_418(request):
    return _preview_error(request, 418)
