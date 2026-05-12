"""
Tweet Generator — Triple provider avec fallback automatique
1. Google Gemini 2.0 Flash Lite  (primary)
2. Mistral Small                 (fallback, retry x3)
3. Groq llama-3.1-8b-instant     (fallback final, retry x3)
"""
from google import genai
from google.genai import types
import requests
import logging
import os
import time

from analyzer.vision import QuotaExhaustedError

logger = logging.getLogger(__name__)

GEMINI_RETRIES  = 3
MISTRAL_RETRIES = 3
GROQ_RETRIES    = 3
RETRY_DELAY     = 20

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"


def _is_rate_limit(e):
    return '429' in str(e) or 'rate' in str(e).lower()

def _is_server_error(e):
    code = None
    if hasattr(e, 'response') and e.response is not None:
        code = e.response.status_code
    return code in (500, 502, 503, 504) or any(str(c) in str(e) for c in [500, 502, 503, 504])


class TweetGenerator:
    def __init__(self, config):
        self.gemini      = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        cfg              = config['gemini']
        self.g_model     = cfg['model']
        self.temperature = cfg['temperature']

        self.mistral_key = os.environ.get('MISTRAL_API_KEY', '')
        self.m_model     = config.get('mistral', {}).get('text_model', 'mistral-small-latest')

        self.groq_key    = os.environ.get('GROQ_API_KEY', '')
        self.groq_model  = config.get('groq', {}).get('text_model', 'llama-3.1-8b-instant')

        providers = ['Gemini']
        if self.mistral_key: providers.append('Mistral')
        if self.groq_key:    providers.append('Groq')
        logger.info(f"[TweetGen] Providers actifs: {' → '.join(providers)}")

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

    def _gemini(self, prompt):
        for attempt in range(1, GEMINI_RETRIES + 1):
            try:
                r = self.gemini.models.generate_content(
                    model=self.g_model, contents=prompt,
                    config=types.GenerateContentConfig(temperature=self.temperature))
                return r.text
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                    if attempt < GEMINI_RETRIES:
                        logger.warning(f"[TweetGen/Gemini] 429 — retry {attempt}/{GEMINI_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.warning("[TweetGen/Gemini] Quota épuisé → Mistral...")
                        return None
                else:
                    logger.error(f"[TweetGen/Gemini] Erreur: {e}")
                    return None

    def _mistral(self, prompt):
        if not self.mistral_key:
            return None
        payload = {
            "model": self.m_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature
        }
        headers = {"Authorization": f"Bearer {self.mistral_key}", "Content-Type": "application/json"}
        for attempt in range(1, MISTRAL_RETRIES + 1):
            try:
                r = requests.post(MISTRAL_URL, json=payload, headers=headers, timeout=30)
                r.raise_for_status()
                return r.json()['choices'][0]['message']['content']
            except Exception as e:
                if _is_rate_limit(e):
                    if attempt < MISTRAL_RETRIES:
                        logger.warning(f"[TweetGen/Mistral] 429 — retry {attempt}/{MISTRAL_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.warning("[TweetGen/Mistral] Rate limit → Groq...")
                        return None
                else:
                    logger.error(f"[TweetGen/Mistral] Erreur: {e}")
                    return None

    def _groq(self, prompt):
        if not self.groq_key:
            return None
        payload = {
            "model": self.groq_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.temperature,
            "max_tokens": 512
        }
        headers = {"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"}
        for attempt in range(1, GROQ_RETRIES + 1):
            try:
                r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=30)
                r.raise_for_status()
                return r.json()['choices'][0]['message']['content']
            except Exception as e:
                if _is_server_error(e) or _is_rate_limit(e):
                    if attempt < GROQ_RETRIES:
                        wait = RETRY_DELAY * attempt
                        logger.warning(f"[TweetGen/Groq] Erreur temporaire — retry {attempt}/{GROQ_RETRIES} dans {wait}s...")
                        time.sleep(wait)
                    else:
                        logger.error(f"[TweetGen/Groq] Échec après {GROQ_RETRIES} tentatives: {e}")
                        return None
                else:
                    logger.error(f"[TweetGen/Groq] Erreur: {e}")
                    return None

    def generate(self, analysis, original_text='', region='Global'):
        prompt = self._build_prompt(analysis, original_text, region)
        for fn, label in [
            (lambda: self._gemini(prompt),  'Gemini'),
            (lambda: self._mistral(prompt), 'Mistral'),
            (lambda: self._groq(prompt),    'Groq'),
        ]:
            text = fn()
            if text:
                logger.info(f"[TweetGen] ✅ {label}")
                return self._parse(text)

        logger.error("[TweetGen] ❌ Tous les providers ont échoué")
        raise QuotaExhaustedError("Gemini + Mistral + Groq : tous indisponibles.")

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
