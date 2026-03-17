import datetime as dt
import os
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from astrbot.api import logger

from app.feature_orchestrator import FeatureOrchestrator
from infra.remote_storage.base import NoopStorage, RemoteStorage
from infra.repo.text_repo import TextRepo


class SchedulerService:
    def __init__(
        self,
        data_dir: Path,
        original_dir: Path,
        cache_media_dir: Path,
        get_config: Callable[[str, object], object],
        text_repo: TextRepo,
        remote_storage: RemoteStorage,
        orchestrator: FeatureOrchestrator,
        send_proactive: Callable[[str, str, str], None],
        get_active_sessions: Callable[[], Dict[str, str]],
    ):
        self.data_dir = data_dir
        self.original_dir = original_dir
        self.cache_media_dir = cache_media_dir
        self.get_config = get_config
        self.text_repo = text_repo
        self.remote_storage = remote_storage
        self.orchestrator = orchestrator
        self.send_proactive = send_proactive
        self.get_active_sessions = get_active_sessions
        self.last_run: Dict[str, str] = {}
        self.last_timestamp_mark = ""

    def _remote_mode(self) -> str:
        return str(self.get_config("remote_mode", "none")).strip().lower()

    def _collect_date_dirs(self) -> List[Path]:
        out: List[Path] = []
        if not self.original_dir.exists():
            return out
        for platform_dir in self.original_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            for date_dir in platform_dir.iterdir():
                if date_dir.is_dir() and date_dir.name.isdigit() and len(date_dir.name) == 8:
                    out.append(date_dir)
        out.sort(key=lambda p: p.name)
        return out

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

    def _run_push_and_cleanup(self):
        if isinstance(self.remote_storage, NoopStorage):
            return
        today = dt.datetime.now().strftime("%Y%m%d")
        if not self.original_dir.exists():
            return

        for date_dir in self._collect_date_dirs():
            if date_dir.name >= today:
                continue
            all_ok = True
            for root, _, files in os.walk(date_dir):
                for name in files:
                    src = Path(root) / name
                    rel = src.relative_to(self.data_dir)
                    ok = self.remote_storage.push(src, rel)
                    if not ok:
                        all_ok = False
            if all_ok:
                shutil.rmtree(date_dir, ignore_errors=True)
                logger.info("[randomreply_plugin] 已推送并清理本地目录: %s", date_dir)

    def _run_push_only(self) -> Tuple[int, int]:
        if isinstance(self.remote_storage, NoopStorage):
            return 0, 0
        pushed = 0
        failed = 0
        if not self.original_dir.exists():
            return pushed, failed

        for date_dir in self._collect_date_dirs():
            for root, _, files in os.walk(date_dir):
                for name in files:
                    src = Path(root) / name
                    rel = src.relative_to(self.data_dir)
                    ok = self.remote_storage.push(src, rel)
                    if ok:
                        pushed += 1
                    else:
                        failed += 1
        return pushed, failed

    def _run_local_retention(self):
        keep_days = int(self.get_config("local_keep_days", 0))
        if keep_days > 0:
            cutoff = dt.datetime.now().date() - dt.timedelta(days=keep_days)
            for date_dir in self._collect_date_dirs():
                try:
                    d = dt.datetime.strptime(date_dir.name, "%Y%m%d").date()
                except ValueError:
                    continue
                if d <= cutoff:
                    shutil.rmtree(date_dir, ignore_errors=True)

        limit_mb = float(self.get_config("local_max_storage_mb", 0))
        limit_bytes = int(max(0.0, limit_mb) * 1024 * 1024)
        if limit_bytes > 0:
            date_dirs = self._collect_date_dirs()
            total = sum(self._dir_size_bytes(d) for d in date_dirs)
            for date_dir in date_dirs:
                if total <= limit_bytes:
                    break
                removed = self._dir_size_bytes(date_dir)
                shutil.rmtree(date_dir, ignore_errors=True)
                total -= removed

    def _cleanup_cache_media(self):
        self.cache_media_dir.mkdir(parents=True, exist_ok=True)
        now = dt.datetime.now().timestamp()
        ttl_h = float(self.get_config("cache_ttl_hours", 24))
        ttl_seconds = max(1.0, ttl_h) * 3600.0
        for p in self.cache_media_dir.iterdir():
            if not p.is_file():
                continue
            try:
                if now - p.stat().st_mtime > ttl_seconds:
                    p.unlink(missing_ok=True)
            except Exception:
                continue

    def debug_cleanup_weight(self, threshold: Optional[float] = None):
        th = float(self.get_config("weight_cleanup_threshold", 0.2)) if threshold is None else float(threshold)
        self.text_repo.cleanup_low_weight(th)

    def debug_cleanup_cache(self):
        self._cleanup_cache_media()

    def debug_backup_data(self):
        if self._remote_mode() == "none":
            self._run_local_retention()
            return "local_retention"
        self._run_push_and_cleanup()
        return "remote_backup"

    def debug_remote_backup_test(self) -> Tuple[int, int, str]:
        if isinstance(self.remote_storage, NoopStorage):
            return 0, 0, "remote_mode=none"
        pushed, failed = self._run_push_only()
        return pushed, failed, self._remote_mode()

    async def _run_timestamp(self, now: dt.datetime):
        if not bool(self.get_config("enable_timestamp_random_reply", False)):
            return
        if now.second != 0:
            return
        minute_mark = now.strftime("%Y%m%d%H%M")
        if minute_mark == self.last_timestamp_mark:
            return
        self.last_timestamp_mark = minute_mark

        if not self.orchestrator.in_timestamp_window(now):
            return
        if not self.orchestrator.timestamp_should_trigger():
            return

        sessions = self.get_active_sessions()
        for umo, group_id in list(sessions.items()):
            kind, content, _ = self.orchestrator.decide_on_timestamp(group_id)
            if kind and content:
                await self.send_proactive(umo, kind, content)

    async def tick(self):
        now = dt.datetime.now()
        today = now.strftime("%Y%m%d")

        if now.strftime("%H:%M") == "01:00" and self.last_run.get("maintenance") != today:
            self.text_repo.cleanup_low_weight(float(self.get_config("weight_cleanup_threshold", 0.2)))
            if self._remote_mode() == "none":
                self._run_local_retention()
            else:
                self._run_push_and_cleanup()
            self.last_run["maintenance"] = today

        if now.strftime("%H:%M") == "01:30" and self.last_run.get("cache") != today:
            self._cleanup_cache_media()
            self.last_run["cache"] = today

        await self._run_timestamp(now)
