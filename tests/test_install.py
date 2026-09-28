from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_install(self, *args):
        self.assertTrue((ROOT / 'scripts/install.py').exists(), 'installer is missing')
        return subprocess.run([sys.executable, str(ROOT / 'scripts/install.py'),
                              '--skills-dir', str(self.root / 'skills'),
                              '--codex-home', str(self.root / 'codex'), *args],
                              capture_output=True, text=True)

    def test_install_is_idempotent_and_skill_is_self_contained(self):
        first = self.run_install(); second = self.run_install()
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        target = self.root / 'skills/token-audit'
        self.assertTrue((target / 'SKILL.md').exists())
        result = subprocess.run([sys.executable, str(target / 'scripts/audit.py'), '--help'], capture_output=True)
        self.assertEqual(result.returncode, 0)
        self.assertFalse((self.root / 'codex/prompts').exists())

    def test_existing_unmanaged_skill_is_preserved(self):
        target = self.root / 'skills/token-audit'
        target.mkdir(parents=True)
        (target / 'SKILL.md').write_text('my skill')
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((target / 'SKILL.md').read_text(), 'my skill')

    def test_legacy_prompt_is_optional_and_resolves_skill_path(self):
        result = self.run_install('--legacy-prompt')
        self.assertEqual(result.returncode, 0, result.stderr)
        prompt = (self.root / 'codex/prompts/token-audit.md').read_text()
        self.assertIn(str(self.root / 'skills/token-audit/SKILL.md'), prompt)
        self.assertIn('$ARGUMENTS', prompt)

    def test_existing_legacy_prompt_is_preserved_before_any_install(self):
        prompt = self.root / 'codex/prompts/token-audit.md'
        prompt.parent.mkdir(parents=True)
        prompt.write_text('my prompt')
        result = self.run_install('--legacy-prompt')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(prompt.read_text(), 'my prompt')
        self.assertFalse((self.root / 'skills/token-audit').exists())


if __name__ == '__main__':
    unittest.main()
