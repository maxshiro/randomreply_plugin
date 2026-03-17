from pathlib import Path
from typing import Optional


class RemoteStorage:
    def fetch(self, relative_path: Path, target_path: Path) -> bool:
        raise NotImplementedError

    def push(self, local_path: Path, relative_path: Path) -> bool:
        raise NotImplementedError


class NoopStorage(RemoteStorage):
    def fetch(self, relative_path: Path, target_path: Path) -> bool:
        return False

    def push(self, local_path: Path, relative_path: Path) -> bool:
        return False
