"""書き出し結果が、固めた仕様（spec/golden/）と同じかを確かめる。

仕様を意図して変えたときだけ、`UPDATE_GOLDEN=1` を付けて実行して、golden を作り直す。
    UPDATE_GOLDEN=1 python manage.py test spec
作り直したら、差分（git diff spec/golden）を、必ず目で確かめる。
"""

import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings

from publisher import builder

from .fixture import FROZEN_NOW, build_sample_data

GOLDEN = Path(__file__).parent / "golden"
# 書き出しのうち、中身を比べるのは HTML だけ（static/media は元のファイルのコピー、release.json は日時入り）
COMPARED = ("public", "members", "errors")


def read_tree(root):
    return {
        str(path.relative_to(root)): path.read_text(encoding="utf-8")
        for folder in COMPARED
        for path in sorted((root / folder).rglob("*"))
        if path.is_file()
    }


class GoldenExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        build_sample_data()

    def build(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        media = root / "media-src"
        media.mkdir()
        with override_settings(MEDIA_ROOT=media), mock.patch("django.utils.timezone.now", return_value=FROZEN_NOW):
            builder._write_release(root / "out", 1)
        return read_tree(root / "out")

    def test_the_export_matches_the_golden_files(self):
        actual = self.build()

        if os.environ.get("UPDATE_GOLDEN") == "1":
            shutil.rmtree(GOLDEN, ignore_errors=True)
            for name, text in actual.items():
                target = GOLDEN / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            self.skipTest("golden を作り直しました。git diff で確かめてください。")

        expected = {
            str(path.relative_to(GOLDEN)): path.read_text(encoding="utf-8")
            for path in sorted(GOLDEN.rglob("*"))
            if path.is_file()
        }
        self.assertEqual(sorted(actual), sorted(expected), "書き出されるページの一覧が変わりました")
        for name in expected:
            with self.subTest(page=name):
                self.assertEqual(actual[name], expected[name])

    def test_pages_are_exported_deterministically(self):
        self.assertEqual(self.build(), self.build())

    def test_the_public_export_never_contains_private_content(self):
        pages = {name: text for name, text in self.build().items() if name.startswith("public/")}
        for name, text in pages.items():
            for secret in ("部員だけの本文", "部内限定の連絡", "出てはいけない"):
                self.assertNotIn(secret, text, name)
        self.assertFalse(any(name.startswith("public/manuals") or name.startswith("public/videos") for name in pages))
