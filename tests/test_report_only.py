"""Report-only boundaries and diagnostic preservation independent of size."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/token-audit/scripts'
sys.path.insert(0, str(SCRIPTS))
from auditlib.measure import TextMeter
from auditlib.session import analyze_session
from retrieve import retrieve
from query import select


class ReportOnlyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.log = self.root / 'rollout.jsonl'

    def write_outputs(self, outputs):
        self.log.write_text(''.join(json.dumps({'type': 'response_item', 'payload': {
            'type': 'function_call_output', 'call_id': str(n), 'output': text}}) + '\n'
            for n, text in enumerate(outputs)))
        return analyze_session(self.log, TextMeter())

    def test_small_failure_survives_size_ranking_and_can_be_recovered(self):
        result = self.write_outputs(['routine progress\n' * 100] * 20 + ['ERROR: checksum mismatch'])
        self.assertNotIn(21, [row['line'] for row in result['tool_outputs']])
        row = result['diagnostics'][0]
        self.assertEqual(row['line'], 21)
        self.assertNotIn('checksum mismatch', json.dumps(result))
        recovered = retrieve(self.log, row['line'], row['record_sha256'])
        self.assertEqual(recovered['text'], 'ERROR: checksum mismatch')
        self.assertTrue(recovered['untrusted_evidence'])
        self.assertFalse(recovered['truncated'])

    def test_nonzero_exit_survives_success_banner_and_structured_wrapper(self):
        result = self.write_outputs([
            'SUCCESS\nProcess exited with code 2\n',
            {'output': 'All finished', 'exit_code': 3},
            json.dumps({'output': 'All finished', 'metadata': {'exit_code': 4}}),
            {'content': [{'type': 'text', 'text': 'oops'}], 'isError': True}])
        self.assertEqual([r['exit_codes'] for r in result['diagnostics']], [[2], [3], [4], []])
        self.assertIn('tool_error', result['diagnostics'][-1]['signals'])

    def test_bounded_retrieval_retains_truncation_and_failure_signals(self):
        result = self.write_outputs(['ok\n' * 500 + 'FATAL: last line'])
        row = result['diagnostics'][0]
        first = retrieve(self.log, 1, row['record_sha256'], max_chars=40)
        self.assertEqual(len(first['text']), 40)
        self.assertTrue(first['truncated'])
        self.assertEqual(first['next_offset'], 40)
        self.assertIn('error_marker', first['signals'])
        last = retrieve(self.log, 1, row['record_sha256'], offset=1500)
        self.assertEqual(last['text'], 'FATAL: last line')
        self.assertIsNone(last['next_offset'])

    def test_stale_fingerprint_and_non_output_lines_refuse_retrieval(self):
        result = self.write_outputs(['ERROR: original'])
        fingerprint = result['diagnostics'][0]['record_sha256']
        self.write_outputs(['ERROR: changed'])
        with self.assertRaisesRegex(ValueError, 'Evidence changed'):
            retrieve(self.log, 1, fingerprint)
        self.log.write_text('null\n')
        with self.assertRaisesRegex(ValueError, 'not a tool response'):
            retrieve(self.log, 1, fingerprint)

    def test_usage_only_writes_nothing_and_does_not_need_project_inventory(self):
        self.write_outputs(['ERROR: marker'])
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'), '--project',
            str(self.root), '--session', str(self.log), '--usage-only'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsNone(json.loads(proc.stdout)['usage'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_audit_only_writes_reports_and_never_executes_log_commands(self):
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True, capture_output=True)
        source = self.root / 'main.py'; source.write_text('value = 1\n')
        instructions = self.root / 'AGENTS.md'; instructions.write_text('Keep tests.\n')
        self.log.write_text(json.dumps({'type': 'response_item', 'payload': {
            'type': 'function_call', 'name': 'exec_command',
            'arguments': 'touch ' + str(self.root / 'should-not-exist')}}) + '\n')
        before = {p.name: p.read_bytes() for p in (source, instructions, self.log)}
        proc = subprocess.run([sys.executable, str(SCRIPTS / 'audit.py'), '--project',
            str(self.root), '--session', str(self.log)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in (source, instructions, self.log)})
        self.assertFalse((self.root / 'should-not-exist').exists())
        self.assertEqual({p.name for p in (self.root / '.token-audit').iterdir()},
                         {'evidence.md', 'evidence.json'})

    def test_marker_is_candidate_not_a_success_verdict(self):
        result = self.write_outputs(['example error message', 'tests look good'])
        self.assertEqual(result['diagnostic_count'], 1)
        self.assertNotIn('success', result)
        self.assertTrue(any('Absence is not success' in text for text in result['limits']))

    def test_query_pages_diagnostics_without_exporting_unrelated_fields(self):
        result = self.write_outputs(['ERROR: local-only text'] * 22)
        report = {'session': result, 'project': {'files': [{'path': 'private-file'}]}}
        page = select(report, 'diagnostics')
        self.assertEqual(len(page['rows']), 3)
        self.assertEqual(page['total'], 22)
        self.assertEqual(page['next_offset'], 3)
        self.assertNotIn('private-file', json.dumps(page))
        self.assertNotIn('local-only text', json.dumps(page))
        self.assertEqual(select(report, 'diagnostics', offset=21)['next_offset'], None)
        self.assertEqual(select(report, 'diagnostics', offset=21)['rows'][0]['line'], 22)
        with self.assertRaises(ValueError):
            select(report, 'diagnostics', limit=1000)
