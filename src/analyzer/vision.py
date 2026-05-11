"""
Vision Analyzer — Double provider avec fallback automatique
Primary  : Google Gemini 2.0 Flash Lite
Fallback : Mistral Small (multimodal)
"""
from google import genai
import PIL.Image
import base64
import logging
import os
import time

try:
    from mistralai import Mistral
    MISTRAL_AVAILABLE = True
except ImportError:
    Mistral = None
    MISTRAL_AVAILABLE = False

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 25

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

TEXT_PROMPT_TEMPLATE = """You are an expert in viral internet content. Based only on this text description:

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
    """Levée quand tous les providers disponibles sont épuisés."""
    pass


class VisionAnalyzer:
    def __init__(self, config):
        # ── Gemini (primary) ──────────────────────────────────────────────────
        self.gemini  = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        self.g_model = config['gemini']['model']

        # ── Mistral (fallback) ────────────────────────────────────────────────
        self.mistral = None
        self.m_model = config.get('mistral', {}).get('vision_model', 'mistral-small-latest')

        if MISTRAL_AVAILABLE:
            mistral_key = os.environ.get('MISTRAL_API_KEY', '')
            if mistral_key:
                self.mistral = Mistral(api_key=mistral_key)
                logger.info("[Vision] Mistral fallback activé ✅")
            else:
                logger.warning("[Vision] MISTRAL_API_KEY absent — fallback désactivé")
        else:
            logger.warning("[Vision] Package mistralai non disponible — fallback désactivé")

    # ── Gemini ────────────────────────────────────────────────────────────────

    def _gemini_call(self, contents):
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = self.gemini.models.generate_content(
                    model=self.g_model, contents=contents)
                return r.text
            except Exception as e:
                if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                    if attempt < MAX_RETRIES:
                        logger.warning(f"[Vision/Gemini] 429 — retry {attempt}/{MAX_RETRIES} dans {RETRY_DELAY}s...")
                        time.sleep(RETRY_DELAY)
                    else:
                        logger.warning("[Vision/Gemini] Quota épuisé → tentative Mistral...")
                        raise QuotaExhaustedError("Gemini quota épuisé")
                else:
                    logger.error(f"[Vision/Gemini] Erreur: {e}")
                    return None

    # ── Mistral ───────────────────────────────────────────────────────────────

    def _mistral_vision_call(self, image_path, prompt):
        if not self.mistral:
            return None
        try:
            ext  = os.path.splitext(image_path)[1].lower()
            mime = EXT_TO_MIME.get(ext, 'image/jpeg')
            with open(image_path, 'rb') as f:
                b64 = base64.b64encode(f.read()).decode('utf-8')
            r = self.mistral.chat.complete(
                model=self.m_model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}}
                ]}]
            )
            return r.choices[0].message.content
        except Exception as e:
            logger.error(f"[Vision/Mistral] Erreur: {e}")
            return None

    def _mistral_text_call(self, prompt):
        if not self.mistral:
            return None
        try:
            r = self.mistral.chat.complete(
                model=self.m_model,
                messages=[{"role": "user", "content": prompt}]
            )
            return r.choices[0].message.content
        except Exception as e:
            logger.error(f"[Vision/Mistral text] Erreur: {e}")
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

        # 1 — Gemini
        try:
            text = self._gemini_call([prompt, img])
            if text:
                logger.info("[Vision] ✅ Gemini OK")
                return self._parse(text)
        except QuotaExhaustedError:
            pass

        # 2 — Mistral fallback
        text = self._mistral_vision_call(media_path, prompt)
        if text:
            logger.info("[Vision] ✅ Mistral fallback OK")
            return self._parse(text)

        # 3 — Les deux ont échoué
        logger.error("[Vision] ❌ Tous les providers ont échoué")
        raise QuotaExhaustedError("Gemini + Mistral : indisponibles.")

    def _analyze_text_only(self, context):
        if not context:
            return None
        prompt = TEXT_PROMPT_TEMPLATE.format(context=context[:400])

        try:
            text = self._gemini_call(prompt)
            if text:
                result = self._parse(text)
                if result:
                    result['IS_VIDEO'] = True
                return result
        except QuotaExhaustedError:
            pass

        text = self._mistral_text_call(prompt)
        if text:
            result = self._parse(text)
            if result:
                result['IS_VIDEO'] = True
            return result

        raise QuotaExhaustedError("Gemini + Mistral : indisponibles.")

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
