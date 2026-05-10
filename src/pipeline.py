#!/usr/bin/env python3
"""
viral-meme-agent — Main Pipeline
Scrapes viral content → analyzes with Gemini Vision → generates tweets → notifies via Telegram/Discord
"""

import sys
import os
import yaml
import json
import logging
from pathlib import Path
from datetime import datetime

# Allow imports from src/
sys.path.insert(0, os.path.dirname(__file__))

from scrapers.nitter import NitterScraper
from scrapers.reddit import RedditScraper
from media.downloader import MediaDownloader
from analyzer.vision import VisionAnalyzer
from generator.tweet_gen import TweetGenerator
from notifier.telegram_bot import TelegramNotifier
from notifier.discord_notif import DiscordNotifier

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  [%(levelname)s]  %(name)s — %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('pipeline')

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent.parent  # project root
CONFIG_PATH = BASE_DIR / 'config' / 'config.yaml'
STATE_PATH = BASE_DIR / 'state' / 'seen.json'
STATE_MAX = 1000  # Max IDs to remember (rolling window)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def load_seen():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return set(json.load(f))
    return set()


def save_seen(seen: set):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Keep only the last STATE_MAX entries to avoid bloat
    trimmed = list(seen)[-STATE_MAX:]
    with open(STATE_PATH, 'w') as f:
        json.dump(trimmed, f, indent=2)


def post_id(post: dict) -> str:
    """Stable unique ID for a post based on its media URLs."""
    key = '|'.join(post.get('media_urls', [])) + post.get('text', '')[:80]
    import hashlib
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    logger.info("=" * 60)
    logger.info("  🚀  viral-meme-agent starting")
    logger.info(f"  ⏰  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 60)

    config = load_config()
    seen = load_seen()

    min_score = config['agent']['min_virality_score']
    max_candidates = config['agent']['max_candidates_per_run']

    # ── Init modules ──────────────────────────────────────────────────────────
    downloader = MediaDownloader(config)
    vision = VisionAnalyzer(config)
    generator = TweetGenerator(config)
    telegram = TelegramNotifier(config)
    discord = DiscordNotifier(config)

    # ── Scraping ──────────────────────────────────────────────────────────────
    all_posts = []

    if config['scrapers']['nitter']['enabled']:
        nitter = NitterScraper(config)
        posts = nitter.scrape()
        all_posts.extend(posts)

    if config['scrapers']['reddit']['enabled']:
        reddit = RedditScraper(config)
        posts = reddit.scrape()
        all_posts.extend(posts)

    # Sort all by score descending
    all_posts.sort(key=lambda x: x.get('score', 0), reverse=True)
    logger.info(f"📦  Total posts scraped: {len(all_posts)}")

    # ── Processing ────────────────────────────────────────────────────────────
    sent = 0
    skipped_seen = 0
    skipped_media = 0
    skipped_score = 0

    for post in all_posts:
        if sent >= max_candidates:
            logger.info(f"Reached max candidates ({max_candidates}), stopping")
            break

        pid = post_id(post)

        # Dedup check
        if pid in seen:
            skipped_seen += 1
            continue

        # Download media
        media_path = downloader.download_best(post.get('media_urls', []))
        if not media_path:
            skipped_media += 1
            seen.add(pid)  # Mark so we don't retry a broken post
            continue

        # Vision analysis
        context = post.get('title', '') or post.get('text', '')
        analysis = vision.analyze(media_path, context)
        if not analysis:
            logger.warning("Vision analysis returned None, skipping")
            continue

        virality = analysis.get('VIRALITY_SCORE', 0)
        logger.info(
            f"Score {virality}/10  [{post.get('region', '?')}]  "
            f"source={post.get('source')}  cat={analysis.get('TREND_CATEGORY', '?')}"
        )

        if virality < min_score:
            skipped_score += 1
            seen.add(pid)
            continue

        # Tweet generation
        tweet = generator.generate(analysis, context, post.get('region', 'Global'))
        if not tweet or not tweet.get('full_tweet'):
            logger.warning("Tweet generation failed, skipping")
            continue

        # Build payload
        source_label = post.get('source', '?')
        if post.get('subreddit'):
            source_label += f" / {post['subreddit']}"
        elif post.get('region'):
            source_label += f" / {post['region']}"

        payload = {
            'source': source_label,
            'region': post.get('region', 'Global'),
            'analysis': analysis,
            'tweet': tweet,
            'media_path': media_path,
            'scraped_at': post.get('scraped_at'),
        }

        # ── Notify ────────────────────────────────────────────────────────────
        telegram.send_candidate(payload)
        discord.send_candidate(payload)

        seen.add(pid)
        sent += 1

    # ── Summary ───────────────────────────────────────────────────────────────
    save_seen(seen)

    logger.info("=" * 60)
    logger.info(f"  ✅  Run complete")
    logger.info(f"  📤  Candidates sent : {sent}")
    logger.info(f"  🔁  Skipped (seen)  : {skipped_seen}")
    logger.info(f"  📵  Skipped (media) : {skipped_media}")
    logger.info(f"  📉  Skipped (score) : {skipped_score}")
    logger.info("=" * 60)

    telegram.send_summary(len(all_posts), sent)
    discord.send_summary(len(all_posts), sent)


if __name__ == '__main__':
    run()
