"""Conservative official-publisher chapter monitor; no X scraping."""
import asyncio
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

HOME = 'https://tonarinoyj.jp/'

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.text = []
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.href = dict(attrs).get('href')
            self.text = []
    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)
    def handle_endtag(self, tag):
        if tag == 'a' and self.href is not None:
            self.links.append((self.href, ''.join(self.text).strip()))
            self.href = None
            self.text = []

def fetch_home():
    req = Request(HOME, headers={'User-Agent': 'ChoujinXUpdatesBot/0.3 (public publisher update checker)'})
    with urlopen(req, timeout=15) as response:
        return response.read(2_000_000).decode('utf-8', 'replace')

def extract_latest(html):
    parser = Links()
    parser.feed(html)
    for href, text in parser.links:
        url = urljoin(HOME, href)
        parsed = urlparse(url)
        if parsed.hostname == 'tonarinoyj.jp' and parsed.path.startswith('/episode/') and '超人X' in text:
            return {'url': url, 'title': 'Choujin X — new chapter on Tonari no Young Jump'}
    raise ValueError('No Choujin X episode link found on publisher homepage; no notification sent')

async def latest_chapter():
    return await asyncio.to_thread(lambda: extract_latest(fetch_home()))
