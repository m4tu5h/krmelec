"""Fetch real menu pages and follow likely daily-menu/PDF links without AI calls."""
from __future__ import annotations

import ipaddress
import re
import socket
from html.parser import HTMLParser
from io import BytesIO
from datetime import date
from urllib.parse import urljoin, urlsplit, urldefrag

import httpx
from pypdf import PdfReader
from pypdf.errors import PyPdfError


class MenuHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.links = []
        self.hidden = 0
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript'):
            self.hidden += 1
        if tag == 'a' and attrs.get('href'):
            self.anchor = [attrs['href'], '']
        if tag in ('iframe', 'embed', 'object'):
            target = attrs.get('src') or attrs.get('data')
            if target:
                self.links.append((target, 'embedded menu'))
        if tag in ('p', 'div', 'li', 'br', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a' and self.anchor:
            self.links.append(tuple(self.anchor))
            self.anchor = None
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'tr'):
            self.text.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
            if self.anchor:
                self.anchor[1] += data


def menu_link_score(url, label=''):
    text = (url + ' ' + label).casefold()
    if any(word in text for word in ('cookie', 'privacy', 'blackhole', 'facebook', 'instagram',
                                     'napoj', 'nápoj', 'vínna', 'vinna', 'a-la-carte', 'jedalny-list', 'jedálny lístok')):
        return 0
    if re.search(r'denn[eéýy]|obed|lunch|daily|tyzd|týžd', text):
        return 3
    if 'ponuka' in text or '.pdf' in text:
        return 2
    if 'menu' in text:
        return 1
    return 0


def require_public_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('Only public HTTP(S) URLs are allowed')
    if parts.port not in (None, 80, 443):
        raise ValueError('Unsupported port')
    addresses = socket.getaddrinfo(parts.hostname, parts.port or 443)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('Private/local URL refused')


def download(client, url):
    current = url
    for _ in range(6):
        require_public_url(current)
        with client.stream('GET', current, follow_redirects=False) as response:
            if response.is_redirect:
                current = urljoin(current, response.headers['location'])
                continue
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 8_000_000:
                    raise ValueError('Menu source exceeds 8 MB')
                chunks.append(chunk)
            return current, response.headers.get('content-type', '').split(';')[0], b''.join(chunks)
    raise ValueError('Too many redirects')



def branch_url_pattern(restaurant):
    if restaurant.get('menu_url_pattern'):
        return restaurant['menu_url_pattern']
    if restaurant.get('domain') == 'klubovna.sk' and restaurant.get('name') == 'Centrálna Klubovňa':
        return r'/KLUBOVNA_CK_DENNE_MENU_'
    return None


def retrieve_menu_sources(restaurant, search_sources, max_pages=8, client=None):
    """Return independently fetched text, never stale Tavily result snippets.

    Only same-site search hits seed retrieval. Linked PDF assets may be external.
    Image-only menus are reported as unsupported, not silently passed off as text.
    """
    domain = restaurant['domain']
    def official(url):
        host = urlsplit(url).hostname or ''
        return host == domain or host.endswith('.' + domain)

    pattern = branch_url_pattern(restaurant)
    def branch_match(url):
        return not (pattern and urlsplit(url).path.lower().endswith('.pdf')) or bool(re.search(pattern, url, re.I))

    seed = restaurant.get('menu_page') or restaurant['website']
    hits = [s['url'] for s in search_sources if s.get('url') and official(s['url']) and branch_match(s['url'])
            and menu_link_score(s['url'], s.get('title', ''))]
    # Visit the known page first, then high-signal links discovered on it.
    queue = [(seed, 0)] + [(url, 0) for url in hits[:3]]
    visited, sources, errors = set(), [], []
    owned = client is None
    client = client or httpx.Client(timeout=30, trust_env=False,
                                   headers={'User-Agent': 'KrmelecMenuPrototype/0.2'})
    try:
        while queue and len(visited) < max_pages:
            url, depth = queue.pop(0)
            url = urldefrag(url)[0]
            if url in visited:
                continue
            visited.add(url)
            try:
                resolved, mime, raw = download(client, url)
                links = []
                if raw.startswith(b'%PDF-') or mime == 'application/pdf':
                    reader = PdfReader(BytesIO(raw))
                    text = '\n'.join(page.extract_text() or '' for page in reader.pages)
                    kind = 'pdf'
                elif mime in ('text/html', 'application/xhtml+xml', 'text/plain'):
                    parser = MenuHTML()
                    parser.feed(raw.decode('utf-8', errors='replace'))
                    text = ''.join(parser.text)
                    text = re.sub(r'\n[ \t]*\n+', '\n\n', text).strip()
                    links = parser.links
                    kind = 'html'
                else:
                    raise ValueError('Unsupported source format (image menus need a later vision step): ' + mime)
                if text.strip():
                    sources.append({'url': resolved, 'requested_url': url, 'content': text[:45000],
                                    'truncated': len(text) > 45000, 'kind': kind})
                else:
                    errors.append({'url': url, 'error': 'No readable text; possible scanned PDF'})
                if depth < 2:
                    candidates = []
                    for href, label in links:
                        target = urldefrag(urljoin(resolved, href))[0]
                        if urlsplit(target).scheme not in ('http', 'https'):
                            continue
                        score = menu_link_score(target, label)
                        # External traversal is limited to directly linked PDF assets.
                        if score and branch_match(target) and (official(target) or urlsplit(target).path.lower().endswith('.pdf')):
                            candidates.append((score, target, depth + 1))
                    candidates.sort(key=lambda item: item[0], reverse=True)
                    queue = [(target, level) for _, target, level in candidates[:8]] + queue
            except (httpx.HTTPError, ValueError, OSError, PyPdfError) as error:
                errors.append({'url': url, 'error': str(error)})
    finally:
        if owned:
            client.close()
    return {'restaurant': dict(restaurant), 'sources': sources, 'errors': errors}


WEEKDAYS = ('pondelok', 'utorok', 'streda', 'štvrtok', 'piatok', 'sobota', 'nedeľa')


def prepare_model_sources(retrieved, target: date):
    """Reduce ambiguity using Python's actual weekday, without inventing date evidence.

    Validation still uses the original fetched text. Unrecognised layouts remain
    unchanged; we never infer a menu year from copyright text.
    """
    pattern = branch_url_pattern(retrieved['restaurant'])
    sources = [dict(s) for s in retrieved['sources'] if not pattern or s['kind'] != 'pdf'
               or re.search(pattern, s['url'], re.I)]
    # A known branch's PDFs are more useful than a homepage listing every branch.
    if pattern and any(s['kind'] == 'pdf' for s in sources):
        sources = [s for s in sources if s['kind'] == 'pdf']
    for source in sources:
        text = source['content']
        headers = list(re.finditer(
            r'(?im)^[ \t]*(?:(\d{1,2})\.[ \t]*(\d{1,2})\.[ \t]*(20\d{2})[ \t]*[-–][ \t]*)?'
            r'(PONDELOK|UTOROK|STREDA|ŠTVRTOK|PIATOK|SOBOTA|NEDEĽA)(?(1)[^\n]*|[ \t]*)$', text))
        if not headers:
            continue
        matching = []
        for i, header in enumerate(headers):
            day, month, year, weekday = header.groups()
            if year:
                try:
                    matches = date(int(year), int(month), int(day)) == target
                except ValueError:
                    matches = False
            else:
                matches = weekday.casefold() == WEEKDAYS[target.weekday()]
            if matches:
                end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
                matching.append(text[header.start():end])
        if not matching:
            # Do not feed other weekdays to the extractor when sections are known.
            source['content'] = text[:headers[0].start()] + '\nNo section for requested date.\n'
            continue
        # Retain global menu conditions/date range. PDF date ranges may be in the footer.
        context = text[:headers[0].start()]
        dated_week = re.findall(r'(?m)^.*\d{1,2}\.\s*\d{1,2}\.\s*[-–]\s*\d{1,2}\.\s*\d{1,2}\.\s*20\d{2}.*$', text)
        global_lines = [line for line in text.splitlines() if any(phrase in line.casefold() for phrase in
                        ('cena dennej polievky samostatne', 'denné menu podávame', 'celý týždeň'))]
        source['content'] = context + '\n' + '\n'.join(matching + dated_week + global_lines)
    return sources
