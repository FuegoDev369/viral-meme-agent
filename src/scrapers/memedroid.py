"""
Memedroid scraper — API publique, zéro auth requise.
Récupère les mèmes trending avec score et images.
"""
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 12; Pixel 6) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Mobile Safari/537.36'
    ),
    'Accept': 'application/json',
    'Referer': 'https://memedroid.com/',
}

# Endpoints publics Memedroid
ENDPOINTS = [
    {
        'url': 'https://api.memedroid.com/api/get_memes_trending',
        'label': 'Global Trending',
        'region': 'Global',
    },
    {
        'url': 'https://api.memedroid.com/api/get_memes_best?interval=week',
        'label': 'Best of Week',
        'region': 'Global',
    },
]


class MemedroidScraper:
    def __init__(self, config):
        self.cfg = config['scrapers']['memedroid']
        self.max_posts = self.cfg.get('max_posts', 15)

    def _fetch(self, url):
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            r.raise_for_status()
            return r.json()
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[Memedroid] HTTP error {e} for {url}")
            return None
        except Exception as e:
            logger.error(f"[Memedroid] Fetch failed ({url}): {e}")
            return None

    def _parse(self, data, region):
        posts = []
        if not data:
            return posts

        # Memedroid wraps results in different keys depending on endpoint
        items = (
            data.get('items')
            or data.get('memes')
            or data.get('data', {}).get('items')
            or []
        )

        for item in items:
            try:
                # Image URL
                media_url = (
                    item.get('image', {}).get('url')
                    or item.get('imageUrl')
                    or item.get('url')
                    or ''
                )
                if not media_url:
                    continue

                title = item.get('title', '') or item.get('name', '')
                score = item.get('score', 0) or item.get('rating', 0) or 1000

                posts.append({
                    'source': 'memedroid',
                    'region': region,
                    'title': title,
                    'text': '',
                    'score': int(score),
                    'media_urls': [media_url],
                    'scraped_at': datetime.utcnow().isoformat(),
                })
            except Exception as e:
                logger.debug(f"[Memedroid] Error parsing item: {e}")
                continue

        return posts

    def scrape(self):
        all_posts = []
        for ep in ENDPOINTS:
            logger.info(f"[Memedroid] Fetching: {ep['label']}")
            data = self._fetch(ep['url'])
            if data:
                posts = self._parse(data, ep['region'])
                logger.info(f"[Memedroid] {ep['label']}: {len(posts)} posts")
                all_posts.extend(posts)
            else:
                logger.warning(f"[Memedroid] No data for {ep['label']}")

        all_posts.sort(key=lambda x: x['score'], reverse=True)
        return all_posts[:self.max_posts]
