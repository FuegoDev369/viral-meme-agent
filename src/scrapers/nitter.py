import requests
from bs4 import BeautifulSoup
import random
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class NitterScraper:
    def __init__(self, config):
        self.instances = config['scrapers']['nitter']['instances']
        self.regions = config['scrapers']['nitter']['regions']
        self.max_posts = config['scrapers']['nitter']['max_posts']
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }

    def _get_instance(self):
        return random.choice(self.instances)

    def _search(self, query, instance):
        url = f"{instance}/search?q={requests.utils.quote(query)}&f=tweets"
        try:
            r = requests.get(url, headers=self.headers, timeout=12)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.warning(f"Nitter instance {instance} failed: {e}")
            return None

    def _parse_tweets(self, html, instance):
        soup = BeautifulSoup(html, 'html.parser')
        posts = []

        for tweet in soup.select('.timeline-item'):
            try:
                # Skip retweets
                if tweet.select_one('.retweet-header'):
                    continue

                content_el = tweet.select_one('.tweet-content')
                text = content_el.get_text(strip=True) if content_el else ''

                # Stats
                likes, retweets = 0, 0
                for stat in tweet.select('.tweet-stat'):
                    val_text = stat.get_text(strip=True).replace(',', '').replace(' ', '')
                    try:
                        val = int(''.join(filter(str.isdigit, val_text)) or '0')
                    except Exception:
                        val = 0
                    if stat.select_one('.icon-heart'):
                        likes = val
                    elif stat.select_one('.icon-retweet'):
                        retweets = val

                # Media — images
                media_urls = []
                for img in tweet.select('.still-image'):
                    src = img.get('src', '')
                    if src:
                        if src.startswith('/'):
                            src = f"{instance}{src}"
                        media_urls.append(src)

                # Media — videos
                for video in tweet.select('video source'):
                    src = video.get('src', '')
                    if src:
                        if src.startswith('/'):
                            src = f"{instance}{src}"
                        media_urls.append(src)

                if not media_urls:
                    continue

                posts.append({
                    'source': 'nitter',
                    'text': text,
                    'likes': likes,
                    'retweets': retweets,
                    'media_urls': media_urls,
                    'score': likes + (retweets * 2),
                    'scraped_at': datetime.utcnow().isoformat(),
                })

            except Exception as e:
                logger.debug(f"Error parsing tweet element: {e}")
                continue

        posts.sort(key=lambda x: x['score'], reverse=True)
        return posts[:self.max_posts]

    def scrape(self):
        all_posts = []
        for region in self.regions:
            label = region['label']
            query = region['query']
            instance = self._get_instance()
            logger.info(f"[Nitter] Scraping region={label} via {instance}")
            html = self._search(query, instance)
            if not html:
                # Try another instance
                for _ in range(2):
                    instance = self._get_instance()
                    html = self._search(query, instance)
                    if html:
                        break
            if html:
                posts = self._parse_tweets(html, instance)
                for p in posts:
                    p['region'] = label
                logger.info(f"[Nitter] {label}: {len(posts)} posts with media")
                all_posts.extend(posts)
            else:
                logger.error(f"[Nitter] All instances failed for region={label}")

        return all_posts
