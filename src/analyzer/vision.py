"""
Vision Analyzer — Triple provider avec fallback automatique
1. Google Gemini 2.0 Flash Lite       (primary)
2. Mistral Small                       (fallback, retry x3)
3. Groq llama-3.2-11b-vision-preview  (fallback final, retry x3)
"""
from google import genai
import PIL.Image
import requests
import base64
import logging
import os
import time

logger = logging.getLogger(__name__)

GEMINI_RETRIES = 3
MISTRAL_RETRIES = 3
GROQ_RETRIES = 3
RETRY_DELAY = 20  # secondes

MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_URL    = "https://api.groq.com/openai/v1/chat/completions"

EXT_TO_MIME = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png',  '.gif':  'image/gif',
    '.webp': 'image/webp',
}

PROMPT_TEMPLATE = """You are an expert in viral internet content. Analyze this image/meme carefully.

Context from scraper: "{context}"

Provide your analysis in EXACTLY this format (no extra text):

DESCRIPTION: [2-3 sentences describing the image and what makes it funny/interesting/relatable]
HUMOR_TYPE: [one of: relatable / absurd / political / wholesome / shock / satire / observational]
VIRALITY_SCORE: [integer 1-10, where 10 = maximum viral potential]
VIRALITY_REASON: [1-2 sentences on why this would go viral]
REGION_RELEVANCE: [which regions/cultures would best relate: Global / USA / Africa / Asia / Europe]
TREND_CATEGORY: [one of: meme / reaction / wholesome / politics / sports / entertainment / news / lifestyle]
"""

TEXT_PROMPT = """You are an expert in viral internet content. Based only on this text description:

"{context}"

Provide your analysis in EXACTLY this format (no extra text):

DESCRIPTION: [What this content is likely about]
HUMOR_TYPE: [one of: relatable / absurd / political / wholesome / shock / satire / observational]
VIRALITY_SCORE: [integer 1-10]
VIRALITY_REASON: [Why this would go viral]
REGION_RELEVANCE: [Global / USA / Africa / Asia / Europe]
TREND_CATEGORY: [meme / reaction / wholesome / politics / sports / entertainment / news / lifestyle]
"""


class QuotaExhaustedError(Exception):
    pass


def _img_to_b64(image_path):
    ext  = os.path.splitext(image_path)[1].lower()
    mime = EXT_TO_MIME.get(ext, 'image/jpeg')
    with open(image_path, 'rb') as f:
        b64 = base64.b64encode(f.read()).decode('utf-8')
    return mime, b64


def _is_rate_limit(e):
    return '429' in str(e) or 'rate' in str(e).lower()

def _is_server_error(e):
    code = None
    if hasattr(e, 'response') and e.response is not None:
        code = e.response.status_code
    return code in (500, 502, 503, 504) or any(str(c) in str(e) for c in [500, 502, 503, 504])


class VisionAnalyzer:
    def __init__(self, config):
        self.gemini  = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        self.g_model = config['gemini']['model']

        self.mistral_key  = os.environ.get('MISTRAL_API_KEY', '')
        self.m_model      = config.get('mistral', {}).get('vision_model', 'mistral-small-latest')

        self.groq_key     = os.environ.get('GROQ_API_KEY', '')
        self.groq_v_model = config.get('groq', {}).get('vision_model', 'llama-3.2-11b-vision-preview')

        providers = ['Gemini']
        if self.mistral_key: providers.append('Mistral')
        if self.groq_key:    providers.append('Groq')
        logger.info(f"[Vision] Providers actifs: {' → '.join(providers)}")

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _gemini(self, contents):
        for attempt in range(1, GEMINI_RETRIES + 1):
            try:
                r = self.gemini.models.generate_content(model=self.g_model, contents=contents)
                return r.text
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                    if attempt < GEMINI_RETRIES:
                        logger.warning(f"[Vision/Gemini] 429 — retry {attempt}/{GEMINI_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.warning("[Vision/Gemini] Quota épuisé → Mistral...")
                        return None
                else:
                    logger.error(f"[Vision/Gemini] Erreur: {e}")
                    return None

    # ── Mistral ───────────────────────────────────────────────────────────────

    def _mistral_vision(self, image_path, prompt):
        if not self.mistral_key:
            return None
        mime, b64 = _img_to_b64(image_path)
        payload = {
            "model": self.m_model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            ]}]
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
                        logger.warning(f"[Vision/Mistral] 429 — retry {attempt}/{MISTRAL_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.warning("[Vision/Mistral] Rate limit persistant → Groq...")
                        return None
                else:
                    logger.error(f"[Vision/Mistral] Erreur: {e}")
                    return None

    def _mistral_text(self, prompt):
        if not self.mistral_key:
            return None
        payload = {"model": self.m_model, "messages": [{"role": "user", "content": prompt}]}
        headers = {"Authorization": f"Bearer {self.mistral_key}", "Content-Type": "application/json"}
        for attempt in range(1, MISTRAL_RETRIES + 1):
            try:
                r = requests.post(MISTRAL_URL, json=payload, headers=headers, timeout=30)
                r.raise_for_status()
                return r.json()['choices'][0]['message']['content']
            except Exception as e:
                if _is_rate_limit(e):
                    if attempt < MISTRAL_RETRIES:
                        logger.warning(f"[Vision/Mistral text] 429 — retry {attempt}/{MISTRAL_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        return None
                else:
                    logger.error(f"[Vision/Mistral text] Erreur: {e}")
                    return None

    # ── Groq ──────────────────────────────────────────────────────────────────

    def _groq_vision(self, image_path, prompt):
        if not self.groq_key:
            return None
        try:
            mime, b64 = _img_to_b64(image_path)
        except Exception as e:
            logger.error(f"[Vision/Groq] Impossible de lire l'image: {e}")
            return None

        payload = {
            "model": self.groq_v_model,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
            ]}],
            "max_tokens": 1024
        }
        headers = {"Authorization": f"Bearer {self.groq_key}", "Content-Type": "application/json"}

        for attempt in range(1, GROQ_RETRIES + 1):
            try:
                r = requests.post(GROQ_URL, json=payload, headers=headers, timeout=45)
                r.raise_for_status()
                return r.json()['choices'][0]['message']['content']
            except Exception as e:
                if _is_server_error(e) or _is_rate_limit(e):
                    if attempt < GROQ_RETRIES:
                        wait = RETRY_DELAY * attempt  # backoff progressif
                        logger.warning(f"[Vision/Groq] Erreur temporaire — retry {attempt}/{GROQ_RETRIES} dans {wait}s...")
                        time.sleep(wait)
                    else:
                        logger.error(f"[Vision/Groq] Échec après {GROQ_RETRIES} tentatives: {e}")
                        return None
                else:
                    logger.error(f"[Vision/Groq] Erreur: {e}")
                    return None

    def _groq_text(self, prompt):
        if not self.groq_key:
            return None
        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": [{"role": "user", "content": prompt}],
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
                        logger.warning(f"[Vision/Groq text] retry {attempt}/{GROQ_RETRIES} dans {wait}s...")
                        time.sleep(wait)
                    else:
                        return None
                else:
                    logger.error(f"[Vision/Groq text] Erreur: {e}")
                    return None

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze(self, media_path, post_context=''):
        if media_path.lower().endswith('.mp4'):
            return self._analyze_text_only(post_context)
        try:
            img    = PIL.Image.open(media_path)
            prompt = PROMPT_TEMPLATE.format(context=post_context[:300] or 'N/A')
        except PIL.UnidentifiedImageError:
            logger.warning(f"Impossible d'ouvrir: {media_path}")
            return None

        for fn, label in [
            (lambda: self._gemini([prompt, img]),           'Gemini'),
            (lambda: self._mistral_vision(media_path, prompt), 'Mistral'),
            (lambda: self._groq_vision(media_path, prompt),    'Groq'),
        ]:
            text = fn()
            if text:
                logger.info(f"[Vision] ✅ {label}")
                return self._parse(text)

        logger.error("[Vision] ❌ Tous les providers ont échoué")
        raise QuotaExhaustedError("Gemini + Mistral + Groq : tous indisponibles.")

    def _analyze_text_only(self, context):
        if not context:
            return None
        prompt = TEXT_PROMPT.format(context=context[:400])
        for fn, label in [
            (lambda: self._gemini(prompt),      'Gemini'),
            (lambda: self._mistral_text(prompt), 'Mistral'),
            (lambda: self._groq_text(prompt),    'Groq'),
        ]:
            text = fn()
            if text:
                logger.info(f"[Vision text] ✅ {label}")
                result = self._parse(text)
                if result:
                    result['IS_VIDEO'] = True
                return result
        raise QuotaExhaustedError("Tous les providers ont échoué (text-only).")

    def _parse(self, text):
        result = {}
        for line in text.strip().split('\n'):
            if ':' in line:
                key, _, value = line.partition(':')
                result[key.strip()] = value.strip()
        try:
            raw = result.get('VIRALITY_SCORE', '0')
            result['VIRALITY_SCORE'] = int(
                ''.join(filter(str.isdigit, raw.split('/')[0])) or '0')
        except Exception:
            result['VIRALITY_SCORE'] = 0
        return result if result else None
