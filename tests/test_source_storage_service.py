from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import unittest

import httpx

from webapp.config import get_settings
from webapp.services.source_storage_service import (
    SourceStorageConfigError,
    SourceStoragePlan,
    SourceStorageService,
)


def build_settings(tmp_path: Path, **overrides):
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
        source_storage_local_cache_dir=tmp_path / "source_cache",
        **overrides,
    )


class SourceStorageServiceTests(unittest.TestCase):
    def test_local_mode_keeps_existing_pdf_store_path(self):
        tmp_path = Path(self.id().replace(".", "_"))
        settings = build_settings(tmp_path, source_storage_mode="local")

        plan = SourceStorageService(settings).build_source_plan("doc-1", ".pdf")

        self.assertEqual(plan.storage_backend, "local")
        self.assertEqual(plan.local_path, tmp_path / "pdf_store" / "doc-1.pdf")
        self.assertEqual(plan.remote_path, "")
        self.assertEqual(plan.remote_url, "")

    def test_webdav_mode_builds_cache_and_configured_remote_path(self):
        tmp_path = Path(self.id().replace(".", "_"))
        settings = build_settings(
            tmp_path,
            source_storage_mode="webdav",
            webdav_endpoint="http://storage.example:5005",
            webdav_root_path="/configured/root/",
        )

        plan = SourceStorageService(settings).build_source_plan("doc-1", ".docx")

        self.assertEqual(plan.storage_backend, "webdav")
        self.assertEqual(plan.local_path, tmp_path / "source_cache" / "doc-1.docx")
        self.assertEqual(plan.remote_path, "/configured/root/doc-1.docx")
        self.assertEqual(
            plan.remote_url,
            "http://storage.example:5005/configured/root/doc-1.docx",
        )

    def test_webdav_mode_requires_configured_root_path(self):
        tmp_path = Path(self.id().replace(".", "_"))
        settings = build_settings(
            tmp_path,
            source_storage_mode="webdav",
            webdav_endpoint="http://storage.example:5005",
            webdav_root_path="",
        )

        with self.assertRaises(SourceStorageConfigError):
            SourceStorageService(settings).build_source_plan("doc-1", ".pdf")

    def test_upload_source_file_puts_local_cache_file_to_webdav_url(self):
        tmp_path = Path(self.id().replace(".", "_"))
        source_path = tmp_path / "source_cache" / "doc-1.pdf"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"%PDF-1.4\n")
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["body"] = request.content
            return httpx.Response(201)

        client = httpx.Client(transport=httpx.MockTransport(handler))
        settings = build_settings(
            tmp_path,
            source_storage_mode="webdav",
            webdav_endpoint="http://storage.example:5005",
            webdav_root_path="/configured/root/",
        )
        service = SourceStorageService(settings, client=client)

        service.upload_source_file(
            SourceStoragePlan(
                local_path=source_path,
                storage_backend="webdav",
                remote_path="/configured/root/doc-1.pdf",
                remote_url="http://storage.example:5005/configured/root/doc-1.pdf",
            )
        )

        self.assertEqual(captured["method"], "PUT")
        self.assertEqual(captured["path"], "/configured/root/doc-1.pdf")
        self.assertEqual(captured["body"], b"%PDF-1.4\n")
