import asyncio
import csv
import datetime as dt
import json
import math
import os
import random
import re
import shutil
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register


class _FileLock:
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.fp = None

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self.fp = open(self.lock_path, "a+b")
        if os.name == "nt":
            import msvcrt

            self.fp.seek(0)
            msvcrt.locking(self.fp.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(self.fp.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.fp:
            return
        if os.name == "nt":
            import msvcrt

            self.fp.seek(0)
            msvcrt.locking(self.fp.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self.fp.fileno(), fcntl.LOCK_UN)
        self.fp.close()


@register("randomreply_plugin", "maxshiro", "跨平台随机回复插件（QQ/Telegram）", "1.2.0")
class RandomReplyPlugin(Star):
    LINK_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)
    PHOTO_NAME_RE = re.compile(
        r"^(?P<platform>[^_]+)_(?P<date>\d{8})_(?P<group>[^_]+)_(?P<user>[^_]+)_(?P<time>\d{6})_(?P<rand>[^_]+)\.(?P<ext>[A-Za-z0-9]+)$"
    )

    def __init__(self, context: Context, config: Optional[AstrBotConfig] = None):
        super().__init__(context)
        self.config = config or {}
        self.plugin_dir = Path(__file__).resolve().parent
        self.data_dir = self.plugin_dir / "data"
        self.original_dir = self.data_dir / "original_data"
        self.cache_media_dir = self.data_dir / "cache_media"
        self.reply_msg_csv = self.data_dir / "reply_msg_data.csv"
        self.reply_photo_csv = self.data_dir / "reply_photo_data.csv"
        self.msg_lock = self.data_dir / ".reply_msg_data.lock"
        self.photo_lock = self.data_dir / ".reply_photo_data.lock"
        self.raw_json_lock_dir = self.data_dir / ".raw_locks"
        self._maintenance_task: Optional[asyncio.Task] = None
        self._maintenance_stop = asyncio.Event()
        self._last_maintenance_run: Dict[str, str] = {}
        self._photo_fail_streak: Dict[str, int] = {}

    async def initialize(self):
        self._ensure_data_layout()
        self._maintenance_task = asyncio.create_task(self._maintenance_loop())
        logger.info("[randomreply_plugin] 插件已加载并初始化数据目录。")

    def _get_config(self, key: str, default: Any) -> Any:
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return default

    def _ensure_data_layout(self):
        self.original_dir.mkdir(parents=True, exist_ok=True)
        self.cache_media_dir.mkdir(parents=True, exist_ok=True)
        self.raw_json_lock_dir.mkdir(parents=True, exist_ok=True)
        if not self.reply_msg_csv.exists():
            self._atomic_write_csv(self.reply_msg_csv, [["消息内容", "权重值", "出现次数"]])
        if not self.reply_photo_csv.exists():
            self._atomic_write_csv(
                self.reply_photo_csv,
                [["图片名称", "出现次数", "失效标记"]],
            )

    def _atomic_write_csv(self, target: Path, rows: List[List[Any]]):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def _atomic_write_json(self, target: Path, data: Any):
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, target)
        finally:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)

    def _is_supported_platform(self, platform_name: str) -> bool:
        platform_name = (platform_name or "").lower()
        platform_keywords = self._get_config(
            "platform_keywords",
            ["aiocqhttp", "qqofficial", "telegram"],
        )
        if not platform_keywords:
            return True
        return any(str(keyword).lower() in platform_name for keyword in platform_keywords)

    def _is_command_like(self, message: str) -> bool:
        prefixes: List[str] = self._get_config("command_prefixes", ["/", "!"])
        return any(message.startswith(prefix) for prefix in prefixes)

    def _extract_image_components(self, event: AstrMessageEvent) -> List[Any]:
        message_chain = getattr(event.message_obj, "message", []) or []
        image_items: List[Any] = []
        for comp in message_chain:
            comp_name = comp.__class__.__name__.lower()
            if "image" in comp_name or "sticker" in comp_name:
                image_items.append(comp)
        return image_items

    def _get_component_attr(self, comp: Any, candidates: List[str]) -> str:
        for key in candidates:
            value = getattr(comp, key, None)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _save_image_component(
        self,
        image_comp: Any,
        platform: str,
        date_str: str,
        group_id: str,
        user_id: str,
        time_hms: str,
    ) -> Optional[str]:
        ext = self._get_component_attr(image_comp, ["ext", "suffix", "format"])
        if not ext:
            source_for_ext = self._get_component_attr(image_comp, ["file", "path", "url", "image"])
            _, guessed = os.path.splitext(source_for_ext)
            ext = guessed.lstrip(".") if guessed else "jpg"
        ext = re.sub(r"[^A-Za-z0-9]", "", ext.lower()) or "jpg"
        image_name = f"{platform}_{date_str}_{group_id}_{user_id}_{time_hms}_{random.randint(10000, 99999)}.{ext}"

        local_dir = self.original_dir / platform / date_str
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / image_name

        source_path = self._get_component_attr(image_comp, ["file", "path", "image"])
        source_url = self._get_component_attr(image_comp, ["url"])
        try:
            if source_path and os.path.exists(source_path):
                shutil.copyfile(source_path, local_path)
            elif source_url.startswith("http://") or source_url.startswith("https://"):
                urllib.request.urlretrieve(source_url, local_path)
            else:
                logger.warning(
                    "[randomreply_plugin] 图片消息缺少可下载来源，跳过保存: platform=%s group=%s attrs=%s",
                    platform,
                    group_id,
                    [k for k in dir(image_comp) if not k.startswith("_")],
                )
                return None
        except Exception as ex:
            logger.error(
                "[randomreply_plugin] 保存图片失败: platform=%s group=%s err=%s",
                platform,
                group_id,
                ex,
            )
            return None

        max_photo_size_mb = float(self._get_config("photo_max_size_mb", 10))
        max_photo_size_bytes = int(max(0.0, max_photo_size_mb) * 1024 * 1024)
        if not local_path.exists() or local_path.stat().st_size <= 0:
            try:
                if local_path.exists():
                    local_path.unlink()
            except Exception:
                pass
            logger.warning(
                "[randomreply_plugin] 图片文件为空，已丢弃: platform=%s group=%s file=%s",
                platform,
                group_id,
                image_name,
            )
            return None
        if max_photo_size_bytes > 0 and local_path.stat().st_size > max_photo_size_bytes:
            current_size = local_path.stat().st_size
            try:
                local_path.unlink(missing_ok=True)
            except Exception:
                pass
            logger.warning(
                "[randomreply_plugin] 图片超过大小阈值，已丢弃: platform=%s group=%s file=%s size=%s threshold=%s",
                platform,
                group_id,
                image_name,
                current_size,
                max_photo_size_bytes,
            )
            return None
        return image_name

    def _compute_w0(self, msg_length: int, max_length: int) -> float:
        if max_length <= 1:
            return 0.0
        l = max(1, msg_length)
        if l >= max_length:
            return 0.0
        return 0.5 * (1.0 - ((l - 1.0) / (max_length - 1.0)))

    def _update_text_csv(self, message: str):
        max_length = int(self._get_config("max_text_length", 30))
        alpha = float(self._get_config("alpha", 0.1))
        alpha = max(0.0, min(1.0, alpha))
        if len(message) >= max_length:
            return
        w0 = self._compute_w0(len(message), max_length)
        with _FileLock(self.msg_lock):
            rows: List[List[str]] = []
            if self.reply_msg_csv.exists():
                with self.reply_msg_csv.open("r", newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.reader(f))
            if not rows:
                rows = [["消息内容", "权重值", "出现次数"]]

            found = False
            for i in range(1, len(rows)):
                row = rows[i]
                if len(row) < 3:
                    continue
                if row[0] != message:
                    continue
                found = True
                old_count = int(row[2]) if row[2].isdigit() else 1
                new_count = old_count + 1
                new_weight = w0 + (1.0 - w0) * (1.0 - math.exp(-alpha * (new_count - 1)))
                rows[i] = [message, f"{new_weight:.5f}", str(new_count)]
                break

            if not found:
                rows.append([message, f"{w0:.5f}", "1"])
            self._atomic_write_csv(self.reply_msg_csv, rows)

    def _update_photo_csv(self, image_name: str):
        with _FileLock(self.photo_lock):
            rows: List[List[str]] = []
            if self.reply_photo_csv.exists():
                with self.reply_photo_csv.open("r", newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.reader(f))
            if not rows:
                rows = [["图片名称", "出现次数", "失效标记"]]

            found = False
            for i in range(1, len(rows)):
                row = rows[i]
                if len(row) < 3:
                    continue
                if row[0] != image_name:
                    continue
                found = True
                old_count = int(row[1]) if row[1].isdigit() else 1
                rows[i] = [image_name, str(old_count + 1), row[2] if row[2] in ("0", "1") else "0"]
                break

            if not found:
                rows.append([image_name, "1", "0"])
            self._atomic_write_csv(self.reply_photo_csv, rows)

    def _set_photo_invalid(self, image_name: str, invalid: bool = True):
        with _FileLock(self.photo_lock):
            rows: List[List[str]] = []
            if self.reply_photo_csv.exists():
                with self.reply_photo_csv.open("r", newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.reader(f))
            if not rows:
                rows = [["图片名称", "出现次数", "失效标记"]]

            for i in range(1, len(rows)):
                row = rows[i]
                if len(row) < 3:
                    continue
                if row[0] == image_name:
                    rows[i][2] = "1" if invalid else "0"
                    break
            self._atomic_write_csv(self.reply_photo_csv, rows)

    def _append_raw_message(
        self,
        platform: str,
        date_str: str,
        group_id: str,
        sender_id: str,
        message_type: str,
        message_content: str,
        timestamp: str,
    ):
        group_file = self.original_dir / platform / date_str / f"{group_id}_messages.json"
        lock_file = self.raw_json_lock_dir / f"{platform}_{date_str}_{group_id}.lock"
        with _FileLock(lock_file):
            records = []
            if group_file.exists():
                try:
                    with group_file.open("r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, list):
                            records = loaded
                except Exception:
                    records = []

            records.append(
                {
                    "sender_id": sender_id,
                    "message_type": message_type,
                    "message_content": message_content,
                    "timestamp": timestamp,
                }
            )
            self._atomic_write_json(group_file, records)

    def _load_text_pool(self) -> Tuple[List[str], List[float]]:
        texts: List[str] = []
        weights: List[float] = []
        with _FileLock(self.msg_lock):
            if not self.reply_msg_csv.exists():
                return texts, weights
            with self.reply_msg_csv.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        for row in rows[1:]:
            if len(row) < 3:
                continue
            msg = row[0].strip()
            if not msg:
                continue
            try:
                w = float(row[1])
            except Exception:
                w = 0.0
            texts.append(msg)
            weights.append(max(0.0, min(1.0, w)))
        return texts, weights

    def _load_photo_pool(self) -> List[str]:
        photos: List[str] = []
        with _FileLock(self.photo_lock):
            if not self.reply_photo_csv.exists():
                return photos
            with self.reply_photo_csv.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        for row in rows[1:]:
            if len(row) < 3:
                continue
            image_name = row[0].strip()
            invalid = row[2].strip() == "1"
            if image_name and not invalid:
                photos.append(image_name)
        return photos

    def _validate_photo_name(self, image_name: str) -> Optional[re.Match]:
        m = self.PHOTO_NAME_RE.match(image_name)
        if not m:
            return None
        date_str = m.group("date")
        if len(date_str) != 8 or not date_str.isdigit():
            return None
        return m

    def _remote_mode(self) -> str:
        return str(self._get_config("remote_mode", "none")).strip().lower()

    def _download_remote_media(self, image_name: str, platform: str, date_str: str) -> Optional[Path]:
        self.cache_media_dir.mkdir(parents=True, exist_ok=True)
        cache_path = self.cache_media_dir / image_name
        mode = self._remote_mode()
        rel = Path("original_data") / platform / date_str / image_name

        try:
            if mode == "local_copy":
                remote_local_dir = str(self._get_config("remote_local_dir", "")).strip()
                if not remote_local_dir:
                    return None
                source = Path(remote_local_dir) / rel
                if not source.exists():
                    return None
                shutil.copyfile(source, cache_path)
            elif mode == "webdav_http":
                remote_base_url = str(self._get_config("remote_base_url", "")).strip().rstrip("/")
                if not remote_base_url:
                    return None
                quoted_rel = "/".join(urllib.parse.quote(part) for part in rel.parts)
                remote_url = f"{remote_base_url}/{quoted_rel}"
                request = urllib.request.Request(remote_url, method="GET")
                with urllib.request.urlopen(request, timeout=float(self._get_config("remote_timeout", 10))) as resp:
                    data = resp.read()
                with cache_path.open("wb") as f:
                    f.write(data)
            else:
                return None
        except Exception as ex:
            logger.error(
                "[randomreply_plugin] 远端拉取失败: image=%s mode=%s err=%s",
                image_name,
                mode,
                ex,
            )
            return None

        if cache_path.exists() and cache_path.stat().st_size > 0:
            return cache_path
        return None

    def resolve_photo_path(self, image_name: str) -> Tuple[Optional[str], Optional[str]]:
        m = self._validate_photo_name(image_name)
        if not m:
            logger.warning("[randomreply_plugin] 图片名格式非法，判定不可用: %s", image_name)
            return None, None

        platform = m.group("platform")
        date_str = m.group("date")
        local_path = self.original_dir / platform / date_str / image_name
        if local_path.exists() and local_path.stat().st_size > 0:
            return str(local_path), "local"

        cache_path = self._download_remote_media(image_name, platform, date_str)
        if cache_path and cache_path.exists() and cache_path.stat().st_size > 0:
            return str(cache_path), "remote_cache"

        logger.warning(
            "[randomreply_plugin] 图片不可用: image=%s platform=%s date=%s",
            image_name,
            platform,
            date_str,
        )
        return None, None

    def _record_photo_failure(self, image_name: str):
        streak = self._photo_fail_streak.get(image_name, 0) + 1
        self._photo_fail_streak[image_name] = streak
        threshold = int(self._get_config("photo_fail_threshold", 3))
        if streak >= threshold:
            self._set_photo_invalid(image_name, True)
            logger.warning(
                "[randomreply_plugin] 图片连续失败达到阈值，已标记失效: image=%s streak=%s",
                image_name,
                streak,
            )

    def _record_photo_success(self, image_name: str):
        self._photo_fail_streak[image_name] = 0

    def _pick_random_reply(self) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        reply_chance = max(1, int(self._get_config("reply_chance", 100)))
        if random.randint(1, reply_chance) != 1:
            return None, None, None

        text_pool, text_weights = self._load_text_pool()
        photo_pool = self._load_photo_pool()

        has_text = len(text_pool) > 0
        has_photo = len(photo_pool) > 0
        if not has_text and not has_photo:
            return None, None, None

        text_ratio = float(self._get_config("text_reply_ratio", 0.6))
        text_ratio = max(0.0, min(1.0, text_ratio))
        weighted_ratio = float(self._get_config("weighted_text_ratio", 0.25))
        weighted_ratio = max(0.0, min(1.0, weighted_ratio))

        choose_text = has_text and (not has_photo or random.random() < text_ratio)
        if choose_text:
            if random.random() < weighted_ratio and any(w > 0 for w in text_weights):
                return random.choices(text_pool, weights=text_weights, k=1)[0], "text", None
            return random.choice(text_pool), "text", None

        if has_photo:
            image_name = random.choice(photo_pool)
            photo_path, source = self.resolve_photo_path(image_name)
            if photo_path:
                self._record_photo_success(image_name)
                return photo_path, "photo", source
            self._record_photo_failure(image_name)
            return None, None, None

        return None, None, None

    def _text_should_store(self, text: str, has_image: bool) -> bool:
        if not text:
            return False
        if has_image:
            return False
        if self.LINK_RE.search(text):
            return False
        max_length = int(self._get_config("max_text_length", 30))
        return len(text) < max_length

    def _transfer_file_to_remote(self, source: Path, rel_path: Path) -> bool:
        mode = self._remote_mode()
        try:
            if mode == "local_copy":
                remote_local_dir = str(self._get_config("remote_local_dir", "")).strip()
                if not remote_local_dir:
                    return False
                target = Path(remote_local_dir) / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                return True
            if mode == "webdav_http":
                remote_base_url = str(self._get_config("remote_base_url", "")).strip().rstrip("/")
                if not remote_base_url:
                    return False
                quoted_rel = "/".join(urllib.parse.quote(part) for part in rel_path.parts)
                remote_url = f"{remote_base_url}/{quoted_rel}"
                with source.open("rb") as f:
                    data = f.read()
                request = urllib.request.Request(remote_url, data=data, method="PUT")
                with urllib.request.urlopen(request, timeout=float(self._get_config("remote_timeout", 10))):
                    pass
                return True
        except Exception as ex:
            logger.error(
                "[randomreply_plugin] 推送远端失败: file=%s mode=%s err=%s",
                source,
                mode,
                ex,
            )
        return False

    def _run_push_and_cleanup(self):
        mode = self._remote_mode()
        if mode == "none":
            return

        today = dt.datetime.now().strftime("%Y%m%d")
        if not self.original_dir.exists():
            return

        for platform_dir in self.original_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            for date_dir in platform_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                if date_dir.name >= today:
                    continue

                all_ok = True
                for root, _, files in os.walk(date_dir):
                    for name in files:
                        src = Path(root) / name
                        rel = src.relative_to(self.data_dir)
                        ok = self._transfer_file_to_remote(src, rel)
                        if not ok:
                            all_ok = False
                if all_ok:
                    shutil.rmtree(date_dir, ignore_errors=True)
                    logger.info("[randomreply_plugin] 已推送并清理本地目录: %s", date_dir)
                else:
                    logger.warning("[randomreply_plugin] 目录推送未完全成功，暂不清理: %s", date_dir)

    def _collect_date_dirs(self) -> List[Path]:
        date_dirs: List[Path] = []
        if not self.original_dir.exists():
            return date_dirs
        for platform_dir in self.original_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            for date_dir in platform_dir.iterdir():
                if date_dir.is_dir() and date_dir.name.isdigit() and len(date_dir.name) == 8:
                    date_dirs.append(date_dir)
        date_dirs.sort(key=lambda p: p.name)
        return date_dirs

    def _dir_size_bytes(self, target: Path) -> int:
        total = 0
        for root, _, files in os.walk(target):
            for name in files:
                fp = Path(root) / name
                try:
                    total += fp.stat().st_size
                except Exception:
                    continue
        return total

    def _apply_local_keep_days(self):
        keep_days = int(self._get_config("local_keep_days", 0))
        if keep_days <= 0:
            return
        cutoff_date = dt.datetime.now().date() - dt.timedelta(days=keep_days)
        for date_dir in self._collect_date_dirs():
            try:
                date_value = dt.datetime.strptime(date_dir.name, "%Y%m%d").date()
            except ValueError:
                continue
            if date_value <= cutoff_date:
                shutil.rmtree(date_dir, ignore_errors=True)
                logger.info("[randomreply_plugin] 本地模式按天数清理目录: %s", date_dir)

    def _apply_local_size_limit(self):
        limit_mb = float(self._get_config("local_max_storage_mb", 0))
        limit_bytes = int(max(0.0, limit_mb) * 1024 * 1024)
        if limit_bytes <= 0:
            return

        date_dirs = self._collect_date_dirs()
        total = sum(self._dir_size_bytes(p) for p in date_dirs)
        if total <= limit_bytes:
            return

        for date_dir in date_dirs:
            if total <= limit_bytes:
                break
            removed_size = self._dir_size_bytes(date_dir)
            shutil.rmtree(date_dir, ignore_errors=True)
            total -= removed_size
            logger.info(
                "[randomreply_plugin] 本地模式按容量清理目录: dir=%s removed=%s remain=%s limit=%s",
                date_dir,
                removed_size,
                total,
                limit_bytes,
            )

    def _run_local_retention(self):
        # 本地模式不执行远端备份，仅执行本地保留策略。
        self._apply_local_keep_days()
        self._apply_local_size_limit()

    def _cleanup_cache_media(self):
        self.cache_media_dir.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now().timestamp()
        ttl_hours = float(self._get_config("cache_ttl_hours", 24))
        ttl_seconds = max(1.0, ttl_hours) * 3600.0
        for p in self.cache_media_dir.iterdir():
            if not p.is_file():
                continue
            try:
                age = now - p.stat().st_mtime
                if age > ttl_seconds:
                    p.unlink(missing_ok=True)
            except Exception as ex:
                logger.warning("[randomreply_plugin] 清理缓存失败: file=%s err=%s", p, ex)

    async def _maintenance_loop(self):
        while not self._maintenance_stop.is_set():
            try:
                now = dt.datetime.now()
                today = now.strftime("%Y%m%d")
                if now.strftime("%H:%M") == "01:00" and self._last_maintenance_run.get("push") != today:
                    if self._remote_mode() == "none":
                        self._run_local_retention()
                    else:
                        self._run_push_and_cleanup()
                    self._last_maintenance_run["push"] = today
                if now.strftime("%H:%M") == "01:30" and self._last_maintenance_run.get("cache") != today:
                    self._cleanup_cache_media()
                    self._last_maintenance_run["cache"] = today
            except Exception as ex:
                logger.error("[randomreply_plugin] 定时任务异常: %s", ex)
            await asyncio.sleep(30)

    @filter.command("rrtest", alias={"rr", "randomreply"})
    async def rr_test(self, event: AstrMessageEvent):
        """手动触发随机回复。"""
        reply, reply_type, source = self._pick_random_reply()
        if reply_type == "text" and reply:
            yield event.plain_result(reply)
            return
        if reply_type == "photo" and reply:
            logger.info("[randomreply_plugin] 手动触发图片回复 source=%s path=%s", source, reply)
            yield event.image_result(reply)
            return
        yield event.plain_result("当前未命中可回复内容。")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        platform_name = (event.get_platform_name() or "").lower()
        if not self._is_supported_platform(platform_name):
            return

        message_text = (event.message_str or "").strip()
        if message_text and self._is_command_like(message_text):
            return

        sender_id = str(event.get_sender_id() or "")
        self_id = str(getattr(event.message_obj, "self_id", "") or "")
        if sender_id and self_id and sender_id == self_id:
            return

        enabled = bool(self._get_config("enable_passive_reply", True))
        if not enabled:
            return

        now = dt.datetime.now()
        date_str = now.strftime("%Y%m%d")
        time_hms = now.strftime("%H%M%S")
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
        group_id = str(getattr(event.message_obj, "group_id", "") or "private")
        group_id = re.sub(r"\s+", "", group_id) or "private"
        user_id = re.sub(r"\s+", "", sender_id) or "unknown"
        platform = re.sub(r"[^a-z0-9]+", "", platform_name) or "unknown"

        image_components = self._extract_image_components(event)
        has_image = len(image_components) > 0

        try:
            if self._text_should_store(message_text, has_image):
                self._update_text_csv(message_text)
                self._append_raw_message(
                    platform=platform,
                    date_str=date_str,
                    group_id=group_id,
                    sender_id=sender_id,
                    message_type="text",
                    message_content=message_text,
                    timestamp=timestamp,
                )

            for image_comp in image_components:
                image_name = self._save_image_component(
                    image_comp=image_comp,
                    platform=platform,
                    date_str=date_str,
                    group_id=group_id,
                    user_id=user_id,
                    time_hms=time_hms,
                )
                if not image_name:
                    continue
                self._update_photo_csv(image_name)
                self._append_raw_message(
                    platform=platform,
                    date_str=date_str,
                    group_id=group_id,
                    sender_id=sender_id,
                    message_type="image",
                    message_content=image_name,
                    timestamp=timestamp,
                )
        except Exception as ex:
            logger.error(
                "[randomreply_plugin] 入库异常(不中断主流程): platform=%s group=%s err=%s",
                platform,
                group_id,
                ex,
            )

        reply, reply_type, source = self._pick_random_reply()
        if reply_type == "text" and reply:
            logger.info(
                "[randomreply_plugin] 文本回复: platform=%s group=%s reply=%s",
                platform,
                group_id,
                reply,
            )
            yield event.plain_result(reply)
            return
        if reply_type == "photo" and reply:
            logger.info(
                "[randomreply_plugin] 图片回复: platform=%s group=%s source=%s path=%s",
                platform,
                group_id,
                source,
                reply,
            )
            yield event.image_result(reply)

    async def terminate(self):
        self._maintenance_stop.set()
        if self._maintenance_task:
            self._maintenance_task.cancel()
            try:
                await self._maintenance_task
            except asyncio.CancelledError:
                pass
        logger.info("[randomreply_plugin] 插件已卸载。")
