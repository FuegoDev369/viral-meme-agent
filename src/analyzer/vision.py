from google import genai
import PIL.Image
import logging
import os

logger = logging.getLogger(__name__)


class VisionAnalyzer:
    def __init__(self, config):
        self.client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        self.model = config['gemini']['model']

    def analyze(self, media_path, post_context=''):
        try:
            if media_path.lower().endswith('.mp4'):
                return self._analyze_text_only(post_context)

            img = PIL.Image.open(media_path)

            prompt = f"""You are an expert in viral internet content. Analyze this image/meme carefully.

Context from scraper: "{post_context[:300] if post_context else 'N/A'}"

Provide your analysis in EXACTLY this format (no extra text):

DESCRIPTION: [2-3 sentences describing the image and what makes it funny/interesting/relatable]
HUMOR_TYPE: [one of: relatable / absurd / political / wholesome / shock / satire / observational]
VIRALITY_SCORE: [integer 1-10, where 10 = maximum viral potential]
VIRALITY_REASON: [1-2 sentences on why this would go viral]
REGION_RELEVANCE: [which regions/cultures would best relate: Global / USA / Africa / Asia / Europe]
TREND_CATEGORY: [one of: meme / reaction / wholesome / politics / sports / entertainment / news / lifestyle]
"""
            response = self.client.models.generate_content(
                model=self.model,
                contents=[prompt, img],
            )
            return self._parse(response.text)

        except PIL.UnidentifiedImageError:
            logger.warning(f"Cannot open image: {media_path}")
            return None
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            return None

    def _analyze_text_only(self, context):
        if not context:
            return None
        try:
            prompt = f"""You are an expert in viral internet content. Based only on this text description of a video:

"{context[:400]}"

Provide your analysis in EXACTLY this format (no extra text):

DESCRIPTION: [What this content is likely about]
HUMOR_TYPE: [one of: relatable / absurd / political / wholesome / shock / satire / observational]
VIRALITY_SCORE: [integer 1-10]
VIRALITY_REASON: [Why this would go viral]
REGION_RELEVANCE: [Global / USA / Africa / Asia / Europe]
TREND_CATEGORY: [meme / reaction / wholesome / politics / sports / entertainment / news / lifestyle]
"""
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
            )
            result = self._parse(response.text)
            if result:
                result['IS_VIDEO'] = True
            return result
        except Exception as e:
            logger.error(f"Text-only analysis failed: {e}")
            return None

    def _parse(self, text):
        result = {}
        for line in text.strip().split('\n'):
            if ':' in line:
                key, _, value = line.partition(':')
                result[key.strip()] = value.strip()
        try:
            raw = result.get('VIRALITY_SCORE', '0')
            result['VIRALITY_SCORE'] = int(''.join(filter(str.isdigit, raw.split('/')[0])) or '0')
        except Exception:
            result['VIRALITY_SCORE'] = 0
        return result if result else None
