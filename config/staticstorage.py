import threading
from contextlib import contextmanager

from django.contrib.staticfiles.storage import StaticFilesStorage
from whitenoise.storage import CompressedManifestStaticFilesStorage

_state = threading.local()


@contextmanager
def plain_static_urls():
    """この中で作る URL には、ハッシュを付けない（静的書き出しは、元のファイル名のまま配信するため）。"""
    previous = getattr(_state, "plain", False)
    _state.plain = True
    try:
        yield
    finally:
        _state.plain = previous


class HashedAdminStaticStorage(CompressedManifestStaticFilesStorage):
    """管理画面用に、CSS・JS のファイル名にハッシュを付ける。更新してもブラウザが古い版を使い続けない。"""

    def url(self, name, force=False):
        if getattr(_state, "plain", False):
            return StaticFilesStorage.url(self, name)
        return super().url(name, force)
