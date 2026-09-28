"""Ensure marketplace installs can carry one self-contained skill to either host."""
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PluginTests(unittest.TestCase):
    def test_both_marketplaces_resolve_the_same_plugin(self):
        codex = json.loads((ROOT / '.agents/plugins/marketplace.json').read_text())
        claude = json.loads((ROOT / '.claude-plugin/marketplace.json').read_text())
        self.assertEqual(codex['name'], claude['name'])
        sources = [codex['plugins'][0]['source']['path'], claude['plugins'][0]['source']]
        self.assertEqual(sources[0], sources[1])
        plugin = (ROOT / sources[0]).resolve()
        self.assertTrue(plugin.is_relative_to(ROOT))
        manifests = [json.loads((plugin / p).read_text()) for p in
                     ('plugin.json', '.codex-plugin/plugin.json', '.claude-plugin/plugin.json')]
        self.assertEqual({m['name'] for m in manifests}, {'token-max'})
        self.assertEqual(len({m['version'] for m in manifests}), 1)
        self.assertEqual(claude['plugins'][0]['version'], manifests[0]['version'])

    def test_installed_copy_has_no_checkout_dependencies(self):
        with tempfile.TemporaryDirectory() as temp:
            installed = Path(temp).resolve() / 'token-max'
            shutil.copytree(ROOT / 'plugins/token-max', installed,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            for path in installed.rglob('*'):
                self.assertFalse(path.is_symlink())
            skill = installed / 'skills/token-audit/SKILL.md'
            for target in re.findall(r'\]\(([^)]+)\)', skill.read_text()):
                reference = (skill.parent / target).resolve()
                self.assertTrue(reference.is_relative_to(installed))
                self.assertTrue(reference.is_file(), target)
            self.assertFalse((installed / 'hooks').exists())
            self.assertFalse((installed / '.mcp.json').exists())
            self.assertTrue((installed / 'skills/token-audit/scripts/audit.py').is_file())
