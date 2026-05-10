import requests
import os
import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONTENT_TYPE_EXT = {
    'image/jpeg': '.jpg',
    'image/png': '.png',
    'image/gif': '.gif',
    'image/webp': '.webp',
    'video/mp4': '.mp4',
}


class MediaDownloader:
    def __init__(self, config):
        self.download_dir = config['media']['download_dir']
        self.max_size = config['media']['max_size_mb'] * 1024 * 1024
        self.allowed_types = config['media']['allowed_types']
        Path(self.download_dir).mkdir(parents=True, exist_ok=True)
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }

    def _get_filepath(self, url, content_type):
        ext = CONTENT_TYPE_EXT.get(content_type, '.bin')
        name = hashlib.md5(url.encode()).hexdigest()[:14]
        return os.path.join(self.download_dir, f"{name}{ext}")

    def download(self, url):
        try:
            r = requests.get(url, headers=self.headers, timeout=15, stream=True)
            r.raise_for_status()

            content_type = r.headers.get('content-type', '').split(';')[0].strip()

            if content_type not in self.allowed_types:
                logger.debug(f"Skipping unsupported type: {content_type} ({url[:60]})")
                return None

            content_length = int(r.headers.get('content-length', 0))
            if content_length > self.max_size:
                logger.warning(f"File too large ({content_length} bytes), skipping")
                return None

            filepath = self._get_filepath(url, content_type)

            # Already downloaded — reuse
            if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
                logger.debug(f"Reusing cached: {os.path.basename(filepath)}")
                return filepath

            with open(filepath, 'wb') as f:
                downloaded = 0
                for chunk in r.iter_content(chunk_size=8192):
                    downloaded += len(chunk)
                    if downloaded > self.max_size:
                        logger.warning("File exceeded max size during download, aborting")
                        f.close()
                        os.remove(filepath)
                        return None
                    f.write(chunk)

            logger.info(f"Downloaded: {os.path.basename(filepath)} ({downloaded // 1024} KB)")
            return filepath

        except Exception as e:
            logger.warning(f"Download failed for {url[:80]}: {e}")
            return None

    def download_best(self, media_urls):
        """Try each URL in order, return first successful download."""
        for url in media_urls:
            path = self.download(url)
            if path:
                return path
        logger.warning("All media URLs failed for this post")
        return None
