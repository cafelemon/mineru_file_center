from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from webapp import db
from webapp import main as main_module
from webapp.main import app
from webapp.services.bridge_registry_service import BridgeRegistrySyncError
from webapp.services.fastgpt_sync_service import FastGPTSyncError


class FakeFastGPTService:
    error: Exception | None = None
    deleted_ids: list[str] = []

    def __init__(self, settings):
        self.settings = settings

    def delete_collection(self, collection_id: str) -> None:
        self.__class__.deleted_ids.append(collection_id)
        if self.__class__.error is not None:
            raise self.__class__.error

    def close(self) -> None:
        return None


class FakeBridgeService:
    enabled: bool = True
    error: Exception | None = None
    calls: list[tuple[str, str | None]] = []

    def __init__(self, settings):
        self.settings = settings

    def is_enabled(self) -> bool:
        return self.__class__.enabled

    def delete_mapping(self, *, doc_id: str, collection_id: str | None = None) -> dict:
        self.__class__.calls.append((doc_id, collection_id))
        if self.__class__.error is not None:
            raise self.__class__.error
        return {"deleted": True}

    def close(self) -> None:
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
        bridge_api_base_url="http://bridge.local",
        bridge_pdf_root=None,
        bridge_manifest_dir=None,
    )


def create_task_record(
    settings,
    *,
    doc_id: str,
    process_status: str = "success",
    collection_id: str = "col-1",
    knowledge_base_code: str = "general",
    folder_path: str = "制度库/人事",
    relative_source_path: str = "制度库/人事/员工手册.pdf",
    original_filename: str = "员工手册.pdf",
    fastgpt_sync_status: str | None = None,
) -> dict:
    task_dir = settings.tasks_dir / doc_id
    task_dir.mkdir(parents=True, exist_ok=True)
    stored_pdf_path = settings.pdf_store_dir / f"{doc_id}.pdf"
    stored_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    stored_pdf_path.write_bytes(b"%PDF-1.4\n")
    final_md_path = settings.output_dir / f"{doc_id}.md"
    final_md_path.parent.mkdir(parents=True, exist_ok=True)
    final_md_path.write_text("# hello", encoding="utf-8")
    log_path = task_dir / "task.log"
    log_path.write_text("ok", encoding="utf-8")

    payload = {
        "doc_id": doc_id,
        "knowledge_base_code": knowledge_base_code,
        "folder_path": folder_path,
        "relative_source_path": relative_source_path,
        "source_archive_name": "batch.zip",
        "original_filename": original_filename,
        "stored_pdf_path": str(stored_pdf_path),
        "stored_pdf_filename": stored_pdf_path.name,
        "final_md_path": str(final_md_path),
        "final_md_filename": final_md_path.name,
        "upload_time": "2026-01-01T00:00:00+00:00",
        "started_at": None,
        "completed_at": "2026-01-01T00:10:00+00:00",
        "processed_time": "2026-01-01T00:10:00+00:00",
        "process_status": process_status,
        "error_message": "",
        "mineru_task_dir": str(task_dir),
        "log_path": str(log_path),
        "file_sha256": "abc123",
        "notes": "",
        "file_size_bytes": 128,
        "mineru_backend": settings.mineru_backend,
        "mineru_method": settings.mineru_method,
        "fastgpt_sync_status": fastgpt_sync_status
        or ("synced" if collection_id else "pending"),
        "fastgpt_sync_error": "",
        "fastgpt_collection_id": collection_id,
    }
    db.insert_task(settings, payload)
    return payload


class DocumentDeleteRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeFastGPTService.error = None
        FakeFastGPTService.deleted_ids = []
        FakeBridgeService.error = None
        FakeBridgeService.enabled = True
        FakeBridgeService.calls = []

    def test_delete_document_success_removes_local_files_and_db_record(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        task = create_task_record(settings, doc_id="doc-1")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                response = client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

                response = client.post(
                    "/files/doc-1/delete",
                    data={"password": settings.password},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("message=", response.headers["location"])
        self.assertIsNone(db.get_task(settings, "doc-1"))
        self.assertFalse(Path(task["stored_pdf_path"]).exists())
        self.assertFalse(Path(task["final_md_path"]).exists())
        self.assertFalse(Path(task["log_path"]).exists())
        self.assertFalse(Path(task["mineru_task_dir"]).exists())
        self.assertEqual(FakeFastGPTService.deleted_ids, ["col-1"])
        self.assertEqual(FakeBridgeService.calls, [("doc-1", "col-1")])

    def test_delete_document_preserves_list_context(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-context")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/doc-context/delete",
                    data={
                        "password": settings.password,
                        "knowledge_base_code": "general",
                        "folder_path": "制度库/人事",
                        "process_status": "success",
                        "q": "员工",
                        "sort_by": "name",
                        "sort_dir": "asc",
                        "page_size": "100",
                        "page": "3",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertIn("knowledge_base_code=general", location)
        self.assertIn("folder_path=%E5%88%B6%E5%BA%A6%E5%BA%93%2F%E4%BA%BA%E4%BA%8B", location)
        self.assertIn("process_status=success", location)
        self.assertIn("q=%E5%91%98%E5%B7%A5", location)
        self.assertIn("sort_by=name", location)
        self.assertIn("sort_dir=asc", location)
        self.assertIn("page_size=100", location)
        self.assertIn("page=3", location)

    def test_delete_document_rejects_wrong_password(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-2")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/doc-2/delete",
                    data={"password": "wrong"},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-2"))
        self.assertEqual(FakeFastGPTService.deleted_ids, [])
        self.assertEqual(FakeBridgeService.calls, [])

    def test_delete_document_rejects_processing_status(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-3", process_status="processing")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/doc-3/delete",
                    data={"password": settings.password},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-3"))

    def test_delete_document_stops_when_fastgpt_delete_fails(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        task = create_task_record(settings, doc_id="doc-4")
        FakeFastGPTService.error = FastGPTSyncError("gateway timeout")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/doc-4/delete",
                    data={"password": settings.password},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-4"))
        self.assertTrue(Path(task["stored_pdf_path"]).exists())
        self.assertEqual(FakeBridgeService.calls, [])

    def test_delete_document_treats_missing_fastgpt_collection_as_success(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-5")
        FakeFastGPTService.error = FastGPTSyncError("collection not found")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/doc-5/delete",
                    data={"password": settings.password},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("message=", response.headers["location"])
        self.assertIsNone(db.get_task(settings, "doc-5"))
        self.assertEqual(FakeBridgeService.calls, [("doc-5", "col-1")])

    def test_delete_document_stops_when_bridge_delete_fails(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        task = create_task_record(settings, doc_id="doc-6")
        FakeBridgeService.error = BridgeRegistrySyncError("bridge unavailable")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/doc-6/delete",
                    data={"password": settings.password},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-6"))
        self.assertTrue(Path(task["stored_pdf_path"]).exists())

    def test_bulk_delete_failed_documents_removes_abnormal_in_current_scope(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-failed-1", process_status="failed", collection_id="")
        create_task_record(settings, doc_id="doc-failed-2", process_status="failed", collection_id="")
        create_task_record(
            settings,
            doc_id="doc-sync-failed-in-scope",
            collection_id="col-sync-failed-in-scope",
            fastgpt_sync_status="failed",
        )
        create_task_record(settings, doc_id="doc-success", process_status="success", collection_id="")
        create_task_record(
            settings,
            doc_id="doc-other-folder",
            process_status="failed",
            collection_id="",
            folder_path="制度库/财务",
            relative_source_path="制度库/财务/报销制度.pdf",
            original_filename="报销制度.pdf",
        )

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-failed",
                    data={
                        "password": settings.password,
                        "knowledge_base_code": "general",
                        "folder_path": "制度库/人事",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("message=", response.headers["location"])
        self.assertIsNone(db.get_task(settings, "doc-failed-1"))
        self.assertIsNone(db.get_task(settings, "doc-failed-2"))
        self.assertIsNone(db.get_task(settings, "doc-sync-failed-in-scope"))
        self.assertIsNotNone(db.get_task(settings, "doc-success"))
        self.assertIsNotNone(db.get_task(settings, "doc-other-folder"))
        self.assertIn("col-sync-failed-in-scope", FakeFastGPTService.deleted_ids)

    def test_bulk_delete_failed_documents_rejects_wrong_password(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-failed-3", process_status="failed", collection_id="")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-failed",
                    data={"password": "wrong"},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-failed-3"))

    def test_bulk_delete_failed_documents_reports_when_nothing_matches(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-success-2", process_status="success", collection_id="")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-failed",
                    data={"password": settings.password},
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-success-2"))

    def test_delete_selected_documents_requires_confirm_text(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-success-confirm")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-selected",
                    data={
                        "doc_ids": ["doc-success-confirm"],
                        "password": settings.password,
                        "confirm_text": "确认删除",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-success-confirm"))
        self.assertEqual(FakeFastGPTService.deleted_ids, [])
        self.assertEqual(FakeBridgeService.calls, [])

    def test_delete_selected_documents_removes_success_and_failed_selection(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-success-1", collection_id="col-success-1")
        create_task_record(
            settings, doc_id="doc-failed-selected", process_status="failed", collection_id=""
        )
        create_task_record(settings, doc_id="doc-success-kept", collection_id="col-kept")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-selected",
                    data={
                        "doc_ids": ["doc-success-1", "doc-failed-selected"],
                        "password": settings.password,
                        "confirm_text": "确认全部删除",
                        "knowledge_base_code": "general",
                        "folder_path": "制度库/人事",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("message=", response.headers["location"])
        self.assertIsNone(db.get_task(settings, "doc-success-1"))
        self.assertIsNone(db.get_task(settings, "doc-failed-selected"))
        self.assertIsNotNone(db.get_task(settings, "doc-success-kept"))
        self.assertCountEqual(FakeFastGPTService.deleted_ids, ["col-success-1"])
        self.assertCountEqual(
            FakeBridgeService.calls,
            [("doc-success-1", "col-success-1"), ("doc-failed-selected", None)],
        )

    def test_delete_selected_documents_rejects_active_status_without_partial_delete(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-success-active-check")
        create_task_record(
            settings,
            doc_id="doc-processing-selected",
            process_status="processing",
            collection_id="",
        )

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-selected",
                    data={
                        "doc_ids": ["doc-success-active-check", "doc-processing-selected"],
                        "password": settings.password,
                        "confirm_text": "确认全部删除",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-success-active-check"))
        self.assertIsNotNone(db.get_task(settings, "doc-processing-selected"))
        self.assertEqual(FakeFastGPTService.deleted_ids, [])
        self.assertEqual(FakeBridgeService.calls, [])

    def test_delete_selected_documents_reports_when_nothing_selected(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-selection-required")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module, "FastGPTSyncService", FakeFastGPTService
        ), patch.object(main_module, "BridgeRegistrySyncService", FakeBridgeService), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.post(
                    "/files/delete-selected",
                    data={
                        "password": settings.password,
                        "confirm_text": "确认全部删除",
                    },
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])
        self.assertIsNotNone(db.get_task(settings, "doc-selection-required"))

    def test_files_page_renders_delete_toolbar_and_modals(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(settings, doc_id="doc-page-success")
        create_task_record(
            settings,
            doc_id="doc-page-sync-failed",
            collection_id="col-page-sync-failed",
            fastgpt_sync_status="failed",
        )

        with patch.object(main_module, "settings", settings), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.get("/files", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("删除选中", html)
        self.assertIn("一键删除异常文件", html)
        self.assertIn('data-delete-selected-label="删除选中"', html)
        self.assertIn('action="/files/delete-selected"', html)
        self.assertIn('data-delete-modal="selected"', html)
        self.assertIn('data-delete-modal="failed"', html)
        self.assertNotIn("批量删除成功文件", html)
        self.assertNotIn("/files/delete-successful", html)

    def test_files_page_abnormal_card_includes_sync_failed_success_records(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(
            settings,
            doc_id="doc-sync-failed",
            collection_id="col-sync-failed",
            fastgpt_sync_status="failed",
        )
        create_task_record(settings, doc_id="doc-conversion-failed", process_status="failed", collection_id="")
        create_task_record(settings, doc_id="doc-clean-success", collection_id="col-clean")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.get("/files", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.text,
            r"<span>异常文件</span>\s*<strong>2</strong>",
        )

    def test_tasks_page_uses_overall_status_for_sync_failed_records(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        create_task_record(
            settings,
            doc_id="doc-task-sync-failed",
            collection_id="col-task-sync-failed",
            fastgpt_sync_status="failed",
        )
        create_task_record(settings, doc_id="doc-task-clean", collection_id="col-task-clean")

        with patch.object(main_module, "settings", settings), patch.object(
            main_module.db, "mark_incomplete_tasks_as_interrupted", lambda _settings: None
        ):
            with TestClient(app) as client:
                client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                response = client.get("/tasks", follow_redirects=False)

        self.assertEqual(response.status_code, 200)
        self.assertIn("同步失败", response.text)
        self.assertIn('status status-failed">同步失败</span>', response.text)
        self.assertRegex(
            response.text,
            r"<span>异常文件</span>\s*<strong>1</strong>",
        )
