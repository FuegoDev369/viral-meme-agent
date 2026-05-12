"""
Tweet Generator — Double provider avec fallback automatique
Primary  : Google Gemini 2.0 Flash Lite
Fallback : Mistral Small (appel HTTP direct, pas de SDK)
"""
from google import genai
from google.genai import types
import requests
import logging
import os
import time

from analyzer.vision import QuotaExhaustedError

logger = logging.getLogger(__name__)

MAX_RETRIES  = 3
RETRY_DELAY  = 25

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"


class TweetGenerator:
    def __init__(self, config):
        # ── Gemini (primary) ──────────────────────────────────────────────────
        self.gemini      = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        cfg              = config['gemini']
        self.g_model     = cfg['model']
        self.temperature = cfg['temperature']

        # ── Mistral (fallback) — appel HTTP direct ────────────────────────────
        self.mistral_key = os.environ.get('MISTRAL_API_KEY', '')
        self.m_model     = config.get('mistral', {}).get('text_model', 'mistral-small-latest')

        if self.mistral_key:
            logger.info("[TweetGen] Mistral fallback activé ✅")
        else:
            logger.warning("[TweetGen] MISTRAL_API_KEY absent — fallback désactivé")

        tw = config['tweet_generator']
        self.max_length     = tw['max_length']
        self.hashtags_count = tw['hashtags_count']
        self.style          = tw['style']

    def _build_prompt(self, analysis, original_text, region):
        return f"""You are a viral Twitter/X growth expert. Craft a tweet that maximizes impressions and engagement.

CONTENT ANALYSIS:
- Description: {analysis.get('DESCRIPTION', '')}
- Humor type: {analysis.get('HUMOR_TYPE', '')}
- Why it would go viral: {analysis.get('VIRALITY_REASON', '')}
- Region relevance: {analysis.get('REGION_RELEVANCE', region)}
- Category: {analysis.get('TREND_CATEGORY', '')}
- Original context: {original_text[:250] if original_text else 'N/A'}

RULES:
- Language: English ONLY
- Max length: {self.max_length} characters (tweet + hashtags combined)
- Style: {self.style}
- Exactly {self.hashtags_count} hashtags at the end
- Start with a strong hook (question, bold claim, or relatable opener)
- Max 2 emojis — feel human, not AI
- Do NOT reference Reddit or any scraping source

Respond with ONLY these two lines:

TWEET: [tweet text without hashtags]
HASHTAGS: [#tag1 #tag2 #tag3]
"""

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _gemini_call(self, prompt):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self.gemini.models.generate_content(
                    model=self.g_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=self.temperature),
                )
                return r.text
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                    if attempt < MAX_RETRIES:
                        logger.warning(f"[TweetGen/Gemini] 429 — retry {attempt}/{MAX_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.warning("[TweetGen/Gemini] Quota épuisé → tentative Mistral...")
                        raise QuotaExhaustedError("Gemini quota épuisé")
                else:
                    logger.error(f"[TweetGen/Gemini] Erreur: {e}")
                    return None

    # ── Mistral HTTP direct ───────────────────────────────────────────────────

    def _mistral_call(self, prompt):
        if not self.mistral_key:
            return None
        try:
            payload = {
                "model": self.m_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self.temperature,
            }
            headers = {
                "Authorization": f"Bearer {self.mistral_key}",
                "Content-Type": "application/json"
            }
            r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content']
        except Exception as e:
            logger.error(f"[TweetGen/Mistral] Erreur: {e}")
            return None

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(self, analysis, original_text='', region='Global'):
        prompt = self._build_prompt(analysis, original_text, region)

        # 1 — Gemini
        try:
            text = self._gemini_call(prompt)
            if text:
                logger.info("[TweetGen] ✅ Gemini OK")
                return self._parse(text)
        except QuotaExhaustedError:
            pass

        # 2 — Mistral fallback
        text = self._mistral_call(prompt)
        if text:
            logger.info("[TweetGen] ✅ Mistral fallback OK")
            return self._parse(text)

        logger.error("[TweetGen] ❌ Tous les providers ont échoué")
        raise QuotaExhaustedError("Gemini + Mistral : indisponibles.")

    def _parse(self, text):
        result = {'tweet_body': '', 'hashtags': '', 'full_tweet': ''}
        for line in text.strip().split('\n'):
            if line.upper().startswith('TWEET:'):
                result['tweet_body'] = line.split(':', 1)[1].strip()
            elif line.upper().startswith('HASHTAGS:'):
                result['hashtags'] = line.split(':', 1)[1].strip()

        combined = f"{result['tweet_body']} {result['hashtags']}".strip()
        if len(combined) > 280:
            max_body = 280 - len(result['hashtags']) - 1
            result['tweet_body'] = result['tweet_body'][:max_body].rsplit(' ', 1)[0] + '…'
            combined = f"{result['tweet_body']} {result['hashtags']}".strip()

        result['full_tweet'] = combined
        result['char_count'] = len(combined)
        return result
