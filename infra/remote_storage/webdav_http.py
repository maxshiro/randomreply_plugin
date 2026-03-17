import urllib.parse
import urllib.request
from pathlib import Path

from infra.remote_storage.base import RemoteStorage


class WebDavHttpStorage(RemoteStorage):
    def __init__(self, base_url: str, timeout: float):
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)

    def _build_url(self, relative_path: Path) -> str:
        rel = "/".join(urllib.parse.quote(part) for part in relative_path.parts)
        return f"{self.base_url}/{rel}"

    def fetch(self, relative_path: Path, target_path: Path) -> bool:
        url = self._build_url(relative_path)
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=self.timeout) as resp:
            data = resp.read()
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as f:
            f.write(data)
        return target_path.exists() and target_path.stat().st_size > 0

    def push(self, local_path: Path, relative_path: Path) -> bool:
        url = self._build_url(relative_path)
        with local_path.open("rb") as f:
            data = f.read()
        request = urllib.request.Request(url, data=data, method="PUT")
        with urllib.request.urlopen(request, timeout=self.timeout):
            pass
        return True
