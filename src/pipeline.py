#!/usr/bin/env python3
"""
viral-meme-agent v3 — Main Pipeline
Sources: 9gag RSS + Memedroid (zéro auth)
→ Gemini Vision → Tweet Generator → Telegram/Discord
"""

import sys
import os
import yaml
import json
import logging
import hashlib
from pathlib import Path
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

from media.downloader import MediaDownloader
from analyzer.vision import VisionAnalyzer
from generator.tweet_gen import TweetGenerator
from notifier.telegram_bot import TelegramNotifier
from notifier.discord_notif import DiscordNotifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s  [%(levelname)s]  %(name)s — %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('pipeline')

BASE_DIR   = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'config.yaml'
STATE_PATH  = BASE_DIR / 'state' / 'seen.json'
STATE_MAX   = 1000


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
    with open(STATE_PATH, 'w') as f:
        json.dump(list(seen)[-STATE_MAX:], f, indent=2)


def post_id(post: dict) -> str:
    key = '|'.join(post.get('media_urls', [])) + post.get('title', '')[:80]
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def run():
    logger.info("=" * 60)
    logger.info("  🚀  viral-meme-agent v3 starting")
    logger.info(f"  ⏰  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 60)

    config   = load_config()
    seen     = load_seen()
    scrapers_cfg = config['scrapers']

    min_score     = config['agent']['min_virality_score']
    max_candidates = config['agent']['max_candidates_per_run']

    downloader = MediaDownloader(config)
    vision     = VisionAnalyzer(config)
    generator  = TweetGenerator(config)
    telegram   = TelegramNotifier(config)
    discord    = DiscordNotifier(config)

    # ── Scraping ──────────────────────────────────────────────────────────────
    all_posts = []

    if scrapers_cfg.get('ninegag', {}).get('enabled', False):
        from scrapers.ninegag import NineGagScraper
        posts = NineGagScraper(config).scrape()
        all_posts.extend(posts)

    if scrapers_cfg.get('memedroid', {}).get('enabled', False):
        from scrapers.memedroid import MemedroidScraper
        posts = MemedroidScraper(config).scrape()
        all_posts.extend(posts)

    if scrapers_cfg.get('reddit', {}).get('enabled', False):
        from scrapers.reddit import RedditScraper
        posts = RedditScraper(config).scrape()
        all_posts.extend(posts)

    if scrapers_cfg.get('nitter', {}).get('enabled', False):
        from scrapers.nitter import NitterScraper
        posts = NitterScraper(config).scrape()
        all_posts.extend(posts)

    all_posts.sort(key=lambda x: x.get('score', 0), reverse=True)
    logger.info(f"📦  Total posts scraped: {len(all_posts)}")

    if not all_posts:
        logger.warning("No posts collected — all scrapers returned empty. Check network or source availability.")
        telegram.send_summary(0, 0)
        discord.send_summary(0, 0)
        return

    # ── Processing ────────────────────────────────────────────────────────────
    sent           = 0
    skipped_seen   = 0
    skipped_media  = 0
    skipped_score  = 0

    for post in all_posts:
        if sent >= max_candidates:
            logger.info(f"Reached max candidates ({max_candidates}), stopping")
            break

        pid = post_id(post)
        if pid in seen:
            skipped_seen += 1
            continue

        media_path = downloader.download_best(post.get('media_urls', []))
        if not media_path:
            skipped_media += 1
            seen.add(pid)
            continue

        context  = post.get('title', '') or post.get('text', '')
        analysis = vision.analyze(media_path, context)
        if not analysis:
            logger.warning("Vision analysis returned None, skipping")
            continue

        virality = analysis.get('VIRALITY_SCORE', 0)
        logger.info(
            f"Score {virality}/10  [{post.get('region', '?')}]  "
            f"src={post.get('source')}  cat={analysis.get('TREND_CATEGORY', '?')}"
        )

        if virality < min_score:
            skipped_score += 1
            seen.add(pid)
            continue

        tweet = generator.generate(analysis, context, post.get('region', 'Global'))
        if not tweet or not tweet.get('full_tweet'):
            logger.warning("Tweet generation failed, skipping")
            continue

        payload = {
            'source': post.get('source', '?'),
            'region': post.get('region', 'Global'),
            'analysis': analysis,
            'tweet': tweet,
            'media_path': media_path,
            'scraped_at': post.get('scraped_at'),
        }

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
