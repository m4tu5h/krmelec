"""Verify that deployment packaging only includes the intended public files."""
import json
import tempfile
import unittest
from pathlib import Path

from build_site import build_site, WEB_FILES


class BuildSiteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'web').mkdir()
        for name in WEB_FILES:
            (self.root / 'web' / name).write_text('public ' + name)
        (self.root / 'menus.json').write_text(json.dumps({
            'requested_date': '2026-10-15', 'meals': [{'name': 'Lunch'}]}))

    def test_allowlist_excludes_secrets_and_removes_stale_output(self):
        (self.root / '.env').write_text('PRIVATE')
        (self.root / 'web' / '.env').write_text('PRIVATE')
        (self.root / 'web' / 'diagnostics.json').write_text('PRIVATE')
        output = build_site(self.root)
        (output / 'stale-secret.txt').write_text('PRIVATE')
        output = build_site(self.root)
        self.assertEqual({p.name for p in output.iterdir()}, {*WEB_FILES, 'menus.json'})
        self.assertEqual((output / 'menus.json').read_bytes(), (self.root / 'menus.json').read_bytes())
        self.assertTrue((self.root / '.env').exists())

    def test_invalid_data_leaves_previous_package_untouched(self):
        output = build_site(self.root)
        previous = (output / 'menus.json').read_bytes()
        (self.root / 'menus.json').write_text('{"meals": []}')
        with self.assertRaises(ValueError):
            build_site(self.root)
        self.assertEqual((output / 'menus.json').read_bytes(), previous)


if __name__ == '__main__':
    unittest.main()
