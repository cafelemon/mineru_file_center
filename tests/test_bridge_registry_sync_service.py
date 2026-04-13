from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json
import unittest

import httpx

from webapp.config import get_settings
from webapp.services.bridge_registry_service import BridgeRegistrySyncService


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
        bridge_api_base_url="http://bridge.local",
    )


class BridgeRegistrySyncServiceTests(unittest.TestCase):
    def test_register_mapping_without_exported_pdf_path(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            import shutil

            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_path, ignore_errors=True))

        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"ok": True})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        service = BridgeRegistrySyncService(build_settings(tmp_path), client=client)

        result = service.register_mapping(
            task={
                "doc_id": "doc-1",
                "final_md_filename": "doc-1.md",
                "original_filename": "员工手册.pdf",
                "file_sha256": "abc123",
            },
            collection_id="collection-1",
            app_code="general_common",
            exported_pdf_path=None,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(captured["path"], "/admin/kb/register-pdf")
        self.assertEqual(
            captured["json"],
            {
                "doc_id": "doc-1",
                "collection_id": "collection-1",
                "source_name": "doc-1.md",
                "origin_pdf_name": "员工手册.pdf",
                "pdf_abs_path": None,
                "perm_level": 1,
                "app_code": "general_common",
                "status": 1,
                "sha256": "abc123",
            },
        )

