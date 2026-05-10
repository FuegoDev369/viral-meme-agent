import requests
import os
import logging

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramNotifier:
    def __init__(self, config):
        self.enabled = config['notifier']['telegram']['enabled']
        self.token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
        self.chat_id = os.environ.get('TELEGRAM_CHAT_ID', '')

    def _api(self, method, **kwargs):
        url = TELEGRAM_API.format(token=self.token, method=method)
        try:
            r = requests.post(url, timeout=30, **kwargs)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.error(f"[Telegram] {method} failed: {e}")
            return None

    def send_candidate(self, payload):
        if not self.enabled or not self.token or not self.chat_id:
            return

        tweet = payload.get('tweet', {})
        analysis = payload.get('analysis', {})
        media_path = payload.get('media_path')
        source = payload.get('source', 'unknown')
        region = payload.get('region', 'Global')
        virality = analysis.get('VIRALITY_SCORE', '?')

        # Virality bar
        score_int = virality if isinstance(virality, int) else 0
        bar = '🟩' * score_int + '⬜' * (10 - score_int)

        caption = (
            f"🔥 *VIRAL CANDIDATE* — {region}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📌 Source: `{source}`\n"
            f"⚡ Virality: {bar} {virality}/10\n"
            f"🏷 Category: `{analysis.get('TREND_CATEGORY', '?')}`\n"
            f"🌍 Relevance: {analysis.get('REGION_RELEVANCE', '?')}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"*📝 TWEET DRAFT* ({tweet.get('char_count', '?')} chars)\n"
            f"```\n{tweet.get('full_tweet', 'N/A')}\n```\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💡 _{analysis.get('VIRALITY_REASON', '')}_"
        )

        # Clamp to Telegram caption limit
        if len(caption) > 1024:
            caption = caption[:1020] + '…'

        ext = media_path.split('.')[-1].lower() if media_path else ''

        try:
            if media_path and os.path.exists(media_path):
                with open(media_path, 'rb') as f:
                    common = dict(
                        data={'chat_id': self.chat_id, 'caption': caption, 'parse_mode': 'Markdown'},
                    )
                    if ext in ('jpg', 'jpeg', 'png', 'webp'):
                        self._api('sendPhoto', files={'photo': f}, **common)
                    elif ext == 'gif':
                        self._api('sendAnimation', files={'animation': f}, **common)
                    elif ext == 'mp4':
                        self._api('sendVideo', files={'video': f}, **common)
                    else:
                        self._api('sendMessage',
                                  json={'chat_id': self.chat_id, 'text': caption, 'parse_mode': 'Markdown'})
            else:
                self._api('sendMessage',
                          json={'chat_id': self.chat_id, 'text': caption, 'parse_mode': 'Markdown'})

            logger.info("[Telegram] Candidate sent")

        except Exception as e:
            logger.error(f"[Telegram] send_candidate error: {e}")

    def send_summary(self, total_scraped, total_sent):
        if not self.enabled or not self.token or not self.chat_id:
            return
        msg = (
            f"✅ *viral-meme-agent — Run Complete*\n"
            f"📦 Scraped: {total_scraped} posts\n"
            f"📤 Candidates sent: {total_sent}\n\n"
            f"_Review the candidates above and copy what you like!_"
        )
        self._api('sendMessage',
                  json={'chat_id': self.chat_id, 'text': msg, 'parse_mode': 'Markdown'})
        logger.info("[Telegram] Summary sent")
