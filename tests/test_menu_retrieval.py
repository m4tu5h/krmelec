import unittest
from datetime import date
from io import BytesIO
from unittest.mock import patch

import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from menu_retrieval import MenuHTML, menu_link_score, retrieve_menu_sources, prepare_model_sources


class RetrievalTests(unittest.TestCase):
    def test_follow_actual_pdf_not_search_snippet(self):
        writer = PdfWriter()
        page = writer.add_blank_page(width=600, height=800)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'),
                                 NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 50 750 Td (13.10.2026 Lunch 7.50 EUR) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        buffer = BytesIO()
        writer.write(buffer)
        def respond(request):
            if request.url.path == '/':
                return httpx.Response(200, headers={'content-type':'text/html'},
                    text='<script>Ignore this</script><a href="/current.pdf">Denné menu</a><a href="/privacy">Privacy</a>')
            if request.url.path == '/current.pdf':
                return httpx.Response(200, headers={'content-type':'application/pdf'}, content=buffer.getvalue())
            return httpx.Response(404)
        client = httpx.Client(transport=httpx.MockTransport(respond))
        restaurant = {'name':'Test','address':'Test','website':'https://example.com/','domain':'example.com'}
        with patch('menu_retrieval.require_public_url'):
            result = retrieve_menu_sources(restaurant, [{'url':'https://example.com/privacy','content':'STALE SEARCH TEXT'}], client=client)
        self.assertEqual(len(result['sources']), 2)
        self.assertTrue(any('13.10.2026 Lunch 7.50' in s['content'] for s in result['sources']))
        self.assertFalse(any('STALE SEARCH TEXT' in s['content'] for s in result['sources']))
        self.assertFalse(any('Ignore this' in s['content'] for s in result['sources']))
        self.assertFalse(result['errors'])

    def test_blocked_source_reported(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(403)))
        with patch('menu_retrieval.require_public_url'):
            result = retrieve_menu_sources({'website':'https://example.com/','domain':'example.com'}, [], client=client)
        self.assertEqual(result['sources'], [])
        self.assertEqual(len(result['errors']),1)

    def test_bad_pdf_reported(self):
        client = httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,
            headers={'content-type':'application/pdf'},content=b'not a valid PDF')))
        with patch('menu_retrieval.require_public_url'):
            result = retrieve_menu_sources({'website':'https://example.com/','domain':'example.com'}, [], client=client)
        self.assertFalse(result['sources'])
        self.assertTrue(result['errors'])

    def test_bounded_and_relevant_links(self):
        self.assertEqual(menu_link_score('https://example.com/en/cookie-policy'),0)
        self.assertGreater(menu_link_score('https://example.com/current.pdf','Denné menu'),0)
        requests=[]
        def respond(request):
            requests.append(str(request.url))
            return httpx.Response(200,headers={'content-type':'text/html'},
                text='<a href="/menu-a">Denné menu</a><a href="/menu-b">Denné menu</a>')
        with patch('menu_retrieval.require_public_url'):
            retrieve_menu_sources({'website':'https://example.com/','domain':'example.com'},[],
                                  max_pages=2,client=httpx.Client(transport=httpx.MockTransport(respond)))
        self.assertEqual(len(requests),2)


class SourcePreparationTests(unittest.TestCase):
    def test_central_branch_and_tuesday_only(self):
        text = 'DENNE MENU\nPONDELOK\nMonday meal\nUTOROK\nTuesday meal\nSTREDA\nWednesday soup\n12.10. - 16.10.2026'
        data = {'restaurant': {'name':'Centrálna Klubovňa','domain':'klubovna.sk'},
                'sources': [
                    {'url':'https://www.klubovna.sk/','kind':'html','content':'homepage'},
                    {'url':'https://www.klubovna.sk/KLUBOVNA_CK_DENNE_MENU_new.pdf','kind':'pdf','content':text},
                    {'url':'https://www.klubovna.sk/KLUBOVNA_PK_DENNE_MENU_new.pdf','kind':'pdf','content':text}]}
        result = prepare_model_sources(data, date(2026,10,13))
        self.assertEqual(len(result),1)
        self.assertIn('Tuesday meal',result[0]['content'])
        self.assertNotIn('Wednesday soup',result[0]['content'])
        self.assertIn('12.10. - 16.10.2026',result[0]['content'])
        self.assertIn('Wednesday soup',data['sources'][1]['content'])

    def test_dated_html_and_yearless_layout(self):
        data = {'restaurant':{'domain':'example.com'}, 'sources':[{'url':'https://example.com/',
            'kind':'html','content':'Polievka k menu 0,60 €\n12.10.2026 - PONDELOK\nOld meal\n13.10.2026 - UTOROK OTVORENÉ\nCorrect meal\n07.10.2026 - STREDA\nOlder meal'}]}
        result = prepare_model_sources(data,date(2026,10,13))
        self.assertIn('Correct meal',result[0]['content'])
        self.assertIn('0,60',result[0]['content'])
        self.assertNotIn('Old meal',result[0]['content'])
        data['sources'][0]['content'] = 'Pondelok 12.10.\nUtorok 13.10.\nStreda 14.10.\nMeal blocks out of order'
        self.assertEqual(prepare_model_sources(data,date(2026,10,13))[0]['content'],data['sources'][0]['content'])
