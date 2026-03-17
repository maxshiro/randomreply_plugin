import csv
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from ...domain.weight_calculator import compute_updated_weight, compute_w0
from ..file_lock.lock import FileLock


HEADER = ["消息内容", "权重值", "出现次数"]


class TextRepo:
    def __init__(self, data_dir: Path, get_config: Callable[[str, object], object]):
        self.data_dir = data_dir
        self.get_config = get_config
        self.global_csv = data_dir / "reply_msg_data.csv"
        self.global_lock = data_dir / ".reply_msg_data.lock"

    def _safe_group_id(self, group_id: str) -> str:
        raw = (group_id or "private").strip() or "private"
        out = []
        for ch in raw:
            if ch.isalnum() or ch in ("_", "-"):
                out.append(ch)
            else:
                out.append("_")
        return "".join(out)

    def is_group_isolated(self) -> bool:
        return bool(self.get_config("group_isolated_text_db", False))

    def get_csv_path(self, group_id: str) -> Path:
        if self.is_group_isolated():
            return self.data_dir / f"reply_msg_data_{self._safe_group_id(group_id)}.csv"
        return self.global_csv

    def get_lock_path(self, csv_path: Path) -> Path:
        return self.data_dir / f".{csv_path.stem}.lock"

    def _atomic_write_csv(self, target: Path, rows: List[List[str]]):
        import os
        import tempfile

        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            os.replace(tmp_name, target)
        finally:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink(missing_ok=True)

    def ensure_csv(self, group_id: str):
        csv_path = self.get_csv_path(group_id)
        if not csv_path.exists():
            self._atomic_write_csv(csv_path, [HEADER])

    def load_pool(self, group_id: str) -> Tuple[List[str], List[float]]:
        csv_path = self.get_csv_path(group_id)
        lock = self.get_lock_path(csv_path)
        if not csv_path.exists():
            return [], []
        with FileLock(lock):
            with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        texts: List[str] = []
        weights: List[float] = []
        for row in rows[1:]:
            if len(row) < 3:
                continue
            msg = row[0].strip()
            if not msg:
                continue
            try:
                weight = float(row[1])
            except Exception:
                weight = 0.0
            texts.append(msg)
            weights.append(max(0.0, min(1.0, weight)))
        return texts, weights

    def update_text(self, message: str, group_id: str):
        max_length = int(self.get_config("max_text_length", 30))
        alpha = float(self.get_config("alpha", 0.1))
        alpha = max(0.0, min(1.0, alpha))
        if len(message) >= max_length:
            return

        self.ensure_csv(group_id)
        csv_path = self.get_csv_path(group_id)
        lock = self.get_lock_path(csv_path)
        w0 = compute_w0(len(message), max_length)

        with FileLock(lock):
            with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
            if not rows:
                rows = [HEADER]

            found = False
            for i in range(1, len(rows)):
                row = rows[i]
                if len(row) < 3:
                    continue
                if row[0] != message:
                    continue
                found = True
                old_count = int(row[2]) if str(row[2]).isdigit() else 1
                new_count = old_count + 1
                new_weight = compute_updated_weight(w0=w0, alpha=alpha, count=new_count)
                rows[i] = [message, f"{new_weight:.5f}", str(new_count)]
                break

            if not found:
                rows.append([message, f"{w0:.5f}", "1"])
            self._atomic_write_csv(csv_path, rows)

    def list_text_csv_paths(self) -> List[Path]:
        paths = [self.global_csv]
        paths.extend(sorted(self.data_dir.glob("reply_msg_data_*.csv")))
        seen = set()
        uniq = []
        for p in paths:
            if p in seen:
                continue
            seen.add(p)
            uniq.append(p)
        return uniq

    def cleanup_low_weight(self, threshold: float):
        threshold = max(0.0, min(1.0, float(threshold)))
        for csv_path in self.list_text_csv_paths():
            if not csv_path.exists():
                continue
            lock = self.get_lock_path(csv_path)
            with FileLock(lock):
                with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                    rows = list(csv.reader(f))
                if not rows:
                    rows = [HEADER]
                out = [rows[0]]
                for row in rows[1:]:
                    if len(row) < 3:
                        continue
                    try:
                        w = float(row[1])
                    except Exception:
                        w = 0.0
                    if w >= threshold:
                        out.append(row)
                self._atomic_write_csv(csv_path, out)

    def merge_global_to_group(self, group_ids: List[str], delete_global: bool):
        if not self.global_csv.exists():
            return

        with FileLock(self.global_lock):
            with self.global_csv.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        if len(rows) <= 1:
            return

        base_map: Dict[str, Tuple[float, int]] = {}
        for row in rows[1:]:
            if len(row) < 3:
                continue
            msg = row[0].strip()
            if not msg:
                continue
            try:
                weight = float(row[1])
            except Exception:
                weight = 0.0
            count = int(row[2]) if str(row[2]).isdigit() else 1
            if msg in base_map:
                old_w, old_c = base_map[msg]
                base_map[msg] = (max(old_w, weight), old_c + count)
            else:
                base_map[msg] = (weight, count)

        for gid in group_ids:
            csv_path = self.data_dir / f"reply_msg_data_{self._safe_group_id(gid)}.csv"
            lock = self.get_lock_path(csv_path)
            with FileLock(lock):
                if csv_path.exists():
                    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                        old_rows = list(csv.reader(f))
                else:
                    old_rows = [HEADER]

                merged = dict(base_map)
                for row in old_rows[1:]:
                    if len(row) < 3:
                        continue
                    msg = row[0].strip()
                    if not msg:
                        continue
                    try:
                        weight = float(row[1])
                    except Exception:
                        weight = 0.0
                    count = int(row[2]) if str(row[2]).isdigit() else 1
                    if msg in merged:
                        old_w, old_c = merged[msg]
                        merged[msg] = (max(old_w, weight), old_c + count)
                    else:
                        merged[msg] = (weight, count)

                out = [HEADER]
                for msg, (weight, count) in merged.items():
                    out.append([msg, f"{max(0.0, min(1.0, weight)):.5f}", str(max(1, count))])
                self._atomic_write_csv(csv_path, out)

        if delete_global:
            self.global_csv.unlink(missing_ok=True)
