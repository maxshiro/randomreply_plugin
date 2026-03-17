from typing import Callable

from infra.remote_storage.base import NoopStorage, RemoteStorage
from infra.remote_storage.local_copy import LocalCopyStorage
from infra.remote_storage.webdav_http import WebDavHttpStorage


def build_remote_storage(get_config: Callable[[str, object], object]) -> RemoteStorage:
    mode = str(get_config("remote_mode", "none")).strip().lower()
    if mode == "local_copy":
        remote_local_dir = str(get_config("remote_local_dir", "")).strip()
        if not remote_local_dir:
            return NoopStorage()
        return LocalCopyStorage(remote_root=remote_local_dir)
    if mode == "webdav_http":
        base_url = str(get_config("remote_base_url", "")).strip()
        if not base_url:
            return NoopStorage()
        timeout = float(get_config("remote_timeout", 10))
        return WebDavHttpStorage(base_url=base_url, timeout=timeout)
    return NoopStorage()
