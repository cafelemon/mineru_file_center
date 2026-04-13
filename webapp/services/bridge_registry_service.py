from __future__ import annotations

from typing import Any

import httpx

from ..config import Settings


class BridgeRegistrySyncError(RuntimeError):
    pass


class BridgeRegistrySyncService:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.base_url = (settings.bridge_api_base_url or "").strip().rstrip("/")
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=30.0),
            trust_env=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def is_enabled(self) -> bool:
        return bool(self.base_url)

    def register_mapping(
        self,
        *,
        task: dict[str, Any],
        collection_id: str,
        app_code: str,
        exported_pdf_path: "Path | None" = None,
    ) -> dict[str, Any]:
        if not self.is_enabled():
            raise BridgeRegistrySyncError("Bridge 管理接口地址未配置")

        payload = {
            "doc_id": str(task["doc_id"]),
            "collection_id": collection_id,
            "source_name": str(task.get("final_md_filename") or ""),
            "origin_pdf_name": str(task.get("original_filename") or f"{task['doc_id']}.pdf"),
            "pdf_abs_path": str(exported_pdf_path.resolve()) if exported_pdf_path is not None else None,
            "perm_level": 1,
            "app_code": app_code,
            "status": 1,
            "sha256": str(task.get("file_sha256") or "").strip() or None,
        }
        try:
            response = self._client.post(
                f"{self.base_url}/admin/kb/register-pdf",
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response is not None else ""
            raise BridgeRegistrySyncError(
                f"Bridge PDF registry 回填失败 status={exc.response.status_code if exc.response else 'unknown'} {detail}".strip()
            ) from exc
        except httpx.HTTPError as exc:
            raise BridgeRegistrySyncError(f"Bridge PDF registry 回填失败: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise BridgeRegistrySyncError("Bridge PDF registry 返回了无效 JSON") from exc
        if not isinstance(data, dict):
            raise BridgeRegistrySyncError("Bridge PDF registry 返回格式异常")
        return data
