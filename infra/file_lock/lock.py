import os
from pathlib import Path


class FileLock:
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
