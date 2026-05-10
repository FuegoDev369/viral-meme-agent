"""
Scraper — meme-api.com
API publique, zéro auth, zéro compte.
Récupère les mèmes viraux par région via des subreddits ciblés.
Doc : https://github.com/D3vd/Meme_Api
"""
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

BASE_URL = "https://meme-api.com/gimme/{subreddit}/{count}"

HEADERS = {'User-Agent': 'viral-meme-agent/4.0'}

# Subreddits par région — couvre USA, Afrique, Asie, Global
REGIONS = {
    'Global':  ['memes', 'dankmemes', 'funny', 'interestingasfuck'],
    'USA':     ['BlackPeopleTwitter', 'AdviceAnimals', 'me_irl'],
    'Africa':  ['AfricanMemes', 'Nigeria', 'africa'],
    'Asia':    ['AsianPeopleTwitter', 'korea', 'japan'],
}

IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')


class MemeAPIScraper:
    def __init__(self, config):
        cfg = config['scrapers']['memeapi']
        self.count_per_sub = cfg.get('count_per_subreddit', 5)
        self.min_upvotes   = cfg.get('min_upvotes', 500)

    def _fetch(self, subreddit):
        url = BASE_URL.format(subreddit=subreddit, count=self.count_per_sub)
        try:
            r = requests.get(url, headers=HEADERS, timeout=12)
            r.raise_for_status()
            return r.json().get('memes', [])
        except requests.exceptions.HTTPError as e:
            logger.warning(f"[MemeAPI] HTTP {e.response.status_code} for r/{subreddit}")
        except Exception as e:
            logger.error(f"[MemeAPI] Failed for r/{subreddit}: {e}")
        return []

    def scrape(self):
        all_posts = []

        for region, subreddits in REGIONS.items():
            logger.info(f"[MemeAPI] Region={region} → {subreddits}")
            for sub in subreddits:
                memes = self._fetch(sub)
                accepted = 0
                for m in memes:
                    # Filtres de base
                    if m.get('nsfw') or m.get('spoiler'):
                        continue
                    ups = m.get('ups', 0)
                    if ups < self.min_upvotes:
                        continue

                    # Construire la liste des URLs médias
                    media_urls = []
                    img_url = m.get('url', '')
                    if img_url and img_url.lower().endswith(IMAGE_EXTS):
                        media_urls.append(img_url)

                    # Les previews sont triés du + petit au + grand
                    for prev in reversed(m.get('preview', [])):
                        if prev not in media_urls:
                            media_urls.append(prev)

                    if not media_urls:
                        continue

                    all_posts.append({
                        'source':     f"meme-api / r/{sub}",
                        'region':     region,
                        'title':      m.get('title', ''),
                        'text':       '',
                        'score':      ups,
                        'media_urls': media_urls,
                        'scraped_at': datetime.utcnow().isoformat(),
                    })
                    accepted += 1

                logger.info(f"[MemeAPI] r/{sub}: {accepted}/{len(memes)} memes accepted")

        all_posts.sort(key=lambda x: x['score'], reverse=True)
        logger.info(f"[MemeAPI] Total collecté: {len(all_posts)} posts")
        return all_posts
