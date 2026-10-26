"""Bounded downloads and persistent thumbnails for known catalog images."""
import asyncio
from hashlib import sha256
from io import BytesIO
import ipaddress
import logging
import os
import random
import shutil
from pathlib import Path
import socket
import tempfile
import time
from urllib.parse import urljoin, urlsplit

import httpx
from PIL import Image, ImageOps
from app.repositories.media import MediaRepository


logger = logging.getLogger(__name__)
MEDIA_HOSTS = frozenset({
    "vikisews.com", "storage.yandexcloud.net", "grasser.ru", "helpersew.com",
    "studio-yusupova.ru", "sewitnow.ru", "api.sewitnow.ru",
    "sellty-assets-prod.storage.yandexcloud.net", "static.tildacdn.com", "static.tildacdn.net",
}) | frozenset(host.strip().lower() for host in os.getenv('MEDIA_ALLOWED_HOSTS', '').split(',') if host.strip())
MAX_BYTES = 12 * 1024 * 1024
MAX_PIXELS = 25_000_000


class ImageUnavailable(Exception):
    pass


def image_key(url: str) -> str:
    return sha256(url.encode()).hexdigest()


class ImageCache:
    def __init__(self, root: Path, *, client: httpx.AsyncClient | None = None,
                 repository: MediaRepository | None = None):
        self.root = root
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=4), follow_redirects=False, trust_env=False,
            headers={"User-Agent": "allsewpattern/1.0 (catalog image cache)"},
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
        )
        self._owned_client = client is None
        self.repository = repository
        self._gate = asyncio.Semaphore(2)
        self._locks: dict[str, asyncio.Lock] = {}
        self._failed: dict[str, float] = {}
        self.requests_made = 0
        self.retries_made = 0
        self.bytes_downloaded = 0

    async def aclose(self):
        if self._owned_client:
            await self.client.aclose()

    async def validate_url(self, url: str):
        parts = urlsplit(url)
        if (parts.scheme not in {"https", "http"} or parts.hostname not in MEDIA_HOSTS
                or parts.username or parts.password or parts.port not in {None, 80, 443}):
            raise ImageUnavailable("Untrusted image host")
        addresses = await asyncio.to_thread(socket.getaddrinfo, parts.hostname, parts.port or 443)
        if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
            raise ImageUnavailable("Nonpublic image address")

    def cached_path(self, url: str, size: str) -> Path:
        return self.root / image_key(url)[:2] / f"{image_key(url)}-{size}.webp"

    async def get(self, url: str, size: str = "thumb", *, referer=None, refresh=False, priority=200) -> Path:
        if size not in {"thumb", "detail"}:
            raise ImageUnavailable("Unknown image size")
        target = self.cached_path(url, size)
        if target.is_file() and not refresh:
            if self.repository:
                await asyncio.to_thread(self.repository.observed_cached, image_key(url), url, target.stat().st_mtime,
                    referer=referer, priority=priority)
            return target
        key = image_key(url)
        if self._failed.get(key, 0) > time.monotonic():
            raise ImageUnavailable("Image temporarily unavailable")
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if target.is_file() and not refresh:
                return target
            if self._failed.get(key, 0) > time.monotonic():
                raise ImageUnavailable("Image temporarily unavailable")
            if self.repository:
                await asyncio.to_thread(self.repository.register, key, url, priority=priority, referer=referer)
                state = await asyncio.to_thread(self.repository.get, key)
            lease = None
            try:
                for attempt in range(3):
                    try:
                        async with self._gate:
                            if self.repository:
                                if lease is None:
                                    lease = await asyncio.to_thread(self.repository.claim, key,
                                        force=state['state'] == 'evicted' and priority >= 200)
                                    owns = bool(lease)
                                else:
                                    owns = await asyncio.to_thread(self.repository.renew, key, lease)
                                if not owns:
                                    raise ImageUnavailable('Image queued for retry or owned by another worker')
                            data = await asyncio.wait_for(self._download(url, referer=referer), timeout=25)
                            await asyncio.to_thread(self._encode, data, url)
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError, TimeoutError) as exc:
                        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else 0
                        retry_after = self.retry_after(exc)
                        if (attempt == 2 or (status and status not in {408, 429, 500, 502, 503, 504, 522, 524})
                                or retry_after > 30):
                            raise
                        self.retries_made += 1
                        await asyncio.sleep(max(retry_after, 2 ** attempt * random.uniform(0.8, 1.2)))
                self._failed.pop(key, None)
                if self.repository:
                    await asyncio.to_thread(self.repository.ready, key, owner=lease)
                return target
            except (httpx.HTTPError, OSError, ValueError, Image.DecompressionBombError,
                    TimeoutError, ImageUnavailable) as exc:
                self._failed[key] = time.monotonic() + 60
                if self.repository and lease:
                    status = f' HTTP {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError) else ''
                    reason = ': ' + str(exc) if isinstance(exc, ImageUnavailable) else status
                    await asyncio.to_thread(self.repository.failed, key, type(exc).__name__ + reason,
                        retry_after=self.retry_after(exc), owner=lease)
                logger.warning("Image cache miss failed: key=%s host=%s error=%s", key[:12], urlsplit(url).hostname, type(exc).__name__)
                if target.is_file():
                    return target
                raise ImageUnavailable("Image could not be downloaded") from None

    @staticmethod
    def retry_after(error) -> float:
        if not isinstance(error, httpx.HTTPStatusError):
            return 0
        value = error.response.headers.get('retry-after', '')
        try:
            return max(0, float(value))
        except ValueError:
            from email.utils import parsedate_to_datetime
            try:
                return max(0, parsedate_to_datetime(value).timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                return 0

    async def _download(self, url: str, *, referer=None) -> bytes:
        for _ in range(4):
            await self.validate_url(url)
            headers = {'Referer': referer} if referer else {}
            self.requests_made += 1
            async with self.client.stream("GET", url, headers=headers, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageUnavailable("Invalid image redirect")
                    url = urljoin(url, location)
                    continue
                response.raise_for_status()
                content_type = response.headers.get('content-type', '').split(';')[0].lower().strip()
                if not (content_type.startswith('image/') or content_type in {
                        '', 'application/octet-stream', 'binary/octet-stream', 'application/binary'}):
                    raise ImageUnavailable("Not an image")
                if int(response.headers.get("content-length") or 0) > MAX_BYTES:
                    raise ImageUnavailable("Image too large")
                chunks, length = [], 0
                async for chunk in response.aiter_bytes():
                    length += len(chunk)
                    if length > MAX_BYTES:
                        raise ImageUnavailable("Image too large")
                    chunks.append(chunk)
                self.bytes_downloaded += length
                return b"".join(chunks)
        raise ImageUnavailable("Too many image redirects")

    def _encode(self, data: bytes, url: str):
        with Image.open(BytesIO(data)) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ImageUnavailable("Image dimensions too large")
            original.draft('RGB', (1280,1280))
            original.thumbnail((1280,1280), Image.Resampling.LANCZOS, reducing_gap=3)
            oriented = ImageOps.exif_transpose(original)
            if 'A' in oriented.getbands() or 'transparency' in oriented.info:
                rgba = oriented.convert('RGBA')
                image = Image.new('RGB', rgba.size, 'white')
                image.paste(rgba, mask=rgba.getchannel('A'))
            else:
                image = oriented.convert('RGB')
        for size, edge in (("thumb", 384), ("detail", 1280)):
            target = self.cached_path(url, size)
            target.parent.mkdir(parents=True, exist_ok=True)
            scaled = image.copy()
            scaled.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                    temporary = Path(output.name)
                    scaled.save(output, format="WEBP", quality=78 if size == "thumb" else 86, method=3)
                os.replace(temporary, target)
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)

    def prune(self, *, max_bytes=768 * 1024 * 1024, reserve_bytes=512 * 1024 * 1024):
        if not self.root.exists():
            return 0
        records = self.repository.retention() if self.repository else {}
        files = []
        for path in self.root.glob('*/*.webp'):
            try:
                files.append((path, path.stat()))
            except FileNotFoundError:
                continue
        for path in self.root.glob('??/tmp*'):
            try:
                if path.stat().st_mtime < time.time() - 3600:
                    path.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
        total = sum(stat.st_size for _, stat in files)
        free = shutil.disk_usage(self.root).free
        def rank(entry):
            path, stat = entry
            record = records.get(path.name.split('-')[0], {})
            cover = path.name.endswith('-thumb.webp') and record.get('priority', 0) >= 100
            return (cover, record.get('last_access', 0), stat.st_mtime)
        removed = 0
        for path, stat in sorted(files, key=rank):
            if total <= max_bytes and free >= reserve_bytes:
                break
            if records.get(path.name.split('-')[0], {}).get('lease_until', 0) > time.time():
                continue
            path.unlink(missing_ok=True)
            if self.repository and path.name.endswith('-thumb.webp'):
                self.repository.evicted(path.name.split('-')[0])
            total -= stat.st_size
            free += stat.st_size
            removed += 1
        return removed


def photo_urls(product_id: int, urls: list[str]) -> dict:
    def link(index: int, size: str):
        return f"/api/products/{product_id}/image/{index}?size={size}&v={image_key(urls[index])[:12]}"
    return {
        "thumbnail_url": link(0, "thumb") if urls else None,
        "photo_urls": [link(i, "detail") for i in range(len(urls))],
        "photo_thumbnails": [link(i, "thumb") for i in range(len(urls))],
        "image_count": len(urls),
    }
