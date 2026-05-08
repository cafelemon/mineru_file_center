from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from webapp import db
from webapp.main import (
    app,
    build_folder_tree,
    normalize_folder_path,
)
from webapp import main as main_module


class StubRunner:
    def __init__(self):
        self.doc_ids: list[str] = []

    def submit(self, doc_id: str):
        self.doc_ids.append(doc_id)
        return None

    def shutdown(self) -> None:
        return None


def build_settings(tmp_path: Path):
    base = main_module.settings
    return replace(
        base,
        data_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        pdf_store_dir=tmp_path / "pdf_store",
        output_dir=tmp_path / "output",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
        database_path=tmp_path / "app.db",
        bridge_pdf_root=None,
        bridge_manifest_dir=None,
    )


class ZipUploadAndFolderTests(unittest.TestCase):
    def test_list_library_files_filters_by_folder_prefix(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)

        for doc_id, folder_path in (
            ("doc-root", ""),
            ("doc-hr", "制度库/人事"),
            ("doc-sub", "制度库/人事/入职"),
        ):
            db.insert_task(
                settings,
                {
                    "doc_id": doc_id,
                    "knowledge_base_code": "general",
                    "folder_path": folder_path,
                    "relative_source_path": f"{folder_path + '/' if folder_path else ''}{doc_id}.pdf",
                    "source_archive_name": "batch.zip" if folder_path else "",
                    "original_filename": f"{doc_id}.pdf",
                    "stored_pdf_path": str(settings.pdf_store_dir / f"{doc_id}.pdf"),
                    "stored_pdf_filename": f"{doc_id}.pdf",
                    "final_md_path": str(settings.output_dir / f"{doc_id}.md"),
                    "final_md_filename": f"{doc_id}.md",
                    "upload_time": "2026-01-01T00:00:00+00:00",
                    "started_at": None,
                    "completed_at": None,
                    "processed_time": None,
                    "process_status": "queued",
                    "error_message": "",
                    "mineru_task_dir": str(settings.tasks_dir / doc_id),
                    "log_path": str(settings.tasks_dir / doc_id / "task.log"),
                    "file_sha256": "",
                    "notes": "",
                    "file_size_bytes": 128,
                    "mineru_backend": settings.mineru_backend,
                    "mineru_method": settings.mineru_method,
                    "fastgpt_sync_status": "pending",
                    "fastgpt_sync_error": "",
                },
            )

        filtered = db.list_library_files(
            settings,
            knowledge_base_code="general",
            folder_path="制度库/人事",
        )

        self.assertEqual({item["doc_id"] for item in filtered}, {"doc-hr", "doc-sub"})

    def test_build_folder_tree_marks_selected_node(self):
        records = [
            {"folder_path": ""},
            {"folder_path": "制度库/人事"},
            {"folder_path": "制度库/人事/入职"},
            {"folder_path": "制度库/质量"},
        ]
        tree = build_folder_tree(
            records,
            knowledge_base_code="general",
            selected_folder_path="制度库/人事",
            selected_process_status="success",
        )

        self.assertEqual(tree[0]["name"], "制度库")
        hr_node = tree[0]["children"][0]
        self.assertEqual(hr_node["path"], "制度库/人事")
        self.assertTrue(hr_node["is_active"])
        self.assertIn("folder_path=%E5%88%B6%E5%BA%A6%E5%BA%93%2F%E4%BA%BA%E4%BA%8B", hr_node["href"])

    def test_upload_zip_creates_tasks_with_folder_metadata(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        runner = StubRunner()

        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("制度库/人事/员工手册.pdf", b"%PDF-1.4\n%test 1")
            archive.writestr("制度库/质量/培训材料.pdf", b"%PDF-1.4\n%test 2")
            archive.writestr("制度库/说明.txt", "skip me")
        archive_buffer.seek(0)

        with patch.object(main_module, "settings", settings):
            with TestClient(app) as client:
                app.state.task_runner = runner
                response = client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

                response = client.post(
                    "/upload",
                    data={"knowledge_base_code": "general"},
                    files=[
                        (
                            "files",
                            ("batch.zip", archive_buffer.getvalue(), "application/zip"),
                        )
                    ],
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("knowledge_base_code=general", response.headers["location"])
        self.assertEqual(len(runner.doc_ids), 2)

        records = db.list_library_files(settings, knowledge_base_code="general", limit=10)
        normalized_paths = {
            normalize_folder_path(item["folder_path"]): item for item in records
        }
        self.assertIn("制度库/人事", normalized_paths)
        self.assertIn("制度库/质量", normalized_paths)
        self.assertEqual(
            normalized_paths["制度库/人事"]["relative_source_path"],
            "制度库/人事/员工手册.pdf",
        )
        self.assertEqual(
            normalized_paths["制度库/人事"]["source_archive_name"],
            "batch.zip",
        )

    def test_files_page_renders_folder_tree_and_path_columns(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)

        with patch.object(main_module, "settings", settings):
            with TestClient(app) as client:
                db.insert_task(
                    settings,
                    {
                        "doc_id": "doc-1",
                        "knowledge_base_code": "general",
                        "folder_path": "制度库/人事",
                        "relative_source_path": "制度库/人事/员工手册.pdf",
                        "source_archive_name": "batch.zip",
                        "original_filename": "员工手册.pdf",
                        "stored_pdf_path": str(settings.pdf_store_dir / "doc-1.pdf"),
                        "stored_pdf_filename": "doc-1.pdf",
                        "final_md_path": str(settings.output_dir / "doc-1.md"),
                        "final_md_filename": "doc-1.md",
                        "upload_time": "2026-01-01T00:00:00+00:00",
                        "started_at": None,
                        "completed_at": None,
                        "processed_time": None,
                        "process_status": "queued",
                        "error_message": "",
                        "mineru_task_dir": str(settings.tasks_dir / "doc-1"),
                        "log_path": str(settings.tasks_dir / "doc-1" / "task.log"),
                        "file_sha256": "",
                        "notes": "",
                        "file_size_bytes": 128,
                        "mineru_backend": settings.mineru_backend,
                        "mineru_method": settings.mineru_method,
                        "fastgpt_sync_status": "pending",
                        "fastgpt_sync_error": "",
                    },
                )
                response = client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

                response = client.get(
                    "/files",
                    params={"knowledge_base_code": "general", "folder_path": "制度库/人事"},
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn("目录树", response.text)
        self.assertIn("制度库/人事/员工手册.pdf", response.text)
        self.assertIn("batch.zip", response.text)
