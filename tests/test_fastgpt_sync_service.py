from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import unittest

import httpx

from webapp.config import get_settings
from webapp.knowledge_bases import KnowledgeBase
from webapp.services.fastgpt_sync_service import FastGPTSyncError, FastGPTSyncService


def build_settings(tmp_path: Path):
    base = get_settings()
    return replace(
        base,
        data_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        pdf_store_dir=tmp_path / "pdf_store",
        output_dir=tmp_path / "output",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
        database_path=tmp_path / "app.db",
        fastgpt_sync_enabled=True,
        fastgpt_base_url="http://fastgpt.local",
        fastgpt_api_key="fastgpt-key",
        fastgpt_training_type="chunk",
        fastgpt_chunk_setting_mode="auto",
        fastgpt_chunk_size=None,
    )


class FastGPTSyncServiceTests(unittest.TestCase):
    def test_sync_markdown_success_replaces_previous_collection(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            import shutil

            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_path, ignore_errors=True))

        markdown_path = tmp_path / "output" / "doc-1.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("# title\n\ncontent", encoding="utf-8")
        requests: list[tuple[str, dict]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            payload = {}
            if request.content:
                payload = json.loads(request.content.decode("utf-8"))
            requests.append((request.url.path, payload))
            if request.url.path == "/api/core/dataset/list":
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": [
                            {"_id": "dataset-1", "name": "通用知识库", "type": "dataset"},
                        ],
                    },
                )
            if request.url.path == "/api/core/dataset/collection/delete":
                return httpx.Response(200, json={"code": 200, "data": None})
            if request.url.path == "/api/core/dataset/collection/create/text":
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "collectionId": "collection-new",
                            "results": {"insertLen": 3, "error": []},
                        },
                    },
                )
            raise AssertionError(f"unexpected path: {request.url.path}")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = FastGPTSyncService(build_settings(tmp_path), client=client)

        result = service.sync_markdown(
            task={
                "doc_id": "doc-1",
                "knowledge_base_code": "general",
                "original_filename": "员工手册.pdf",
                "final_md_path": str(markdown_path),
                "final_md_filename": "doc-1.md",
                "fastgpt_collection_id": "collection-old",
            },
            knowledge_base=KnowledgeBase(code="general", display_name="通用知识库"),
        )

        self.assertEqual(result.dataset_id, "dataset-1")
        self.assertEqual(result.collection_id, "collection-new")
        self.assertEqual(
            [item[0] for item in requests],
            [
                "/api/core/dataset/list",
                "/api/core/dataset/collection/delete",
                "/api/core/dataset/collection/create/text",
            ],
        )
        self.assertEqual(requests[-1][1]["datasetId"], "dataset-1")
        self.assertEqual(requests[-1][1]["name"], "员工手册.pdf")
        self.assertEqual(requests[-1][1]["text"], "# title\n\ncontent")

    def test_sync_markdown_fails_when_dataset_missing(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            import shutil

            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_path, ignore_errors=True))

        markdown_path = tmp_path / "output" / "doc-2.md"
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text("content", encoding="utf-8")

        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={"code": 200, "data": []},
                )
            )
        )
        service = FastGPTSyncService(build_settings(tmp_path), client=client)

        with self.assertRaises(FastGPTSyncError) as ctx:
            service.sync_markdown(
                task={
                    "doc_id": "doc-2",
                    "knowledge_base_code": "general",
                    "original_filename": "制度.pdf",
                    "final_md_path": str(markdown_path),
                    "final_md_filename": "doc-2.md",
                },
                knowledge_base=KnowledgeBase(code="general", display_name="通用知识库"),
            )

        self.assertIn("未找到", str(ctx.exception))
