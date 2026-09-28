"""Behavioral tests: accounting, project boundaries, privacy, and CLI contracts."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / '.agents/skills/token-audit/scripts'
sys.path.insert(0, str(SCRIPTS))


def usage(i=100, c=60, o=20, r=5):
    return dict(input_tokens=i, cached_input_tokens=c, output_tokens=o,
                reasoning_output_tokens=r, total_tokens=i + o)


def snapshot(u):
    return dict(type='event_msg', payload=dict(type='token_count',
                info=dict(total_token_usage=u, last_token_usage=u)))


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def log(self, rows, name='session.jsonl'):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return p

    def modules(self):
        self.assertTrue((SCRIPTS / 'audit.py').is_file(), 'audit implementation is missing')
        from auditlib.session import analyze_session, select_session
        from auditlib.project import analyze_project
        from auditlib.measure import TextMeter
        return analyze_session, select_session, analyze_project, TextMeter

    def analyze(self, rows):
        analyze, _, _, meter = self.modules()
        return analyze(self.log(rows), meter())

    def test_cumulative_snapshots_are_not_summed(self):
        result = self.analyze([snapshot(usage()), snapshot(usage()), snapshot(usage(200))])
        self.assertEqual(result['usage']['total_tokens'], 220)
        self.assertEqual(result['usage']['uncached_input_tokens'], 140)
        self.assertEqual(result['usage']['output_tokens'], 20)
        self.assertEqual(result['duplicate_snapshots'], 1)

    def test_response_record_can_be_newer_than_snapshot(self):
        record = dict(type='token_usage_record', payload=dict(response_id='r1',
                      usage=usage(), thread_token_usage=usage(300)))
        result = self.analyze([snapshot(usage()), record, record])
        self.assertEqual(result['usage']['total_tokens'], 320)
        self.assertEqual(result['response_records'], 1)

    def test_counter_reset_is_disclosed_not_invented_lifetime_total(self):
        result = self.analyze([snapshot(usage(500)), snapshot(usage(30, 10))])
        self.assertEqual(result['usage']['input_tokens'], 30)
        self.assertTrue(any('reset' in w for w in result['warnings']))

    def test_missing_usage_is_unknown_not_zero(self):
        result = self.analyze([])
        self.assertIsNone(result['usage'])

    def test_null_info_and_non_object_records_do_not_crash(self):
        result = self.analyze([None, [], dict(type='event_msg', payload=None),
                              dict(type='event_msg', payload=dict(type='token_count', info=None))])
        self.assertIsNone(result['usage'])

    def test_truncated_log_is_reported(self):
        analyze, _, _, meter = self.modules()
        p = self.log([snapshot(usage())])
        with p.open('a') as f:
            f.write('{"unfinished":')
        result = analyze(p, meter())
        self.assertEqual(result['malformed_lines'], 1)
        self.assertEqual(result['usage']['total_tokens'], 120)

    def test_invalid_counters_do_not_become_measurements(self):
        bad = usage(); bad['input_tokens'] = -1
        result = self.analyze([snapshot(bad)])
        self.assertIsNone(result['usage'])

    def test_inconsistent_provider_counters_are_disclosed(self):
        result = self.analyze([snapshot(usage(10, 20))])
        self.assertIsNone(result['usage']['uncached_input_tokens'])
        self.assertTrue(result['warnings'])

    def test_raw_log_secrets_never_appear_in_report(self):
        secret = 'fake-private-key-DO-NOT-EXPORT'
        rows = [dict(type='response_item', payload=dict(type='function_call',
                name='exec_command', call_id='a', arguments=secret)),
                dict(type='response_item', payload=dict(type='function_call_output',
                call_id='a', output=secret)),
                dict(type='response_item', payload=dict(type='message', role='user',
                content=[dict(type='input_text', text=secret)]))]
        result = self.analyze(rows)
        self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(result['tool_outputs'][0]['bytes'], len(secret))

    def test_repeated_tool_calls_are_candidates_not_savings(self):
        call = dict(type='response_item', payload=dict(type='custom_tool_call',
                    name='functions.exec', call_id='x', input='read file'))
        result = self.analyze([call, call])
        self.assertEqual(result['repeated_calls'][0]['count'], 2)
        self.assertNotIn('saved_tokens', json.dumps(result))

    def test_latest_selection_is_scoped_to_project(self):
        _, select, _, _ = self.modules()
        mine = self.log([dict(type='session_meta', payload=dict(cwd=str(self.root / 'project')))], 'logs/a.jsonl')
        other = self.log([dict(type='session_meta', payload=dict(cwd='/unrelated'))], 'logs/b.jsonl')
        os.utime(other, (2000000000, 2000000000))
        selected = select(self.root / 'logs', self.root / 'project')
        self.assertEqual(selected, mine)

    def test_no_matching_session_stays_unknown(self):
        _, select, _, _ = self.modules()
        self.assertIsNone(select(self.root / 'logs', self.root / 'project'))

    def test_fork_is_disclosed(self):
        result = self.analyze([dict(type='session_meta', payload=dict(forked_from_id='parent')), snapshot(usage())])
        self.assertTrue(any('fork' in w.lower() for w in result['warnings']))

    def test_gitignore_secret_files_and_external_symlinks_are_excluded(self):
        _, _, analyze, meter = self.modules()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('.github_examples/\nignored.py\n')
        (self.root / 'ignored.py').write_text('secret\n' * 100)
        (self.root / '.env').write_text('PRIVATE=abc')
        (self.root / 'safe.py').write_text('def f():\n    return 42\n')
        (self.root / 'linked.py').symlink_to('/etc/hosts')
        p = self.root / '.github_examples'; p.mkdir(); (p / 'huge.py').write_text('x\n' * 900)
        result = analyze(self.root, meter())
        paths = [r['path'] for r in result['files']]
        self.assertIn('safe.py', paths)
        self.assertFalse(set(paths) & {'.env', 'ignored.py', 'linked.py', '.github_examples/huge.py'})
        self.assertEqual(result['functions'][0]['lines'], 2)

    def test_instruction_routing_is_flagged_without_prescribing_a_model(self):
        _, _, analyze, meter = self.modules()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / 'AGENTS.md').write_text('Use GPT-6 for Python and route Rust to model X.\n')
        result = analyze(self.root, meter())
        self.assertEqual(result['instructions'][0]['routing_lines'], [1])
        self.assertNotIn('recommended_model', json.dumps(result))

    def test_no_tokenizer_means_no_fake_token_estimate(self):
        _, _, _, meter = self.modules()
        measured = meter().measure('hello 世界')
        self.assertEqual(measured['bytes'], len('hello 世界'.encode()))
        self.assertIsNone(measured['text_tokens'])

    @unittest.skipUnless(importlib.util.find_spec('tiktoken'), 'optional tiktoken not installed')
    def test_explicit_tokenizer_counts_text_and_accepts_literal_special_tokens(self):
        _, _, _, meter = self.modules()
        counter = meter('o200k_base')
        self.assertEqual(counter.measure('hello world')['text_tokens'], 2)
        self.assertGreater(counter.measure('<|endoftext|>')['text_tokens'], 1)

    def test_missing_explicit_log_fails_instead_of_selecting_another(self):
        self.modules()
        result = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'), '--project',
                str(self.root), '--session', str(self.root / 'missing.jsonl')],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.root / '.token-audit/evidence.json').exists())

    def test_report_does_not_overwrite_a_symlink_target(self):
        self.modules()
        original = self.root / 'precious.txt'
        original.write_text('preserve me')
        out = self.root / 'out'; out.mkdir()
        (out / 'evidence.json').symlink_to(original)
        result = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'), '--project',
                str(self.root), '--session', 'none', '--out', str(out)],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(original.read_text(), 'preserve me')

    def test_cli_emits_bounded_report_and_json(self):
        self.modules()
        p = self.log([snapshot(usage())])
        result = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'), '--project',
                str(self.root), '--session', str(p), '--out', str(self.root / 'out')],
                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(len(result.stdout), 1200)
        evidence = json.loads((self.root / 'out/evidence.json').read_text())
        self.assertEqual(evidence['session']['usage']['total_tokens'], 120)
        self.assertTrue((self.root / 'out/evidence.md').is_file())

    def test_custom_report_location_does_not_audit_its_own_output(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        (self.root / 'main.py').write_text('value = 1\n')
        # Both a subdirectory and the project root must preserve unrelated sources.
        for out in (self.root / 'reports', self.root):
            inventories = []
            for _ in range(3):
                result = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'),
                    '--project', str(self.root), '--session', 'none', '--out', str(out)],
                    capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads((out / 'evidence.json').read_text())
                inventories.append(report['project']['files'])
            self.assertEqual(inventories[0], inventories[1])
            self.assertEqual(inventories[1], inventories[2])
            self.assertIn('main.py', [row['path'] for row in inventories[-1]])
            # Other output locations aren't guessed: remove the known fixture reports.
            (out / 'evidence.json').unlink()
            (out / 'evidence.md').unlink()


if __name__ == '__main__':
    unittest.main()
