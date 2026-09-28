import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.site = Path(self.temp.name)
        (self.site / 'CNAME').write_text('token-max.swacktech.com\n')
        (self.site / 'styles.css').write_text('body { color: black; }')

    def check(self, body):
        (self.site / 'index.html').write_text('<!doctype html><html lang="en"><head>'
            '<title>Docs</title><link rel="canonical" href="https://token-max.swacktech.com/">'
            '<link rel="stylesheet" href="styles.css"></head><body><h1>Docs</h1>'
            + body + '</body></html>')
        path = ROOT / 'scripts/check_site.py'
        self.assertTrue(path.exists(), 'site checker is missing')
        spec = importlib.util.spec_from_file_location('check_site', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.validate_site(self.site)

    def test_valid_navigation_and_assets_pass(self):
        self.assertEqual(self.check('<a href="#guide">Guide</a><section id="guide">Hello</section>'), [])

    def test_broken_anchor_and_missing_asset_fail(self):
        errors = self.check('<a href="#missing">Guide</a><script src="missing.js"></script>')
        self.assertTrue(any('missing anchor' in error for error in errors))
        self.assertTrue(any('missing asset' in error for error in errors))

    def test_mismatched_tags_and_duplicate_ids_fail(self):
        errors = self.check('<div id="x"><span></div><p id="x">bad</p>')
        self.assertTrue(any('mismatched' in error for error in errors))
        self.assertTrue(any('duplicate id' in error for error in errors))

    def test_wrong_domain_and_private_artifact_fail(self):
        (self.site / 'CNAME').write_text('wrong.example\n')
        (self.site / 'session.jsonl').write_text('private log')
        errors = self.check('')
        self.assertTrue(any('CNAME' in error for error in errors))
        self.assertTrue(any('unexpected publish file' in error for error in errors))

    def test_only_named_plugin_archive_is_publishable(self):
        (self.site / 'token-max.zip').write_bytes(b'plugin fixture')
        self.assertEqual(self.check('<a href="token-max.zip">Install</a>'), [])
        (self.site / 'private.zip').write_bytes(b'private fixture')
        self.assertTrue(any('unexpected publish file' in error for error in self.check('')))


if __name__ == '__main__':
    unittest.main()
