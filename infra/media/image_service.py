import hashlib
import json
import os
import random
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional, Tuple

from astrbot.api import logger
from ..remote_storage.base import RemoteStorage


class ImageService:
    URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
    PHOTO_NAME_RE = re.compile(
        r"^(?P<platform>[^_]+)_(?P<date>\d{8})_(?P<group>[^_]+)_(?P<user>[^_]+)_(?P<time>\d{6})_(?P<rand>[^_]+)\.(?P<ext>[A-Za-z0-9]+)$"
    )

    def __init__(
        self,
        original_dir: Path,
        cache_media_dir: Path,
        get_config: Callable[[str, object], object],
        remote_storage: RemoteStorage,
    ):
        self.original_dir = original_dir
        self.cache_media_dir = cache_media_dir
        self.get_config = get_config
        self.remote_storage = remote_storage

    def _get_attr(self, comp: Any, keys: list[str]) -> str:
        for key in keys:
            value = getattr(comp, key, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def save_image_component(
        self,
        image_comp: Any,
        platform: str,
        date_str: str,
        group_id: str,
        user_id: str,
        time_hms: str,
    ) -> Optional[str]:
        ext = self._get_attr(image_comp, ["ext", "suffix", "format"])
        if not ext:
            source_for_ext = self._get_attr(image_comp, ["file", "path", "url", "image"])
            _, guessed = os.path.splitext(source_for_ext)
            ext = guessed.lstrip(".") if guessed else "jpg"
        ext = re.sub(r"[^A-Za-z0-9]", "", ext.lower()) or "jpg"
        image_name = f"{platform}_{date_str}_{group_id}_{user_id}_{time_hms}_{random.randint(10000, 99999)}.{ext}"

        local_dir = self.original_dir / platform / date_str
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / image_name

        source_path = self._get_attr(image_comp, ["file", "path", "image"])
        source_url = self._get_attr(image_comp, ["url"])
        try:
            if source_path and os.path.exists(source_path):
                shutil.copyfile(source_path, local_path)
            elif source_url.startswith("http://") or source_url.startswith("https://"):
                urllib.request.urlretrieve(source_url, local_path)
            else:
                return None
        except Exception:
            return None

        max_mb = float(self.get_config("photo_max_size_mb", 10))
        limit = int(max(0.0, max_mb) * 1024 * 1024)
        if not local_path.exists() or local_path.stat().st_size <= 0:
            local_path.unlink(missing_ok=True)
            return None
        if limit > 0 and local_path.stat().st_size > limit:
            local_path.unlink(missing_ok=True)
            return None
        return image_name

    def _validate_photo_name(self, image_name: str):
        m = self.PHOTO_NAME_RE.match(image_name)
        if not m:
            return None
        if not m.group("date").isdigit() or len(m.group("date")) != 8:
            return None
        return m

    def resolve_photo_path(self, image_name: str) -> Tuple[Optional[str], Optional[str]]:
        m = self._validate_photo_name(image_name)
        if not m:
            return None, None

        platform = m.group("platform")
        date_str = m.group("date")
        local_path = self.original_dir / platform / date_str / image_name
        if local_path.exists() and local_path.stat().st_size > 0:
            return str(local_path), "local"

        cache_path = self.cache_media_dir / image_name
        relative = Path("original_data") / platform / date_str / image_name
        try:
            ok = self.remote_storage.fetch(relative, cache_path)
            if ok and cache_path.exists() and cache_path.stat().st_size > 0:
                return str(cache_path), "remote_cache"
        except Exception as ex:
            logger.error("[randomreply_plugin] 远端拉取失败: image=%s err=%s", image_name, ex)
        return None, None

    def fetch_api_image_reference(self) -> Optional[str]:
        api_url = str(self.get_config("api_image_url", "")).strip()
        if not api_url:
            return None

        try:
            request = urllib.request.Request(api_url, method="GET")
            with urllib.request.urlopen(request, timeout=float(self.get_config("remote_timeout", 10))) as resp:
                body = resp.read()
                content_type = str(resp.headers.get("Content-Type", "")).lower()

            if "image" in content_type:
                ext = "jpg"
                if "png" in content_type:
                    ext = "png"
                elif "gif" in content_type:
                    ext = "gif"
                digest = hashlib.md5(body).hexdigest()[:12]
                path = self.cache_media_dir / f"api_{digest}.{ext}"
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("wb") as f:
                    f.write(body)
                if path.exists() and path.stat().st_size > 0:
                    return str(path)
                return None

            text_body = body.decode("utf-8", errors="ignore")
            try:
                parsed = json.loads(text_body)
                if isinstance(parsed, dict):
                    for key in ("url", "image", "img", "data"):
                        value = parsed.get(key)
                        if isinstance(value, str) and value.startswith(("http://", "https://")):
                            return value
            except Exception:
                pass

            m = self.URL_RE.search(text_body)
            if m:
                return m.group(0)
        except Exception as ex:
            logger.error("[randomreply_plugin] API 图片获取失败: url=%s err=%s", api_url, ex)
        return None
