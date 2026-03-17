import json
from pathlib import Path
from typing import Any, Dict, List

from ..file_lock.lock import FileLock


class RawMessageRepo:
    def __init__(self, data_dir: Path):
        self.original_dir = data_dir / "original_data"
        self.lock_dir = data_dir / ".raw_locks"
        self.lock_dir.mkdir(parents=True, exist_ok=True)

    def _atomic_write_json(self, target: Path, data: Any):
        import os
        import tempfile

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_name, target)
        finally:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink(missing_ok=True)

    def append_record(self, platform: str, date_str: str, group_id: str, record: Dict[str, Any]):
        group_file = self.original_dir / platform / date_str / f"{group_id}_messages.json"
        lock_file = self.lock_dir / f"{platform}_{date_str}_{group_id}.lock"
        with FileLock(lock_file):
            rows: List[Dict[str, Any]] = []
            if group_file.exists():
                try:
                    with group_file.open("r", encoding="utf-8") as f:
                        loaded = json.load(f)
                        if isinstance(loaded, list):
                            rows = loaded
                except Exception:
                    rows = []
            rows.append(record)
            self._atomic_write_json(group_file, rows)

    def discover_groups(self) -> List[str]:
        groups: List[str] = []
        if not self.original_dir.exists():
            return groups
        for platform_dir in self.original_dir.iterdir():
            if not platform_dir.is_dir():
                continue
            for date_dir in platform_dir.iterdir():
                if not date_dir.is_dir():
                    continue
                for f in date_dir.glob("*_messages.json"):
                    name = f.name
                    if name.endswith("_messages.json"):
                        gid = name[: -len("_messages.json")]
                        if gid:
                            groups.append(gid)
        return sorted(set(groups))
