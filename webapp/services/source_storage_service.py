from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from ..config import Settings


class SourceStorageConfigError(RuntimeError):
    pass


class SourceStorageUploadError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SourceStoragePlan:
    local_path: Path
    storage_backend: str
    remote_path: str = ""
    remote_url: str = ""


class SourceStorageService:
    """Build source-file storage paths without changing document naming contracts."""

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        auth = None
        if settings.webdav_username or settings.webdav_password:
            auth = (settings.webdav_username, settings.webdav_password)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(settings.webdav_timeout_seconds),
            auth=auth,
            trust_env=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def build_source_plan(self, doc_id: str, source_ext: str) -> SourceStoragePlan:
        filename = _safe_source_filename(doc_id, source_ext)
        mode = str(self.settings.source_storage_mode or "local").strip().lower()

        if mode == "local":
            return SourceStoragePlan(
                local_path=self.settings.pdf_store_dir / filename,
                storage_backend="local",
            )

        if mode == "webdav":
            local_cache_dir = self.settings.source_storage_local_cache_dir
            if local_cache_dir is None:
                raise SourceStorageConfigError(
                    "source_storage.local_cache_path is required in webdav mode"
                )
            remote_path = _join_remote_path(self.settings.webdav_root_path, filename)
            return SourceStoragePlan(
                local_path=local_cache_dir / filename,
                storage_backend="webdav",
                remote_path=remote_path,
                remote_url=_join_remote_url(self.settings.webdav_endpoint, remote_path),
            )

        raise SourceStorageConfigError(f"Unsupported source storage mode: {mode}")

    def upload_source_file(self, plan: SourceStoragePlan) -> None:
        if plan.storage_backend != "webdav":
            return
        if not self.settings.webdav_endpoint:
            raise SourceStorageUploadError("webdav.endpoint is required in webdav mode")
        if not plan.remote_path:
            raise SourceStorageUploadError("remote_path is required in webdav mode")
        if not plan.local_path.exists() or not plan.local_path.is_file():
            raise SourceStorageUploadError(f"local source file does not exist: {plan.local_path}")

        remote_url = _join_remote_url(self.settings.webdav_endpoint, plan.remote_path)
        try:
            with plan.local_path.open("rb") as handle:
                response = self._client.put(remote_url, content=handle)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response is not None else ""
            raise SourceStorageUploadError(
                f"WebDAV upload failed status={exc.response.status_code if exc.response else 'unknown'} {detail}".strip()
            ) from exc
        except httpx.HTTPError as exc:
            raise SourceStorageUploadError(f"WebDAV upload failed: {exc}") from exc


def _safe_source_filename(doc_id: str, source_ext: str) -> str:
    normalized_doc_id = str(doc_id or "").strip()
    normalized_ext = str(source_ext or "").strip().lower()
    if not normalized_doc_id:
        raise SourceStorageConfigError("doc_id is required")
    if "/" in normalized_doc_id or "\\" in normalized_doc_id:
        raise SourceStorageConfigError("doc_id must not contain path separators")
    if any(part in {"", ".", ".."} for part in PurePosixPath(normalized_doc_id).parts):
        raise SourceStorageConfigError("doc_id must be a safe filename component")
    if not normalized_ext.startswith("."):
        normalized_ext = f".{normalized_ext}"
    if "/" in normalized_ext or "\\" in normalized_ext or normalized_ext in {"", "."}:
        raise SourceStorageConfigError("source_ext must be a safe extension")
    return f"{normalized_doc_id}{normalized_ext}"


def _join_remote_path(root_path: str, filename: str) -> str:
    normalized_root = _normalize_remote_root(root_path)
    return str(PurePosixPath(normalized_root) / filename).replace("//", "/")


def _normalize_remote_root(root_path: str) -> str:
    text = str(root_path or "").strip().replace("\\", "/")
    if not text:
        raise SourceStorageConfigError("webdav.root_path is required in webdav mode")

    parts: list[str] = []
    for part in text.split("/"):
        if not part or part == ".":
            continue
        if part == "..":
            raise SourceStorageConfigError("webdav.root_path must not contain '..'")
        parts.append(part)
    return "/" + "/".join(parts) if parts else "/"


def _join_remote_url(endpoint: str, remote_path: str) -> str:
    normalized_endpoint = str(endpoint or "").strip().rstrip("/")
    if not normalized_endpoint:
        return ""
    return f"{normalized_endpoint}{quote(remote_path, safe='/')}"
