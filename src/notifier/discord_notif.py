import requests
import os
import json
import logging

logger = logging.getLogger(__name__)


def _virality_color(score):
    if score >= 8:
        return 0xFF4500   # Red-orange — ultra viral
    if score >= 6:
        return 0xF4A62A   # Orange — high viral
    if score >= 4:
        return 0x5865F2   # Discord blurple — medium
    return 0x747F8D       # Grey — low


class DiscordNotifier:
    def __init__(self, config):
        self.enabled = config['notifier']['discord']['enabled']
        self.webhook_url = os.environ.get('DISCORD_WEBHOOK_URL', '')

    def _post(self, **kwargs):
        try:
            r = requests.post(self.webhook_url, timeout=30, **kwargs)
            r.raise_for_status()
        except Exception as e:
            logger.error(f"[Discord] Post failed: {e}")

    def send_candidate(self, payload):
        if not self.enabled or not self.webhook_url:
            return

        tweet = payload.get('tweet', {})
        analysis = payload.get('analysis', {})
        media_path = payload.get('media_path')
        source = payload.get('source', 'unknown')
        region = payload.get('region', 'Global')
        virality = analysis.get('VIRALITY_SCORE', 0)
        score_int = virality if isinstance(virality, int) else 0

        # Virality bar emoji
        bar = '🟩' * score_int + '⬜' * (10 - score_int)

        full_tweet = tweet.get('full_tweet', 'N/A')
        char_count = tweet.get('char_count', len(full_tweet))

        embed = {
            "title": f"🔥  Viral Candidate — {region}",
            "color": _virality_color(score_int),
            "fields": [
                {
                    "name": "📌 Source",
                    "value": f"`{source}`",
                    "inline": True
                },
                {
                    "name": "⚡ Virality Score",
                    "value": f"{bar}  **{virality}/10**",
                    "inline": False
                },
                {
                    "name": "🏷 Category",
                    "value": analysis.get('TREND_CATEGORY', '?'),
                    "inline": True
                },
                {
                    "name": "🌍 Region Relevance",
                    "value": analysis.get('REGION_RELEVANCE', '?'),
                    "inline": True
                },
                {
                    "name": f"📝 Tweet Draft ({char_count}/280 chars)",
                    "value": f"```\n{full_tweet[:1000]}\n```",
                    "inline": False
                },
                {
                    "name": "💡 Why it works",
                    "value": analysis.get('VIRALITY_REASON', '?')[:300],
                    "inline": False
                },
            ],
            "footer": {
                "text": "viral-meme-agent  •  Copy the tweet draft above, download the media, and post on Twitter/X"
            }
        }

        ext = media_path.split('.')[-1].lower() if media_path else ''

        try:
            if media_path and os.path.exists(media_path) and ext in ('jpg', 'jpeg', 'png', 'gif'):
                with open(media_path, 'rb') as f:
                    self._post(
                        data={"payload_json": json.dumps({"embeds": [embed]})},
                        files={"file": (f"viral.{ext}", f, f"image/{ext}")}
                    )
            else:
                self._post(json={"embeds": [embed]})

            logger.info("[Discord] Candidate sent")

        except Exception as e:
            logger.error(f"[Discord] send_candidate error: {e}")

    def send_summary(self, total_scraped, total_sent):
        if not self.enabled or not self.webhook_url:
            return

        embed = {
            "title": "✅  viral-meme-agent — Run Complete",
            "color": 0x57F287,  # Discord green
            "fields": [
                {"name": "📦 Posts Scraped", "value": str(total_scraped), "inline": True},
                {"name": "📤 Candidates Sent", "value": str(total_sent), "inline": True},
            ],
            "footer": {"text": "Review the candidates above and copy what resonates!"}
        }
        self._post(json={"embeds": [embed]})
        logger.info("[Discord] Summary sent")
