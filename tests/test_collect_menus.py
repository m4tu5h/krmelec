"""Manual command checks with fake providers; no paid requests."""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import collect_menus as command


class CollectionCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.restaurant = {'name': 'Test', 'address': 'Address', 'domain': 'example.com',
                           'website': 'https://example.com/', 'menu_page': 'https://example.com/menu'}
        (self.root / 'restaurants.json').write_text(json.dumps([self.restaurant]))
        self.target = date(2026, 10, 13)
        self.meal = {'name': 'Lunch', 'restaurant': 'Test', 'address': 'Address', 'price_eur': 7.5}
        self.record = {'restaurant': self.restaurant, 'requested_date': self.target.isoformat(),
                       'status': 'verified', 'meals': [self.meal]}

    def test_success_saves_and_second_run_skips_paid_services(self):
        with patch.object(command.pipeline, 'search_restaurants', return_value=[]) as search, \
             patch.object(command.pipeline, 'retrieve_restaurants', return_value=[]), \
             patch.object(command.pipeline, 'extract_menus', return_value=[self.record]) as extract:
            self.assertEqual(command.collect(self.root, self.target, 'test', 'fake', Mock()), 0)
            saved = json.loads((self.root / 'menus.json').read_text())
            self.assertEqual(saved['meals'], [self.meal])
            self.assertEqual(command.collect(self.root, self.target, 'test', 'fake', Mock()), 0)
            search.assert_called_once()
            extract.assert_called_once()
            self.assertEqual(command.collect(self.root, self.target, 'test', 'fake', Mock(), force=True), 0)
            self.assertEqual(search.call_count, 2)
            self.assertFalse(extract.call_args.kwargs['retry_failed_only'])

    def test_failed_validation_keeps_existing_app_file(self):
        original = '{"requested_date": "2026-10-12", "meals": []}'
        output = self.root / 'menus.json'
        output.write_text(original)
        failed = dict(self.record, status='needs_review', meals=[], reason='Unproven date')
        with patch.object(command.pipeline, 'search_restaurants', return_value=[]), \
             patch.object(command.pipeline, 'retrieve_restaurants', return_value=[]), \
             patch.object(command.pipeline, 'extract_menus', return_value=[failed]):
            self.assertEqual(command.collect(self.root, self.target, 'test', 'fake', Mock()), 1)
        self.assertEqual(output.read_text(), original)

    def test_overlapping_command_is_blocked_and_lock_releases(self):
        lock = self.root / 'collection.lock'
        with command.collection_lock(lock):
            with self.assertRaisesRegex(ValueError, 'already running'):
                with command.collection_lock(lock):
                    self.fail('Second command acquired the lock')
        with command.collection_lock(lock):
            pass

    def test_check_mode_makes_no_requests_and_missing_keys_fail_early(self):
        with patch.dict(os.environ, {'OPENAI_API_KEY': 'fake', 'TAVILY_API_KEY': 'fake'}, clear=True), \
             patch.object(command, 'OpenAI') as client, \
             patch.object(command.pipeline, 'search_restaurants') as search:
            self.assertEqual(command.main(['--check'], root=self.root), 0)
            client.assert_not_called()
            search.assert_not_called()
        with patch.dict(os.environ, {}, clear=True), patch.object(command, 'OpenAI') as client:
            self.assertEqual(command.main([], root=self.root), 1)
            client.assert_not_called()

    def test_shared_configuration_matches_successful_saved_restaurants(self):
        root = Path(command.__file__).resolve().parent
        restaurants = command.pipeline.load_restaurants(root / 'restaurants.json')
        self.assertEqual(len(restaurants), 4)
        self.assertTrue(all(r['allow_yearless_dates'] for r in restaurants))
        self.assertEqual(restaurants[0]['menu_page'], 'https://www.spilkarestaurant.sk/ponuka/')
        path = self.root / 'bad-restaurants.json'
        path.write_text(json.dumps([restaurants[0], restaurants[0]]))
        with self.assertRaisesRegex(ValueError, 'unique'):
            command.pipeline.load_restaurants(path)


if __name__ == '__main__':
    unittest.main()
