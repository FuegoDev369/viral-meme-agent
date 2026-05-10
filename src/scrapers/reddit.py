import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class RedditScraper:
    def __init__(self, config):
        self.subreddits = config['scrapers']['reddit']['subreddits']
        self.max_posts = config['scrapers']['reddit']['max_posts']
        self.min_score = config['scrapers']['reddit']['min_score']
        self.headers = {'User-Agent': 'viral-meme-agent/1.0 (by u/anonymous)'}

    def _fetch_subreddit(self, subreddit):
        sub = subreddit.replace('r/', '')
        url = f"https://www.reddit.com/r/{sub}/hot.json?limit=30"
        try:
            r = requests.get(url, headers=self.headers, timeout=12)
            r.raise_for_status()
            return r.json()['data']['children']
        except Exception as e:
            logger.error(f"[Reddit] Fetch failed for {subreddit}: {e}")
            return []

    def _extract_media(self, post_data):
        media_urls = []

        url = post_data.get('url', '')

        # Direct image link
        if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            media_urls.append(url)

        # Reddit gallery
        if post_data.get('is_gallery'):
            gallery = post_data.get('gallery_data', {}).get('items', [])
            media_meta = post_data.get('media_metadata', {})
            for item in gallery[:3]:
                media_id = item.get('media_id', '')
                meta = media_meta.get(media_id, {})
                if meta.get('status') == 'valid':
                    s = meta.get('s', {})
                    img_url = s.get('u', '').replace('&amp;', '&')
                    if img_url:
                        media_urls.append(img_url)

        # Reddit preview image (fallback)
        preview = post_data.get('preview', {})
        if preview.get('images'):
            img_url = preview['images'][0]['source']['url'].replace('&amp;', '&')
            if img_url and img_url not in media_urls:
                media_urls.append(img_url)

        # Reddit hosted video
        media = post_data.get('media') or {}
        reddit_video = media.get('reddit_video', {})
        if reddit_video:
            video_url = reddit_video.get('fallback_url', '')
            if video_url:
                media_urls.append(video_url)

        return media_urls

    def scrape(self):
        all_posts = []

        for subreddit in self.subreddits:
            logger.info(f"[Reddit] Scraping {subreddit}")
            children = self._fetch_subreddit(subreddit)

            for child in children:
                post = child['data']

                # Skip text-only posts
                if post.get('is_self'):
                    continue

                score = post.get('score', 0)
                if score < self.min_score:
                    continue

                media_urls = self._extract_media(post)
                if not media_urls:
                    continue

                all_posts.append({
                    'source': 'reddit',
                    'subreddit': subreddit,
                    'region': 'Global',
                    'title': post.get('title', ''),
                    'text': post.get('selftext', ''),
                    'score': score,
                    'upvote_ratio': post.get('upvote_ratio', 0),
                    'num_comments': post.get('num_comments', 0),
                    'media_urls': media_urls,
                    'permalink': f"https://reddit.com{post.get('permalink', '')}",
                    'scraped_at': datetime.utcnow().isoformat(),
                })

        # Sort by score descending
        all_posts.sort(key=lambda x: x['score'], reverse=True)
        top = all_posts[:self.max_posts]
        logger.info(f"[Reddit] Total with media: {len(all_posts)} → keeping top {len(top)}")
        return top
