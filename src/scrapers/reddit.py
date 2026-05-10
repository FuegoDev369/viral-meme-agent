import praw
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


class RedditScraper:
    def __init__(self, config):
        self.cfg = config['scrapers']['reddit']
        self.min_score = self.cfg['min_score']
        self.max_posts = self.cfg.get('max_posts_per_region', 5)

        self.reddit = praw.Reddit(
            client_id=os.environ['REDDIT_CLIENT_ID'],
            client_secret=os.environ['REDDIT_CLIENT_SECRET'],
            user_agent='viral-meme-agent/2.0 (read-only bot)',
            read_only=True,
        )

    def _extract_media(self, sub):
        urls = []
        url = sub.url or ''

        if any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
            urls.append(url)

        if getattr(sub, 'is_gallery', False):
            try:
                for item in sub.gallery_data['items'][:3]:
                    mid = item['media_id']
                    meta = sub.media_metadata.get(mid, {})
                    if meta.get('status') == 'valid':
                        img = meta['s']['u'].replace('&amp;', '&')
                        urls.append(img)
            except Exception:
                pass

        if hasattr(sub, 'preview') and sub.preview:
            try:
                img = sub.preview['images'][0]['source']['url'].replace('&amp;', '&')
                if img not in urls:
                    urls.append(img)
            except Exception:
                pass

        if sub.is_video and sub.media:
            try:
                urls.append(sub.media['reddit_video']['fallback_url'])
            except Exception:
                pass

        return urls

    def _scrape_subreddit(self, subreddit_name, region):
        sub_id = subreddit_name.replace('r/', '')
        posts = []
        try:
            subreddit = self.reddit.subreddit(sub_id)
            for submission in subreddit.hot(limit=30):
                if submission.is_self:
                    continue
                if submission.score < self.min_score:
                    continue
                media_urls = self._extract_media(submission)
                if not media_urls:
                    continue
                posts.append({
                    'source': 'reddit',
                    'subreddit': subreddit_name,
                    'region': region,
                    'title': submission.title,
                    'text': (submission.selftext or '')[:200],
                    'score': submission.score,
                    'upvote_ratio': submission.upvote_ratio,
                    'num_comments': submission.num_comments,
                    'media_urls': media_urls,
                    'scraped_at': datetime.utcnow().isoformat(),
                })
                if len(posts) >= self.max_posts:
                    break
        except Exception as e:
            logger.error(f"[Reddit] Failed on {subreddit_name}: {e}")
        return posts

    def scrape(self):
        all_posts = []
        regions = self.cfg.get('subreddits_by_region', {})
        for region, subreddits in regions.items():
            logger.info(f"[Reddit] Region={region} — {len(subreddits)} subreddits")
            for sr in subreddits:
                posts = self._scrape_subreddit(sr, region)
                logger.info(f"[Reddit] {sr}: {len(posts)} posts with media")
                all_posts.extend(posts)
        all_posts.sort(key=lambda x: x['score'], reverse=True)
        logger.info(f"[Reddit] Total collected: {len(all_posts)}")
        return all_posts
