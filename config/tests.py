import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from .staticstorage import HashedAdminStaticStorage, plain_static_urls


class HashedAdminStaticStorageTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / "ops.js").write_text("console.log(1)")
        self.storage = HashedAdminStaticStorage(location=str(self.root), base_url="/static/")
        self.storage.hashed_files = {}
        self.storage.manifest_strict = False
        hashed = self.storage.hashed_name("ops.js")
        self.storage.hashed_files["ops.js"] = hashed
        self.hashed = hashed

    def test_admin_urls_carry_a_hash(self):
        self.assertNotEqual(self.hashed, "ops.js")
        self.assertEqual(self.storage.url("ops.js"), f"/static/{self.hashed}")

    def test_the_static_export_keeps_the_original_names(self):
        with plain_static_urls():
            self.assertEqual(self.storage.url("ops.js"), "/static/ops.js")
        self.assertEqual(self.storage.url("ops.js"), f"/static/{self.hashed}")
