"""Validate the benchmark's negative controls as well as its favorable case."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from benchmark import benchmark, source_fingerprint


class PublishedEvidenceTests(unittest.TestCase):
    def test_published_measurement_matches_current_source_fingerprint(self):
        artifact = Path(__file__).resolve().parents[1] / 'site/benchmark.txt'
        self.assertEqual(json.loads(artifact.read_text())['source_sha256'], source_fingerprint(),
                         'Regenerate the benchmark and update the website when its inputs change.')


@unittest.skipUnless(importlib.util.find_spec('tiktoken'), 'optional tiktoken is not installed')
class BenchmarkTests(unittest.TestCase):
    def test_representation_and_information_loss_controls(self):
        result = benchmark()
        cases = {case['case']: case for case in result['cases']}
        self.assertGreater(cases['tiny']['skill_plus_evidence_text_tokens'], cases['tiny']['raw_log_text_tokens'])
        self.assertGreater(cases['verbose']['summary_reduction_percent'], 0)
        for case in cases.values():
            self.assertTrue(all(case['metadata_checks'].values()))
            self.assertFalse(case['critical_error_body_preserved'])
            self.assertTrue(case['critical_error_in_diagnostics'])
            self.assertTrue(case['critical_error_recovered_exactly'])
            self.assertLess(case['usage_only_cli_text_tokens'], case['raw_log_text_tokens'])
            self.assertLess(case['targeted_usage_only_text_tokens'], case['evidence_markdown_text_tokens'])
        self.assertTrue(cases['tiny']['critical_error_metadata_in_top15'])
        self.assertFalse(cases['crowded']['critical_error_metadata_in_top15'])
