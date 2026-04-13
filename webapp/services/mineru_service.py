from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .. import db
from ..config import Settings
from ..knowledge_bases import get_bridge_app_code, get_knowledge_base
from .bridge_export_service import BridgeExportService
from .bridge_registry_service import (
    BridgeRegistrySyncError,
    BridgeRegistrySyncService,
)
from .fastgpt_sync_service import FastGPTSyncError, FastGPTSyncService


logger = logging.getLogger("mineru_webapp.service")


class MineruTaskRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bridge_export_service = BridgeExportService(settings)
        self.bridge_registry_sync_service = BridgeRegistrySyncService(settings)
        self.fastgpt_sync_service = FastGPTSyncService(settings)
        self.executor = ThreadPoolExecutor(
            max_workers=settings.task_workers,
            thread_name_prefix="mineru-task",
        )

    def submit(self, doc_id: str) -> Future[None]:
        logger.info("Queue task %s", doc_id)
        return self.executor.submit(self._run_task, doc_id)

    def shutdown(self) -> None:
        self.fastgpt_sync_service.close()
        self.bridge_registry_sync_service.close()
        self.executor.shutdown(wait=False, cancel_futures=False)

    def _run_task(self, doc_id: str) -> None:
        task = db.get_task(self.settings, doc_id)
        if not task:
            logger.error("Task %s not found in database", doc_id)
            return

        started_at = _utc_now()
        db.update_task(
            self.settings,
            doc_id,
            process_status="processing",
            started_at=started_at,
            error_message="",
        )

        raw_output_dir = Path(task["mineru_task_dir"]) / "raw_output"
        raw_output_dir.mkdir(parents=True, exist_ok=True)
        log_path = Path(task["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)

        command = self._build_command(task["stored_pdf_path"], raw_output_dir)
        command_text = shlex.join(command)
        logger.info("Start MinerU task %s with command: %s", doc_id, command_text)

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        try:
            with log_path.open("a", encoding="utf-8") as log_handle:
                log_handle.write(f"[{started_at}] command: {command_text}\n")
                completed = subprocess.run(
                    command,
                    cwd=self.settings.project_root,
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
                    check=False,
                )
                log_handle.write(
                    f"[{_utc_now()}] process exited with code {completed.returncode}\n"
                )

            if completed.returncode != 0:
                raise RuntimeError(
                    f"MinerU exited with code {completed.returncode}. {self._tail_log(log_path)}"
                )

            final_md_source = self._find_markdown(raw_output_dir, doc_id)
            if final_md_source is None:
                raise FileNotFoundError(
                    "MinerU finished but no markdown file was found in raw_output."
                )

            final_md_path = self.settings.output_dir / f"{doc_id}.md"
            shutil.copy2(final_md_source, final_md_path)
            logger.info("Task %s markdown copied from %s", doc_id, final_md_source)

            completed_at = _utc_now()
            db.update_task(
                self.settings,
                doc_id,
                process_status="success",
                completed_at=completed_at,
                processed_time=completed_at,
                final_md_path=str(final_md_path),
                final_md_filename=final_md_path.name,
                fastgpt_sync_status="pending",
                fastgpt_sync_error="",
                error_message="",
            )

            sync_task = {
                **task,
                "process_status": "success",
                "completed_at": completed_at,
                "processed_time": completed_at,
                "final_md_path": str(final_md_path),
                "final_md_filename": final_md_path.name,
                "fastgpt_sync_status": "pending",
                "fastgpt_sync_error": "",
            }
            bridge_result = self._export_to_bridge(sync_task)
            self._sync_to_fastgpt(sync_task, bridge_result)
            logger.info("Task %s finished successfully", doc_id)
        except Exception as exc:
            logger.exception("Task %s failed", doc_id)
            db.update_task(
                self.settings,
                doc_id,
                process_status="failed",
                completed_at=_utc_now(),
                processed_time=_utc_now(),
                error_message=str(exc),
            )

    def _export_to_bridge(self, task: dict[str, Any]):
        if not self.bridge_export_service.is_enabled():
            return None

        doc_id = str(task["doc_id"])
        existing_notes = str(task.get("notes") or "").strip()
        try:
            result = self.bridge_export_service.export_task(task)
        except Exception as exc:
            logger.exception("Task %s bridge export failed", doc_id)
            note = _append_note(existing_notes, f"Bridge export failed: {exc}")
            db.update_task(self.settings, doc_id, notes=note)
            return None

        if result is None:
            return None

        logger.info(
            "Task %s exported to bridge pdf=%s manifest=%s",
            doc_id,
            result.exported_pdf_path,
            result.aggregate_manifest_path,
        )
        note = _append_note(
            existing_notes,
            (
                f"Bridge export ok: app_code={result.app_code}, "
                f"pdf={result.exported_pdf_path}, manifest={result.item_manifest_path}"
            ),
        )
        db.update_task(self.settings, doc_id, notes=note)
        return result

    def _sync_to_fastgpt(self, task: dict[str, Any], bridge_result: Any) -> None:
        doc_id = str(task["doc_id"])
        knowledge_base = get_knowledge_base(
            self.settings,
            task.get("knowledge_base_code"),
        )
        if not self.fastgpt_sync_service.is_enabled():
            logger.info(
                "Task %s skipped FastGPT sync because sync is disabled",
                doc_id,
            )
            return

        latest_task = db.get_task(self.settings, doc_id) or task
        existing_notes = str(latest_task.get("notes") or "").strip()
        try:
            sync_result = self.fastgpt_sync_service.sync_markdown(
                task=task,
                knowledge_base=knowledge_base,
            )
        except FastGPTSyncError as exc:
            logger.warning("Task %s FastGPT sync failed: %s", doc_id, exc)
            note = _append_note(existing_notes, f"FastGPT sync failed: {exc}")
            db.update_task(
                self.settings,
                doc_id,
                fastgpt_sync_status="failed",
                fastgpt_sync_error=str(exc),
                notes=note,
            )
            return

        note = _append_note(
            existing_notes,
            (
                "FastGPT sync ok: "
                f"dataset={sync_result.dataset_name}({sync_result.dataset_id}), "
                f"collection={sync_result.collection_id}, insert_len={sync_result.insert_len}"
            ),
        )
        db.update_task(
            self.settings,
            doc_id,
            fastgpt_dataset_id=sync_result.dataset_id,
            fastgpt_dataset_name=sync_result.dataset_name,
            fastgpt_collection_id=sync_result.collection_id,
            fastgpt_sync_status="synced",
            fastgpt_synced_at=_utc_now(),
            fastgpt_sync_error="",
            notes=note,
        )

        if not self.bridge_registry_sync_service.is_enabled():
            note = _append_note(
                note,
                "Bridge registry sync skipped: BRIDGE_API_BASE_URL 未配置",
            )
            db.update_task(self.settings, doc_id, notes=note)
            return

        try:
            self.bridge_registry_sync_service.register_mapping(
                task=task,
                collection_id=sync_result.collection_id,
                app_code=get_bridge_app_code(task.get("knowledge_base_code")),
                exported_pdf_path=bridge_result.exported_pdf_path if bridge_result is not None else None,
            )
        except BridgeRegistrySyncError as exc:
            logger.warning("Task %s Bridge registry sync failed: %s", doc_id, exc)
            note = _append_note(note, f"Bridge registry sync failed: {exc}")
            db.update_task(self.settings, doc_id, notes=note)
            return

        note = _append_note(note, "Bridge registry sync ok")
        db.update_task(self.settings, doc_id, notes=note)

    def sync_task_to_fastgpt(self, doc_id: str) -> None:
        if not self.fastgpt_sync_service.is_enabled():
            raise FastGPTSyncError("FastGPT 自动同步未启用")
        task = db.get_task(self.settings, doc_id)
        if not task:
            raise FastGPTSyncError("任务不存在")
        if str(task.get("process_status") or "") != "success":
            raise FastGPTSyncError("仅处理成功的任务可以同步到 FastGPT")
        bridge_result = self._export_to_bridge(task)
        self._sync_to_fastgpt(task, bridge_result)

    def _build_command(self, stored_pdf_path: str, raw_output_dir: Path) -> list[str]:
        command = list(self.settings.mineru_command)
        command.extend(
            [
                "-p",
                stored_pdf_path,
                "-o",
                str(raw_output_dir),
                "-b",
                self.settings.mineru_backend,
            ]
        )
        if self.settings.mineru_method:
            command.extend(["-m", self.settings.mineru_method])
        if self.settings.mineru_lang:
            command.extend(["-l", self.settings.mineru_lang])
        if self.settings.mineru_api_url:
            command.extend(["--api-url", self.settings.mineru_api_url])
        command.extend(self.settings.mineru_extra_args)
        return command

    @staticmethod
    def _find_markdown(raw_output_dir: Path, doc_id: str) -> Path | None:
        exact_matches = sorted(raw_output_dir.rglob(f"{doc_id}.md"))
        if exact_matches:
            return exact_matches[0]

        markdown_files = sorted(
            raw_output_dir.rglob("*.md"),
            key=lambda path: (len(path.parts), str(path)),
        )
        return markdown_files[0] if markdown_files else None

    @staticmethod
    def _tail_log(log_path: Path, line_count: int = 12) -> str:
        if not log_path.exists():
            return "Check task.log for details."
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return "Check task.log for details."
        tail = " | ".join(lines[-line_count:]).strip()
        return tail[:1800] if tail else "Check task.log for details."


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_note(existing_notes: str, message: str) -> str:
    stamped = f"[{_utc_now()}] {message}"
    return f"{existing_notes}\n{stamped}".strip() if existing_notes else stamped
