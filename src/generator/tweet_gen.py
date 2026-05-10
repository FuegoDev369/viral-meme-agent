from google import genai
from google.genai import types
import logging
import os

logger = logging.getLogger(__name__)


class TweetGenerator:
    def __init__(self, config):
        self.client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
        cfg = config['gemini']
        self.model = cfg['model']
        self.temperature = cfg['temperature']
        tw = config['tweet_generator']
        self.max_length = tw['max_length']
        self.hashtags_count = tw['hashtags_count']
        self.style = tw['style']

    def generate(self, analysis, original_text='', region='Global'):
        try:
            prompt = f"""You are a viral Twitter/X growth expert. Your job is to craft tweets that maximize impressions and engagement.

CONTENT ANALYSIS:
- Description: {analysis.get('DESCRIPTION', '')}
- Humor type: {analysis.get('HUMOR_TYPE', '')}
- Why it would go viral: {analysis.get('VIRALITY_REASON', '')}
- Region relevance: {analysis.get('REGION_RELEVANCE', region)}
- Category: {analysis.get('TREND_CATEGORY', '')}
- Original context: {original_text[:250] if original_text else 'N/A'}

RULES:
- Language: English ONLY
- Max tweet length: {self.max_length} characters (tweet + hashtags combined)
- Style: {self.style}
- Must include exactly {self.hashtags_count} hashtags at the end
- Start with a powerful hook: a question, bold claim, or relatable statement
- Max 2 emojis — make it feel human, not AI
- Do NOT use quotation marks around the tweet
- Do NOT reference Reddit or any scraping source

Respond with ONLY these two lines, nothing else:

TWEET: [your tweet text without hashtags]
HASHTAGS: [#tag1 #tag2 #tag3]
"""
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=self.temperature),
            )
            return self._parse(response.text)

        except Exception as e:
            logger.error(f"Tweet generation failed: {e}")
            return None

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
