"""Conservative VIZ Choujin X chapter listing checker.

VIZ is a confirmed-release source; MANGA Plus is the reader link. We do not
claim that a MANGA Plus countdown means a chapter has already published.
"""
import asyncio
import re
from datetime import datetime, time
from html import unescape
from html.parser import HTMLParser
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

VIZ = 'https://www.viz.com/shonenjump/chapters/choujin-x'
MANGA_PLUS = 'https://mangaplus.shueisha.co.jp/titles/100160'
EASTERN = ZoneInfo('America/New_York')

class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignore = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.ignore += 1
    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.ignore:
            self.ignore -= 1
    def handle_data(self, data):
        if not self.ignore:
            self.parts.append(data)

def parse_viz(html):
    parser = Text()
    parser.feed(html)
    text = re.sub(r'\s+', ' ', unescape(' '.join(parser.parts)))
    # Require a dated, numbered chapter in the official Choujin X listing.
    matches = re.findall(
        r'\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+'
        r'(\d{1,2}),\s*(20\d{2})\s*(?:Ch\.?|Chapter)\s*(\d+(?:\.\d+)?)\b',
        text, re.I)
    if not matches:
        raise ValueError('VIZ chapter listing could not be parsed; no announcement sent')
    entries = []
    for month, day, year, chapter in matches:
        d = datetime.strptime(f'{month} {day} {year}', '%B %d %Y').date()
        entries.append((d, chapter))
    latest_date, chapter = max(entries, key=lambda x: (x[0], tuple(int(p) for p in x[1].split('.'))))
    # VIZ shows the date, but not a reliable release hour. The 10 PM hour is
    # an observed schedule assumption, NOT a timestamp verified by VIZ.
    estimated_clock = datetime.combine(latest_date, time(22), EASTERN)
    return {'chapter': chapter, 'date': latest_date.isoformat(), 'estimated_clock': estimated_clock,
            'url': VIZ, 'reader_url': MANGA_PLUS}

def fetch_viz():
    request = Request(VIZ, headers={'User-Agent': 'Mozilla/5.0 (compatible; ChoujinXReleaseWatcher/1.0)'})
    with urlopen(request, timeout=20) as response:
        return response.read(3_000_000).decode('utf-8', 'replace')

async def latest_english():
    return await asyncio.to_thread(lambda: parse_viz(fetch_viz()))
