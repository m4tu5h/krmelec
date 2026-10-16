"""Offline checks for the Tavily-only workflow; no real API requests."""
import ast
import copy
import json
import tempfile
import unittest
import httpx
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

from tavily_agent import ResearchMenu, TavilyMenus, check_menu, covers_date, save_menus, research_output_schema, url_key, prepare_extraction

ROOT = Path(__file__).resolve().parents[1]
RESTAURANT = {'name': 'Test', 'address': 'Test address', 'website': 'https://example.com/', 'domain': 'example.com'}
URL = 'https://example.com/menu.pdf'
TEXT = 'DENNÉ MENU 12.10. – 16.10.2026\nUTOROK\nKuracie cestoviny 7,50 €\nVývar 0,2 l k menu 0,60 €'


def valid_menu():
    return ResearchMenu(confirmed_date='2026-10-13', date_evidence='12.10. – 16.10.2026',
        date_source_url=URL, notes=[], meals=[{
            'name': 'Kuracie cestoviny', 'labels': ['hydina', 'cestoviny'],
            'price_eur': 7.5, 'portion': '250 g', 'source_url': URL,
            'evidence': 'Kuracie cestoviny 7,50 €', 'day_evidence': 'UTOROK',
            'soups': [{'name': 'Vývar', 'portion': '0,2 l', 'additional_price_eur': 0.6,
                       'evidence': 'Vývar 0,2 l k menu 0,60 €'}]}])


class TavilyResearchTests(unittest.TestCase):
    def test_zero_soup_claim_uses_explicit_source_backed_with_menu_rule(self):
        menu = valid_menu()
        soup = menu.meals[0].soups[0]
        soup.additional_price_eur = 0
        soup.evidence = 'Vývar'
        soup.price_evidence = 'Polievka 0,60 € k menu obsah 0,2 l alebo samostatne cena 2,80 € obsah 0,4 l'
        text = TEXT + '\n' + soup.price_evidence
        prepared = prepare_extraction(menu, {URL: text})
        self.assertEqual(prepared.meals[0].soups[0].additional_price_eur, 0.6)
        self.assertEqual(soup.additional_price_eur, 0, 'Raw response must remain unchanged')
        self.assertTrue(any('explicit with-menu' in n for n in prepared.notes))
        check_menu(prepared, date(2026,10,13), RESTAURANT, {URL: text})
        soup.additional_price_eur = 0.9
        prepared = prepare_extraction(menu, {URL: text})
        with self.assertRaisesRegex(ValueError, 'Soup surcharge lacks price evidence'):
            check_menu(prepared, date(2026,10,13), RESTAURANT, {URL: text})

    def test_zero_soup_claim_is_not_repaired_using_unrelated_or_missing_prices(self):
        for quote in ('Polievka 2,80 € samostatne', 'Kofola 0,60 € k menu',
                      'Polievka 0,60 € samostatne alebo k menu podľa ponuky'):
            menu = valid_menu()
            soup = menu.meals[0].soups[0]
            soup.additional_price_eur = 0
            soup.evidence = 'Vývar'
            soup.price_evidence = quote
            text = TEXT + '\n' + quote
            prepared = prepare_extraction(menu, {URL: text})
            self.assertEqual(prepared.meals[0].soups[0].additional_price_eur, 0)
            with self.assertRaisesRegex(ValueError, 'Zero soup surcharge'):
                check_menu(prepared, date(2026,10,13), RESTAURANT, {URL: text})
        soup.price_evidence = 'Polievka 0,70 € k menu'
        prepared = prepare_extraction(menu, {URL: TEXT})
        self.assertEqual(prepared.meals[0].soups[0].additional_price_eur, 0)
        with self.assertRaisesRegex(ValueError, 'Soup price evidence missing'):
            check_menu(prepared, date(2026,10,13), RESTAURANT, {URL: TEXT})

    def test_soup_ellipsis_restores_only_a_literal_same_line_suffix(self):
        menu = valid_menu()
        soup = menu.meals[0].soups[0]
        original = soup.evidence
        soup.evidence = soup.price_evidence = 'POLIEVKY ... ' + original
        text = TEXT + '\nPOLIEVKY Boršč 1,99 € / ' + original
        repaired = prepare_extraction(menu, {URL: text})
        self.assertEqual(repaired.meals[0].soups[0].evidence, original)
        check_menu(repaired, date(2026,10,13), RESTAURANT, {URL: text})
        self.assertIn('...', soup.evidence, 'Raw model response must remain unchanged')
        for bad_text in (TEXT, TEXT + '\nPOLIEVKY\n' + original):
            with self.assertRaisesRegex(ValueError, 'Soup evidence missing'):
                check_menu(prepare_extraction(menu, {URL: bad_text}), date(2026,10,13), RESTAURANT, {URL: bad_text})
        soup.evidence = soup.price_evidence = 'POLIEVKY ... Vývar 0,2 l k menu 0,70 €'
        with self.assertRaisesRegex(ValueError, 'Soup evidence missing'):
            check_menu(prepare_extraction(menu, {URL: text}), date(2026,10,13), RESTAURANT, {URL: text})

    def test_omitted_allergen_line_is_restored_without_skipping_other_content(self):
        menu = valid_menu()
        for gap in ('1,3,7', '7,1,3'):
            text = TEXT.replace('Kuracie cestoviny 7,50 €', f'Kuracie cestoviny\n\n{gap}\n\n7,50 €')
            prepared = prepare_extraction(menu, {URL: text})
            self.assertIn(gap, prepared.meals[0].evidence)
            check_menu(prepared, date(2026,10,13), RESTAURANT, {URL: text})
        for gap in ('Other meal', 'STREDA', '15,20'):
            text = TEXT.replace('Kuracie cestoviny 7,50 €', f'Kuracie cestoviny\n{gap}\n7,50 €')
            with self.assertRaisesRegex(ValueError, 'Meal evidence missing'):
                check_menu(prepare_extraction(menu, {URL: text}), date(2026,10,13), RESTAURANT, {URL: text})
        text = TEXT.replace('Kuracie cestoviny 7,50 €', 'Kuracie cestoviny\n1,3,7\n8,50 €')
        with self.assertRaisesRegex(ValueError, 'Meal evidence missing'):
            check_menu(prepare_extraction(menu, {URL: text}), date(2026,10,13), RESTAURANT, {URL: text})

    def test_rizoto_pasta_label_requires_a_stated_pasta_ingredient(self):
        menu = valid_menu()
        meal = menu.meals[0]
        meal.name = 'Rizoto'
        meal.evidence = 'Rizoto s kuracím mäsom a zeleninou 7,50 €'
        prepared = prepare_extraction(menu, {URL: TEXT + '\n' + meal.evidence})
        self.assertNotIn('cestoviny', prepared.meals[0].labels)
        self.assertIn('cestoviny', meal.labels)
        meal.evidence = 'Rizoto z cestoviny orzo 7,50 €'
        prepared = prepare_extraction(menu, {URL: TEXT + '\n' + meal.evidence})
        self.assertIn('cestoviny', prepared.meals[0].labels)

    def test_evidence_formatting_repairs_preserve_raw_response(self):
        menu = valid_menu()
        menu.date_evidence = '\"12.10. – 16.10.2026\" and heading \"UTOROK\"'
        menu.meals[0].evidence = '\"' + menu.meals[0].evidence + '\"'
        repaired = prepare_extraction(menu, {URL: TEXT})
        self.assertEqual(len(check_menu(repaired, date(2026,10,13), RESTAURANT, {URL: TEXT})), 1)
        self.assertIn('and heading', menu.date_evidence)
        menu.date_evidence = '\"12.10. – 16.10.2025\" and heading \"UTOROK\"'
        with self.assertRaises(ValueError):
            check_menu(prepare_extraction(menu, {URL: TEXT}), date(2026,10,13), RESTAURANT, {URL: TEXT})

    def test_soup_price_repairs_are_conservative(self):
        menu = valid_menu()
        soup = menu.meals[0].soups[0]
        soup.price_evidence = 'Cena samostatne 2,60 €'
        sources = {URL: TEXT + '\nCena samostatne 2,60 €'}
        repaired = prepare_extraction(menu, sources)
        self.assertEqual(repaired.meals[0].soups[0].price_evidence, soup.evidence)
        check_menu(repaired, date(2026,10,13), RESTAURANT, sources)
        soup.evidence = 'Vývar 0,2 l'
        soup.price_evidence = soup.evidence
        soup.additional_price_eur = 0
        repaired = prepare_extraction(menu, sources)
        self.assertIsNone(repaired.meals[0].soups[0].additional_price_eur)
        self.assertTrue(any('unsupported free' in n for n in repaired.notes))
        soup.evidence = 'Cena samostatne 2,60 €'
        soup.price_evidence = soup.evidence
        self.assertEqual(prepare_extraction(menu, sources).meals[0].soups[0].additional_price_eur, 0)
        soup.additional_price_eur = 0.6
        with self.assertRaises(ValueError):
            check_menu(prepare_extraction(menu, sources), date(2026,10,13), RESTAURANT, sources)

    def test_empty_soups_conflicting_with_notes_requires_review(self):
        menu = valid_menu()
        menu.meals[0].soups = []
        menu.notes = ['Soups are listed at the top of the Tuesday menu.']
        with self.assertRaisesRegex(ValueError, 'every soups array is empty'):
            check_menu(menu, date(2026,10,13), RESTAURANT, {URL: TEXT})

    def test_tavily_schema_contract(self):
        schema = research_output_schema()
        self.assertEqual(set(schema), {'properties', 'required'})
        encoded = json.dumps(schema)
        self.assertNotIn('"$ref"', encoded)
        self.assertNotIn('"$defs"', encoded)
        meal = schema['properties']['meals']['items']
        self.assertEqual(meal['type'], 'object')
        self.assertIn('labels', meal['properties'])
        soup = meal['properties']['soups']['items']
        self.assertIn('additional_price_eur', soup['properties'])
        self.assertEqual(meal['properties']['price_eur']['type'], 'number')
        self.assertNotIn('price_eur', meal['required'])
        self.assertEqual(schema['properties']['confirmed_date']['type'], 'string')
        self.assertNotIn('confirmed_date', schema['required'])
        self.assertNotIn('"anyOf"', encoded)
        self.assertNotIn('"default"', encoded)
        self.assertIn('bravčové', meal['properties']['labels']['items']['description'])

        def check_properties(node):
            if not isinstance(node, dict):
                return
            for name, prop in node.get('properties', {}).items():
                self.assertIn('type', prop, name)
                self.assertIsInstance(prop['type'], str, name)
                self.assertIsInstance(prop.get('description'), str, name)
                self.assertTrue(prop['description'].strip(), name)
                self.assertLessEqual(set(prop), {'type', 'description', 'properties', 'required', 'items'})
                check_properties(prop)
            if 'items' in node:
                self.assertIn('type', node['items'])
                self.assertTrue(node['items'].get('description'))
                check_properties(node['items'])
        check_properties(schema)

    def test_omitted_optional_fields_restore_nulls(self):
        menu = ResearchMenu.model_validate({'meals': [], 'notes': ['No verified date']})
        self.assertIsNone(menu.confirmed_date)
        self.assertIsNone(menu.date_source_url)
        from tavily_agent import Meal, Soup
        meal = Meal.model_validate({'name': 'Test', 'labels': [], 'soups': [],
                                    'source_url': URL, 'evidence': 'Test', 'day_evidence': 'UTOROK'})
        self.assertIsNone(meal.price_eur)
        self.assertIsNone(meal.model_dump()['portion'])
        soup = Soup.model_validate({'name': 'Test', 'evidence': 'Test'})
        self.assertIsNone(soup.model_dump()['additional_price_eur'])

    def test_slovak_and_iso_dates(self):
        target = date(2026, 10, 13)
        for quote in ('13.10.2026', '2026-10-13', '12. – 16.10.2026', '12.10.2026 - 16.10.2026'):
            self.assertTrue(covers_date(quote, target), quote)
        for quote in ('13.09.2026', '13.10.', '99.10.2026', '12.10.2025 - 16.10.2025'):
            self.assertFalse(covers_date(quote, target), quote)

    def test_old_month_cannot_be_relabelled(self):
        menu = valid_menu()
        menu.date_evidence = '13.09.2026'
        with self.assertRaisesRegex(ValueError, 'full date'):
            check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: '13.09.2026\n' + TEXT})

    def test_invented_quote_rejected(self):
        menu = valid_menu()
        menu.date_evidence = '13.10.2026'
        with self.assertRaises(ValueError):
            check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: TEXT})

    def test_wrong_day_rejected(self):
        menu = valid_menu()
        menu.meals[0].day_evidence = 'PONDELOK'
        with self.assertRaises(ValueError):
            check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: TEXT+'\nPONDELOK'})

    def test_soup_cannot_be_free_without_evidence(self):
        menu = valid_menu()
        menu.meals[0].soups[0].additional_price_eur = 0
        with self.assertRaisesRegex(ValueError, 'Zero soup'):
            check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: TEXT})

    def test_invented_price_rejected(self):
        menu = valid_menu()
        menu.meals[0].price_eur = 8.9
        with self.assertRaisesRegex(ValueError, 'price lacks'):
            check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: TEXT})

    def test_html_entities_do_not_break_matching_quotes(self):
        menu = valid_menu()
        menu.meals[0].name = 'Kuracie prsia "Cordon Bleu"'
        menu.meals[0].evidence = 'Kuracie prsia "Cordon Bleu" 7,50 €'
        text = TEXT+'\nKuracie prsia &quot;Cordon Bleu&quot; 7,50 €'
        meals = check_menu(menu,date(2026,10,13),RESTAURANT,{URL:text})
        self.assertEqual(len(meals),1)
        menu.meals[0].evidence = 'Kuracie prsia "Cordon Bleu" 8,90 €'
        with self.assertRaises(ValueError):
            check_menu(menu,date(2026,10,13),RESTAURANT,{URL:text})

    def test_sample_only_output_rejected(self):
        menu = valid_menu()
        menu.notes = ['Only the first soup is included for illustrative clarity']
        with self.assertRaisesRegex(ValueError,'sample'):
            check_menu(menu,date(2026,10,13),RESTAURANT,{URL:TEXT})

    def test_unspecified_meat_is_not_beef(self):
        menu = valid_menu()
        menu.meals[0].name = 'Fašírky'
        menu.meals[0].evidence = 'Fašírky 7,50 €'
        menu.meals[0].labels = ['hovädzie']
        with self.assertRaisesRegex(ValueError,'Beef label'):
            check_menu(menu,date(2026,10,13),RESTAURANT,{URL:TEXT+'\nFašírky 7,50 €'})

    def test_yearless_policy_flags_matching_date(self):
        menu = valid_menu()
        menu.confirmed_date = None
        menu.date_evidence = 'Utorok 13.10.'
        menu.meals[0].day_evidence = 'Utorok 13.10.'
        source = {URL: TEXT+'\nUtorok 13.10.'}
        with patch('tavily_agent.datetime') as clock:
            clock.now.return_value.year = 2026
            meals = check_menu(menu,date(2026,10,13),dict(RESTAURANT,allow_yearless_dates=True),source)
            self.assertTrue(meals[0]['date_assumed'])
            self.assertIn('2026',meals[0]['date_note'])
            with self.assertRaises(ValueError):
                check_menu(menu,date(2026,10,13),RESTAURANT,source)
            for quote in ('Utorok 06.10.', 'Streda 13.10.', 'Utorok 13.09.', 'Utorok 13.10.2025'):
                menu.date_evidence = quote
                with self.assertRaises(ValueError):
                    check_menu(menu,date(2026,10,13),dict(RESTAURANT,allow_yearless_dates=True),
                               {URL:TEXT+'\n'+quote})
            menu.date_evidence = 'Utorok 13.10.'
            clock.now.return_value.year = 2027
            with self.assertRaises(ValueError):
                check_menu(menu,date(2026,10,13),dict(RESTAURANT,allow_yearless_dates=True),source)

    def test_separate_soup_name_and_price_evidence(self):
        menu = valid_menu()
        soup = menu.meals[0].soups[0]
        soup.evidence = 'Vývar'
        soup.price_evidence = 'Polievka 0,60 € k menu'
        meals = check_menu(menu, date(2026,10,13), RESTAURANT,
                           {URL: TEXT+'\nPolievka 0,60 € k menu'})
        self.assertEqual(meals[0]['soups'][0]['additional_price_eur'], 0.6)
        self.assertNotIn('price_evidence', meals[0]['soups'][0])
        soup.price_evidence = 'Polievka 0,70 € k menu'
        with self.assertRaises(ValueError):
            check_menu(menu, date(2026,10,13), RESTAURANT, {URL: TEXT})

    def test_soup_is_not_a_main(self):
        menu = valid_menu()
        menu.meals[0].name = 'Slepačí vývar s rezancami'
        with self.assertRaisesRegex(ValueError, 'Soup returned as a main'):
            check_menu(menu, date(2026,10,13), RESTAURANT, {URL: TEXT})

    def test_gorgonzola_is_recognized_as_cheese(self):
        menu = valid_menu()
        meal = menu.meals[0]
        meal.name = 'Kurací steak s omáčkou z gorgonzoly'
        meal.evidence = meal.name + ' 7,50 €'
        meal.labels = ['hydina', 'syr']
        meals = check_menu(menu, date(2026, 10, 13), RESTAURANT,
                           {URL: TEXT+'\n'+meal.evidence})
        self.assertIn('syr', meals[0]['labels'])

    def test_pancakes_not_labelled_cheese_from_allergens(self):
        menu = valid_menu()
        meal = menu.meals[0]
        meal.name = 'Palacinky s džemom'
        meal.evidence = 'Palacinky s džemom 7,50 € 1,3,7'
        meal.labels = ['syr']
        with self.assertRaisesRegex(ValueError, 'Cheese label'):
            check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: TEXT+'\n'+meal.evidence})

    def test_included_soup_and_unknown_price(self):
        menu = valid_menu()
        menu.meals[0].price_eur = None
        soup = menu.meals[0].soups[0]
        soup.additional_price_eur = 0
        soup.evidence = 'Vývar v cene menu'
        meals = check_menu(menu, date(2026, 10, 13), RESTAURANT, {URL: TEXT+'\nVývar v cene menu'})
        self.assertIsNone(meals[0]['price_eur'])
        self.assertEqual(meals[0]['soups'][0]['additional_price_eur'], 0)

    def test_resume_poll_retrieve_once_and_save(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.post.side_effect = [
                Mock(json=lambda: {'request_id': 'task-1', 'status': 'pending'}),
                Mock(json=lambda: {'results': [{'url': URL, 'raw_content': TEXT}], 'usage': {'credits': 1}})]
            client.get.side_effect = [
                Mock(json=lambda: {'status': 'in_progress'}),
                Mock(json=lambda: {'status': 'completed', 'content': valid_menu().model_dump(),
                                   'sources': [{'url': URL}], 'usage': {'credits': 4}})]
            agent = TavilyMenus('not-a-real-key', Path(directory)/'tasks', client)
            record = agent.start(RESTAURANT, date(2026, 10, 13))
            self.assertEqual(agent.start(RESTAURANT, date(2026, 10, 13))['request_id'], 'task-1')
            self.assertEqual(client.post.call_count, 1)
            self.assertEqual(agent.check(record)['status'], 'in_progress')
            record = agent.check(record)
            self.assertEqual(record['status'], 'verified')
            agent.check(record)
            self.assertEqual(client.post.call_count, 2)
            self.assertEqual(client.get.call_count, 2)
            payload = client.post.call_args_list[0].kwargs['json']
            self.assertEqual(payload['model'], 'mini')
            self.assertEqual(set(payload['output_schema']), {'properties', 'required'})
            self.assertNotIn('openai', client.post.call_args_list[0].args[0])
            path = Path(directory)/'menus.json'
            data = save_menus([record], [RESTAURANT], date(2026, 10, 13), path)
            self.assertEqual(set(data), {'requested_date', 'saved_at', 'meals'})
            self.assertEqual(data['meals'][0]['soups'][0]['additional_price_eur'], 0.6)
            self.assertNotIn('evidence', data['meals'][0])
            original = path.read_text()
            record['status'] = 'needs_review'
            with self.assertRaises(ValueError):
                save_menus([record], [RESTAURANT], date(2026, 10, 13), path)
            self.assertEqual(path.read_text(), original)

    def test_failed_or_empty_results_cannot_save(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'menus.json'
            path.write_text('{"keep":true}')
            for status in ('pending', 'failed', 'needs_review'):
                record = {'restaurant': RESTAURANT, 'status': status, 'requested_date': '2026-10-13'}
                with self.assertRaises(ValueError):
                    save_menus([record], [RESTAURANT], date(2026, 10, 13), path)
            self.assertEqual(json.loads(path.read_text()), {'keep': True})

    def test_uncertain_submission_not_automatically_repeated(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            client.post.side_effect = RuntimeError('Connection lost after submission')
            agent = TavilyMenus('test', Path(directory), client)
            with self.assertRaises(RuntimeError):
                agent.start(RESTAURANT, date(2026, 10, 13))
            with self.assertRaisesRegex(RuntimeError, 'uncertain'):
                agent.start(RESTAURANT, date(2026, 10, 13))
            self.assertEqual(client.post.call_count, 1)

    def test_rejection_body_visible_and_explicit_retry_allowed(self):
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            rejection = httpx.Response(400, json={'detail': 'Invalid output schema'},
                                       request=httpx.Request('POST', 'https://api.tavily.com/research'))
            client.post.side_effect = [rejection, Mock(json=lambda: {'request_id': 'fixed-task', 'status': 'pending'})]
            agent = TavilyMenus('test', Path(directory), client)
            with self.assertRaisesRegex(RuntimeError, 'Invalid output schema'):
                agent.start(RESTAURANT, date(2026, 10, 13))
            records = list(Path(directory).glob('*.json'))
            saved = json.loads(records[0].read_text())
            self.assertEqual(saved['status'], 'rejected')
            self.assertEqual(saved['http_status'], 400)
            result = agent.start(RESTAURANT, date(2026, 10, 13))
            self.assertEqual(result['request_id'], 'fixed-task')
            self.assertEqual(client.post.call_count, 2)

    def test_main_notebook_calls_reusable_workflow(self):
        nb = json.loads((ROOT/'notebooks/01_menu_agent.ipynb').read_text())
        code = '\n'.join(''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'code')
        ast.parse(code)
        for name in ['search_restaurants', 'retrieve_restaurants', 'extract_menus', 'recover_extraction']:
            self.assertIn('pipeline.' + name + '(', code)
        self.assertNotIn('client.responses.parse(', code)
        self.assertNotIn('https://api.tavily.com/search', code)
        self.assertNotIn('TavilyMenus(', code)
        self.assertIn('save_menus(', code)
