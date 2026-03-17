import csv
from pathlib import Path
from typing import List

from infra.file_lock.lock import FileLock


HEADER = ["图片名称", "出现次数", "失效标记"]


class PhotoRepo:
    def __init__(self, data_dir: Path):
        self.csv_path = data_dir / "reply_photo_data.csv"
        self.lock_path = data_dir / ".reply_photo_data.lock"

    def _atomic_write_csv(self, rows: List[List[str]]):
        import os
        import tempfile

        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=self.csv_path.name + ".", suffix=".tmp", dir=self.csv_path.parent)
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerows(rows)
            os.replace(tmp_name, self.csv_path)
        finally:
            if Path(tmp_name).exists():
                Path(tmp_name).unlink(missing_ok=True)

    def ensure_csv(self):
        if not self.csv_path.exists():
            self._atomic_write_csv([HEADER])

    def update_photo(self, image_name: str):
        self.ensure_csv()
        with FileLock(self.lock_path):
            with self.csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
            if not rows:
                rows = [HEADER]

            found = False
            for i in range(1, len(rows)):
                row = rows[i]
                if len(row) < 3:
                    continue
                if row[0] != image_name:
                    continue
                found = True
                old_count = int(row[1]) if str(row[1]).isdigit() else 1
                rows[i] = [image_name, str(old_count + 1), row[2] if row[2] in ("0", "1") else "0"]
                break

            if not found:
                rows.append([image_name, "1", "0"])
            self._atomic_write_csv(rows)

    def mark_invalid(self, image_name: str, invalid: bool = True):
        self.ensure_csv()
        with FileLock(self.lock_path):
            with self.csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
            if not rows:
                rows = [HEADER]
            for i in range(1, len(rows)):
                row = rows[i]
                if len(row) < 3:
                    continue
                if row[0] == image_name:
                    rows[i][2] = "1" if invalid else "0"
                    break
            self._atomic_write_csv(rows)

    def load_available(self) -> List[str]:
        if not self.csv_path.exists():
            return []
        with FileLock(self.lock_path):
            with self.csv_path.open("r", newline="", encoding="utf-8-sig") as f:
                rows = list(csv.reader(f))
        out: List[str] = []
        for row in rows[1:]:
            if len(row) < 3:
                continue
            name = row[0].strip()
            invalid = row[2].strip() == "1"
            if name and not invalid:
                out.append(name)
        return out
