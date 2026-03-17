import shutil
from pathlib import Path

from infra.remote_storage.base import RemoteStorage


class LocalCopyStorage(RemoteStorage):
    def __init__(self, remote_root: str):
        self.remote_root = Path(remote_root)

    def fetch(self, relative_path: Path, target_path: Path) -> bool:
        source = self.remote_root / relative_path
        if not source.exists():
            return False
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target_path)
        return target_path.exists() and target_path.stat().st_size > 0

    def push(self, local_path: Path, relative_path: Path) -> bool:
        target = self.remote_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(local_path, target)
        return target.exists() and target.stat().st_size > 0
