from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import unittest
from unittest.mock import MagicMock, patch

from webapp import db
from webapp.config import get_settings
from webapp.services.bridge_registry_service import BridgeRegistrySyncError
from webapp.services.fastgpt_sync_service import FastGPTSyncResult
from webapp.services.mineru_service import MineruTaskRunner


def build_settings(tmp_path: Path):
    base = get_settings()
    return replace(
        base,
        project_root=tmp_path,
        config_path=tmp_path / "config.toml",
        data_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        pdf_store_dir=tmp_path / "pdf_store",
        output_dir=tmp_path / "output",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
        database_path=tmp_path / "app.db",
        mineru_command=["env/bin/mineru"],
        mineru_stale_process_scan_interval_seconds=0,
    )


class _FakeFastGPTSyncService:
    def is_enabled(self) -> bool:
        return True

    def sync_markdown(self, *, task, knowledge_base):
        return FastGPTSyncResult(
            dataset_id="dataset-1",
            dataset_name=knowledge_base.display_name,
            collection_id="collection-new",
            insert_len=1,
        )

    def close(self) -> None:
        return None


class _FakeBridgeRegistrySyncService:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def is_enabled(self) -> bool:
        return True

    def register_mapping(self, *, task, collection_id, app_code, exported_pdf_path=None):
        self.calls.append((str(task["doc_id"]), collection_id))
        if self.error is not None:
            raise self.error
        return {"ok": True}

    def close(self) -> None:
        return None


class MineruServiceTests(unittest.TestCase):
    def _insert_sync_task(self, settings, doc_id: str = "doc-sync") -> dict:
        settings.ensure_directories()
        db.init_db(settings)
        final_md_path = settings.output_dir / f"{doc_id}.md"
        final_md_path.write_text("# hello", encoding="utf-8")
        stored_pdf_path = settings.pdf_store_dir / f"{doc_id}.pdf"
        stored_pdf_path.write_bytes(b"%PDF-1.4\n")
        task_dir = settings.tasks_dir / doc_id
        task_dir.mkdir(parents=True, exist_ok=True)
        log_path = settings.logs_dir / f"{doc_id}.log"
        log_path.write_text("ok", encoding="utf-8")
        payload = {
            "doc_id": doc_id,
            "knowledge_base_code": "general",
            "folder_path": "",
            "relative_source_path": "demo.pdf",
            "source_archive_name": "",
            "original_filename": "demo.pdf",
            "stored_pdf_path": str(stored_pdf_path),
            "stored_pdf_filename": stored_pdf_path.name,
            "source_file_path": str(stored_pdf_path),
            "source_file_filename": stored_pdf_path.name,
            "source_file_ext": ".pdf",
            "source_mime_type": "application/pdf",
            "processor_type": "mineru_pdf",
            "final_md_path": str(final_md_path),
            "final_md_filename": final_md_path.name,
            "upload_time": "2026-01-01T00:00:00+00:00",
            "started_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
            "processed_time": "2026-01-01T00:01:00+00:00",
            "process_status": "success",
            "error_message": "",
            "mineru_task_dir": str(task_dir),
            "log_path": str(log_path),
            "file_sha256": "abc123",
            "notes": "",
            "file_size_bytes": 128,
            "mineru_backend": settings.mineru_backend,
            "mineru_method": settings.mineru_method,
            "fastgpt_sync_status": "pending",
            "fastgpt_sync_error": "",
            "fastgpt_collection_id": "",
        }
        db.insert_task(settings, payload)
        return payload

    def test_sync_to_fastgpt_marks_synced_only_after_bridge_registry_success(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = replace(
            build_settings(tmp_path),
            fastgpt_sync_enabled=True,
            bridge_api_base_url="http://bridge.local",
        )
        task = self._insert_sync_task(settings)
        runner = MineruTaskRunner(settings)
        self.addCleanup(runner.shutdown)
        runner.fastgpt_sync_service.close()
        runner.bridge_registry_sync_service.close()
        runner.fastgpt_sync_service = _FakeFastGPTSyncService()
        runner.bridge_registry_sync_service = _FakeBridgeRegistrySyncService()

        runner._sync_to_fastgpt(task, bridge_result=None)

        saved = db.get_task(settings, task["doc_id"])
        self.assertEqual(saved["fastgpt_collection_id"], "collection-new")
        self.assertEqual(saved["fastgpt_sync_status"], "synced")
        self.assertEqual(saved["fastgpt_sync_error"], "")
        self.assertIn("Bridge registry sync ok", saved["notes"])

    def test_sync_to_fastgpt_marks_failed_when_bridge_registry_fails(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = replace(
            build_settings(tmp_path),
            fastgpt_sync_enabled=True,
            bridge_api_base_url="http://bridge.local",
        )
        task = self._insert_sync_task(settings)
        runner = MineruTaskRunner(settings)
        self.addCleanup(runner.shutdown)
        runner.fastgpt_sync_service.close()
        runner.bridge_registry_sync_service.close()
        runner.fastgpt_sync_service = _FakeFastGPTSyncService()
        runner.bridge_registry_sync_service = _FakeBridgeRegistrySyncService(
            error=BridgeRegistrySyncError("bridge unavailable")
        )

        runner._sync_to_fastgpt(task, bridge_result=None)

        saved = db.get_task(settings, task["doc_id"])
        self.assertEqual(saved["fastgpt_collection_id"], "collection-new")
        self.assertEqual(saved["fastgpt_sync_status"], "failed")
        self.assertEqual(saved["fastgpt_sync_error"], "bridge unavailable")
        self.assertIn("Bridge registry sync failed", saved["notes"])

    def test_run_mineru_process_uses_new_process_group_on_posix(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        runner = MineruTaskRunner(build_settings(tmp_path))
        fake_process = MagicMock()
        fake_process.pid = 4321
        fake_process.wait.return_value = 0

        with patch("webapp.services.mineru_service.subprocess.Popen", return_value=fake_process) as popen_mock:
            with patch.object(runner, "_cleanup_process_group") as cleanup_mock:
                with (tmp_path / "task.log").open("w", encoding="utf-8") as log_handle:
                    returncode = runner._run_mineru_process(
                        ["mineru", "-p", "demo.pdf"],
                        log_handle=log_handle,
                        env={"PYTHONUNBUFFERED": "1"},
                    )

        self.assertEqual(returncode, 0)
        self.assertTrue(popen_mock.call_args.kwargs["start_new_session"])
        cleanup_mock.assert_called_once_with(4321)

    def test_cleanup_process_group_escalates_when_children_linger(self):
        with patch("webapp.services.mineru_service.os.name", "posix"):
            with patch(
                "webapp.services.mineru_service.os.killpg",
                side_effect=[None, None, None, ProcessLookupError()],
            ) as killpg_mock:
                with patch(
                    "webapp.services.mineru_service.time.monotonic",
                    side_effect=[0.0, 0.5, 1.5, 2.5],
                ):
                    with patch("webapp.services.mineru_service.time.sleep"):
                        MineruTaskRunner._cleanup_process_group(4321)

        self.assertEqual(
            [call.args for call in killpg_mock.call_args_list],
            [
                (4321, 15),
                (4321, 0),
                (4321, 0),
                (4321, 9),
            ],
        )

    def test_is_managed_mineru_process_matches_spawn_worker_from_same_runtime(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        runner = MineruTaskRunner(build_settings(tmp_path))
        resolved_tmp_path = tmp_path.resolve()
        cmdline = (
            f"{resolved_tmp_path}/env/bin/python3.11 -c "
            "from multiprocessing.spawn import spawn_main; spawn_main(tracker_fd=13)"
        )

        self.assertTrue(runner._is_managed_mineru_process(cmdline))
        self.assertFalse(runner._is_managed_mineru_process("/usr/bin/python worker.py"))

    def test_cleanup_stale_processes_skips_active_groups(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        runner = MineruTaskRunner(build_settings(tmp_path))
        resolved_tmp_path = tmp_path.resolve()
        runner._register_active_process_group(3001)
        processes = [
            {
                "pid": 2001,
                "pgid": 3001,
                "age_seconds": 7200,
                "cmdline": (
                    f"{resolved_tmp_path}/env/bin/python3.11 -c "
                    "from multiprocessing.spawn import spawn_main; spawn_main()"
                ),
            },
            {
                "pid": 2002,
                "pgid": 3002,
                "age_seconds": 7200,
                "cmdline": (
                    f"{resolved_tmp_path}/env/bin/python3.11 -c "
                    "from multiprocessing.spawn import spawn_main; spawn_main()"
                ),
            },
        ]

        with patch("webapp.services.mineru_service.sys.platform", "linux"):
            with patch.object(runner, "_iter_linux_processes", return_value=processes):
                with patch.object(runner, "_cleanup_process_group") as cleanup_mock:
                    cleaned = runner._cleanup_stale_mineru_processes(max_age_seconds=3600)

        self.assertEqual(cleaned, 1)
        cleanup_mock.assert_called_once_with(3002)
