#!/usr/bin/env python3
"""
viral-meme-agent v4.1 — Main Pipeline
Source : meme-api.com (public, zéro auth)
→ Gemini 1.5 Flash (avec rate limiting) → Tweet Generator → Telegram/Discord
"""

import sys, os, yaml, json, logging, hashlib, time
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

BASE_DIR    = Path(__file__).parent.parent
CONFIG_PATH = BASE_DIR / 'config' / 'config.yaml'
STATE_PATH  = BASE_DIR / 'state' / 'seen.json'
STATE_MAX   = 1000

# Délai entre chaque post traité (vision + tweet_gen = 2 appels Gemini)
# Free tier: 15 req/min → 1 req toutes les 4s minimum
# On prend 8s de marge pour être safe avec 2 appels par post
GEMINI_INTER_POST_DELAY = 8  # secondes


def load_config():
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)

def load_seen():
    if STATE_PATH.exists():
        with open(STATE_PATH) as f:
            return set(json.load(f))
    return set()

def save_seen(seen):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, 'w') as f:
        json.dump(list(seen)[-STATE_MAX:], f, indent=2)

def post_id(post):
    key = '|'.join(post.get('media_urls', [])) + post.get('title', '')[:80]
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def run():
    logger.info("=" * 60)
    logger.info("  🚀  viral-meme-agent v4.1 starting")
    logger.info(f"  ⏰  {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    logger.info("=" * 60)

    config = load_config()
    seen   = load_seen()
    scfg   = config['scrapers']

    min_score      = config['agent']['min_virality_score']
    max_candidates = config['agent']['max_candidates_per_run']

    downloader = MediaDownloader(config)
    vision     = VisionAnalyzer(config)
    generator  = TweetGenerator(config)
    telegram   = TelegramNotifier(config)
    discord    = DiscordNotifier(config)

    # ── Scraping ──────────────────────────────────────────────────────────────
    all_posts = []

    if scfg.get('memeapi', {}).get('enabled'):
        from scrapers.memeapi import MemeAPIScraper
        all_posts.extend(MemeAPIScraper(config).scrape())

    if scfg.get('ninegag', {}).get('enabled'):
        from scrapers.ninegag import NineGagScraper
        all_posts.extend(NineGagScraper(config).scrape())

    if scfg.get('memedroid', {}).get('enabled'):
        from scrapers.memedroid import MemedroidScraper
        all_posts.extend(MemedroidScraper(config).scrape())

    if scfg.get('reddit', {}).get('enabled'):
        from scrapers.reddit import RedditScraper
        all_posts.extend(RedditScraper(config).scrape())

    if scfg.get('nitter', {}).get('enabled'):
        from scrapers.nitter import NitterScraper
        all_posts.extend(NitterScraper(config).scrape())

    all_posts.sort(key=lambda x: x.get('score', 0), reverse=True)
    logger.info(f"📦  Total posts scraped: {len(all_posts)}")

    if not all_posts:
        logger.warning("⚠️  Aucun post collecté.")
        telegram.send_summary(0, 0)
        discord.send_summary(0, 0)
        return

    # ── Processing ────────────────────────────────────────────────────────────
    sent, skipped_seen, skipped_media, skipped_score = 0, 0, 0, 0

    for i, post in enumerate(all_posts):
        if sent >= max_candidates:
            logger.info(f"Max candidats atteint ({max_candidates}), arrêt.")
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

        # Délai entre posts pour respecter le rate limit Gemini (free tier: 15 RPM)
        if i > 0:
            logger.info(f"⏳  Attente {GEMINI_INTER_POST_DELAY}s (rate limit Gemini)...")
            time.sleep(GEMINI_INTER_POST_DELAY)

        context  = post.get('title', '') or post.get('text', '')
        analysis = vision.analyze(media_path, context)
        if not analysis:
            logger.warning("Vision analysis None, skip")
            continue

        virality = analysis.get('VIRALITY_SCORE', 0)
        logger.info(
            f"Score {virality}/10  [{post.get('region','?')}]  "
            f"src={post.get('source','?')}  cat={analysis.get('TREND_CATEGORY','?')}"
        )

        if virality < min_score:
            skipped_score += 1
            seen.add(pid)
            continue

        tweet = generator.generate(analysis, context, post.get('region', 'Global'))
        if not tweet or not tweet.get('full_tweet'):
            logger.warning("Tweet generation failed, skip")
            continue

        payload = {
            'source':     post.get('source', '?'),
            'region':     post.get('region', 'Global'),
            'analysis':   analysis,
            'tweet':      tweet,
            'media_path': media_path,
            'scraped_at': post.get('scraped_at'),
        }

        telegram.send_candidate(payload)
        discord.send_candidate(payload)
        seen.add(pid)
        sent += 1

    # ── Résumé ────────────────────────────────────────────────────────────────
    save_seen(seen)
    logger.info("=" * 60)
    logger.info(f"  ✅  Run complet")
    logger.info(f"  📤  Envoyés      : {sent}")
    logger.info(f"  🔁  Déjà vus     : {skipped_seen}")
    logger.info(f"  📵  Pas de media : {skipped_media}")
    logger.info(f"  📉  Score < {min_score}    : {skipped_score}")
    logger.info("=" * 60)

    telegram.send_summary(len(all_posts), sent)
    discord.send_summary(len(all_posts), sent)


if __name__ == '__main__':
    run()
