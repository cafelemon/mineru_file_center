from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..knowledge_bases import KnowledgeBase


@dataclass(slots=True)
class FastGPTSyncResult:
    dataset_id: str
    dataset_name: str
    collection_id: str
    insert_len: int


class FastGPTSyncError(RuntimeError):
    pass


class FastGPTSyncService:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.settings = settings
        self.base_url = _normalize_fastgpt_root_url(settings.fastgpt_base_url)
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=30.0),
            trust_env=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def is_enabled(self) -> bool:
        return bool(self.settings.fastgpt_sync_enabled)

    def sync_markdown(
        self,
        *,
        task: dict[str, Any],
        knowledge_base: KnowledgeBase,
    ) -> FastGPTSyncResult:
        if not self.is_enabled():
            raise FastGPTSyncError("FastGPT 自动同步未启用")
        if not self.base_url or not self.settings.fastgpt_api_key:
            raise FastGPTSyncError("FastGPT 自动同步缺少 base_url 或 api_key 配置")

        markdown_path = self._resolve_markdown_path(task)
        markdown_text = markdown_path.read_text(encoding="utf-8").strip()
        if not markdown_text:
            raise FastGPTSyncError("Markdown 文件为空，无法同步到 FastGPT")

        dataset = self._find_dataset_by_name(knowledge_base.display_name)
        previous_collection_id = str(task.get("fastgpt_collection_id") or "").strip()
        if previous_collection_id:
            self._delete_collection(previous_collection_id)

        payload: dict[str, Any] = {
            "text": markdown_text,
            "datasetId": dataset["id"],
            "parentId": None,
            "name": self._build_collection_name(task, markdown_path),
            "trainingType": self.settings.fastgpt_training_type,
            "chunkSettingMode": self.settings.fastgpt_chunk_setting_mode,
            "metadata": {
                "doc_id": str(task["doc_id"]),
                "knowledge_base_code": str(task.get("knowledge_base_code") or ""),
                "knowledge_base_name": knowledge_base.display_name,
                "source_name": str(task.get("final_md_filename") or markdown_path.name),
                "origin_pdf_name": str(task.get("original_filename") or ""),
            },
        }
        if self.settings.fastgpt_chunk_setting_mode == "custom":
            payload["chunkSize"] = self.settings.fastgpt_chunk_size or 1500

        result = self._post_json("/api/core/dataset/collection/create/text", payload)
        data = result.get("data")
        if not isinstance(data, dict):
            raise FastGPTSyncError("FastGPT 创建文本集合返回格式异常")
        collection_id = str(data.get("collectionId") or "").strip()
        if not collection_id:
            raise FastGPTSyncError("FastGPT 未返回 collectionId")
        results = data.get("results") if isinstance(data.get("results"), dict) else {}
        insert_len = _safe_int(results.get("insertLen"))
        errors = results.get("error") if isinstance(results.get("error"), list) else []
        if insert_len <= 0 and errors:
            raise FastGPTSyncError(f"FastGPT 切片失败: {' | '.join(str(item) for item in errors)}")

        return FastGPTSyncResult(
            dataset_id=dataset["id"],
            dataset_name=dataset["name"],
            collection_id=collection_id,
            insert_len=insert_len,
        )

    def _find_dataset_by_name(self, dataset_name: str) -> dict[str, str]:
        payload = self._post_json("/api/core/dataset/list?parentId=", {"parentId": ""})
        data = payload.get("data")
        if not isinstance(data, list):
            raise FastGPTSyncError("FastGPT 知识库列表返回格式异常")

        matches: list[dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "") != "dataset":
                continue
            name = str(item.get("name") or "").strip()
            if name != dataset_name:
                continue
            dataset_id = str(item.get("_id") or item.get("id") or "").strip()
            if not dataset_id:
                continue
            matches.append({"id": dataset_id, "name": name})

        if not matches:
            raise FastGPTSyncError(f"FastGPT 中未找到名称为“{dataset_name}”的知识库")
        if len(matches) > 1:
            raise FastGPTSyncError(f"FastGPT 中存在多个名称为“{dataset_name}”的知识库")
        return matches[0]

    def _delete_collection(self, collection_id: str) -> None:
        self._post_json(
            "/api/core/dataset/collection/delete",
            {"collectionIds": [collection_id]},
        )

    def _resolve_markdown_path(self, task: dict[str, Any]) -> Path:
        final_md_path = str(task.get("final_md_path") or "").strip()
        if not final_md_path:
            raise FastGPTSyncError("任务尚未生成 Markdown 文件")
        path = Path(final_md_path).expanduser()
        if not path.exists() or not path.is_file():
            raise FastGPTSyncError("Markdown 文件不存在")
        return path

    def _build_collection_name(self, task: dict[str, Any], markdown_path: Path) -> str:
        original_filename = str(task.get("original_filename") or "").strip()
        if original_filename:
            return original_filename
        final_md_filename = str(task.get("final_md_filename") or "").strip()
        if final_md_filename:
            return final_md_filename
        return markdown_path.name

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.base_url:
            raise FastGPTSyncError("FASTGPT_BASE_URL 未配置")
        try:
            response = self._client.post(
                f"{self.base_url}{path}",
                headers={
                    "Authorization": f"Bearer {self.settings.fastgpt_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip() if exc.response is not None else ""
            raise FastGPTSyncError(
                f"FastGPT 接口调用失败 status={exc.response.status_code if exc.response else 'unknown'} {detail}".strip()
            ) from exc
        except httpx.HTTPError as exc:
            raise FastGPTSyncError(f"FastGPT 接口调用失败: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise FastGPTSyncError("FastGPT 返回了无法解析的 JSON") from exc
        if not isinstance(data, dict):
            raise FastGPTSyncError("FastGPT 返回格式异常")
        if _safe_int(data.get("code"), default=200) != 200:
            raise FastGPTSyncError(str(data.get("message") or "FastGPT 返回失败"))
        return data


def _normalize_fastgpt_root_url(base_url: str) -> str:
    text = (base_url or "").strip().rstrip("/")
    if text.endswith("/api/v1"):
        return text[: -len("/api/v1")]
    return text


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
