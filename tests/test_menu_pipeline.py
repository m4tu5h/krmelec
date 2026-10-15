"""Offline workflow tests: retries and recovery must not duplicate paid requests."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import menu_pipeline as pipeline
from tavily_agent import ResearchMenu


TARGET = date(2026, 10, 13)
RESTAURANT = {'name': 'Test', 'address': 'Test address', 'domain': 'example.com',
              'website': 'https://example.com/'}
URL = 'https://example.com/menu.pdf'
TEXT = 'DENNÉ MENU 12.10. – 16.10.2026\nUTOROK\nKuracie cestoviny 7,50 €'


def extraction():
    return ResearchMenu(confirmed_date=TARGET.isoformat(), date_evidence='12.10. – 16.10.2026',
                        date_source_url=URL, notes=[], meals=[{
                            'name': 'Kuracie cestoviny', 'labels': ['hydina', 'cestoviny'],
                            'price_eur': 7.5, 'source_url': URL, 'soups': [],
                            'evidence': 'Kuracie cestoviny 7,50 €', 'day_evidence': 'UTOROK'}])


def retrieved(restaurant=None):
    return {'restaurant': dict(restaurant or RESTAURANT), 'requested_date': TARGET.isoformat(),
            'sources': [{'url': URL, 'content': TEXT, 'kind': 'pdf'}], 'errors': []}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'diagnostics/latest-run.json'
        self.client = Mock()
        self.client.responses.parse.side_effect = lambda **kwargs: Mock(output_parsed=extraction())

    def run_extraction(self, sources=None, restaurants=None, **kwargs):
        return pipeline.extract_menus(sources or [retrieved()], restaurants or [RESTAURANT], TARGET,
                                      self.client, 'test-model', self.path, **kwargs)

    def test_verified_reuse_failed_retry_and_explicit_model_comparison(self):
        results = self.run_extraction()
        self.assertEqual(results[0]['status'], 'verified')
        self.assertEqual(results[0]['meals'][0]['price_eur'], 7.5)
        self.run_extraction(previous_results=results)
        self.assertEqual(self.client.responses.parse.call_count, 1)
        results[0]['status'] = 'needs_review'
        results[0]['reason'] = 'Missing soup options'
        results = self.run_extraction(previous_results=results)
        sent = self.client.responses.parse.call_args.kwargs
        self.assertNotIn('tools', sent)
        self.assertEqual(json.loads(sent['input'])['previous_validation_error'], 'Missing soup options')
        self.run_extraction(previous_results=results, retry_failed_only=False)
        self.assertEqual(self.client.responses.parse.call_count, 3)

    def test_one_failure_retries_only_one_of_four_restaurants(self):
        restaurants = [dict(RESTAURANT, name=f'Restaurant {i}') for i in range(4)]
        sources = [retrieved(r) for r in restaurants]
        results = self.run_extraction(sources, restaurants)
        results[0]['status'] = 'needs_review'
        self.client.reset_mock()
        retried = self.run_extraction(sources, restaurants, previous_results=results)
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.assertEqual(len(retried), 4)
        self.assertTrue(all(r['status'] == 'verified' for r in retried))

    def test_changed_content_invalidates_reuse_and_empty_sources_skip_api(self):
        results = self.run_extraction()
        changed = retrieved()
        changed['sources'][0]['content'] += '\nUpdated menu notice'
        self.run_extraction([changed], previous_results=results)
        self.assertEqual(self.client.responses.parse.call_count, 2)
        changed['sources'] = []
        result = self.run_extraction([changed], previous_results=results)[0]
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(self.client.responses.parse.call_count, 2)

    def test_local_failure_recovers_from_disk_without_another_request(self):
        with patch.object(pipeline, 'validate_extraction', side_effect=RuntimeError('Local failure')):
            with self.assertRaisesRegex(RuntimeError, 'Local failure'):
                self.run_extraction()
        pending = self.path.with_name('pending-extraction.json')
        self.assertTrue(pending.exists())
        results = pipeline.recover_extraction(self.path)
        self.assertEqual(results[0]['status'], 'verified')
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.assertEqual(json.loads(self.path.read_text())['menu_results'][0]['status'], 'verified')

    def test_request_failure_is_not_automatically_retried(self):
        self.client.responses.parse.side_effect = RuntimeError('API unavailable')
        with self.assertRaisesRegex(RuntimeError, 'API unavailable'):
            self.run_extraction()
        self.assertEqual(self.client.responses.parse.call_count, 1)
        self.assertEqual(json.loads(self.path.read_text())['menu_results'][0]['status'], 'needs_review')

    def test_wrong_date_or_restaurant_fails_before_paid_requests(self):
        wrong = retrieved()
        wrong['requested_date'] = '2026-10-12'
        with self.assertRaisesRegex(ValueError, 'different requested date'):
            self.run_extraction([wrong])
        wrong = retrieved(dict(RESTAURANT, address='Other address'))
        with self.assertRaisesRegex(ValueError, 'changing restaurant selection'):
            self.run_extraction([wrong])
        self.client.responses.parse.assert_not_called()

    def test_search_returns_links_and_retrieval_uses_actual_sources(self):
        search_client = Mock()
        search_client.post.return_value.json.return_value = {
            'results': [{'url': URL, 'title': 'Menu', 'content': 'Untrusted search snippet'}],
            'usage': {'credits': 1}}
        searches = pipeline.search_restaurants([RESTAURANT], TARGET, 'test-key', client=search_client)
        self.assertNotIn('content', searches[0]['sources'][0])
        payload = search_client.post.call_args.kwargs['json']
        self.assertEqual(payload['search_depth'], 'basic')
        self.assertFalse(payload['include_answer'])
        with patch.object(pipeline, 'retrieve_menu_sources', return_value=retrieved()) as fetch:
            sources = pipeline.retrieve_restaurants(searches, [RESTAURANT], TARGET)
            fetch.assert_called_once_with(RESTAURANT, searches[0]['sources'])
        self.assertEqual(sources[0]['requested_date'], TARGET.isoformat())
        self.assertEqual(sources[0]['sources'][0]['content'], TEXT)
        self.client.responses.parse.assert_not_called()


if __name__ == '__main__':
    unittest.main()
