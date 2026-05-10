"""
9gag scraper — utilise le RSS public, zéro auth requise.
Récupère les posts hot/viral avec images.
"""
import requests
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

NAMESPACES = {
    'media': 'http://search.yahoo.com/mrss/',
    'dc': 'http://purl.org/dc/elements/1.1/',
}

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/rss+xml, application/xml, text/xml, */*',
    'Accept-Language': 'en-US,en;q=0.9',
}


class NineGagScraper:
    def __init__(self, config):
        self.cfg = config['scrapers']['ninegag']
        self.max_posts = self.cfg.get('max_posts', 20)

    def _fetch(self, url):
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.error(f"[9gag] Fetch failed ({url}): {e}")
            return None

    def _extract_images(self, description_html):
        """Extract image URLs from the HTML description block in RSS items."""
        urls = []
        if not description_html:
            return urls
        soup = BeautifulSoup(description_html, 'html.parser')
        for img in soup.find_all('img'):
            src = img.get('src', '').strip()
            # Skip tiny icons / avatars
            if src and ('images-cdn.9gag.com' in src or '9gag.com' in src):
                # Prefer the largest variant
                src = src.replace('_220x220', '_460c').replace('_460s', '_460c')
                urls.append(src)
            elif src and src.startswith('http'):
                urls.append(src)
        return urls

    def _parse_rss(self, xml_text):
        posts = []
        try:
            root = ET.fromstring(xml_text)
            channel = root.find('channel')
            if channel is None:
                logger.error("[9gag] No <channel> element found in RSS")
                return posts

            for item in channel.findall('item'):
                title = item.findtext('title', '').strip()
                description = item.findtext('description', '')
                link = item.findtext('link', '')

                media_urls = []

                # 1 — media:content (preferred — full image)
                for mc in item.findall('media:content', NAMESPACES):
                    url = mc.get('url', '')
                    if url:
                        media_urls.append(url)

                # 2 — media:thumbnail
                for mt in item.findall('media:thumbnail', NAMESPACES):
                    url = mt.get('url', '')
                    if url and url not in media_urls:
                        media_urls.append(url)

                # 3 — parse HTML description
                img_urls = self._extract_images(description)
                for u in img_urls:
                    if u not in media_urls:
                        media_urls.append(u)

                if not media_urls:
                    continue

                posts.append({
                    'source': '9gag',
                    'region': 'Global',
                    'title': title,
                    'text': '',
                    'score': 5000,  # No score in RSS — default high so it passes filter
                    'media_urls': media_urls,
                    'link': link,
                    'scraped_at': datetime.utcnow().isoformat(),
                })

        except ET.ParseError as e:
            logger.error(f"[9gag] XML parse error: {e}")

        logger.info(f"[9gag] Parsed {len(posts)} posts with media")
        return posts[:self.max_posts]

    def scrape(self):
        logger.info("[9gag] Fetching RSS...")
        xml = self._fetch('https://9gag.com/rss.xml')
        if not xml:
            return []
        return self._parse_rss(xml)
