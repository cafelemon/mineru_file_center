from __future__ import annotations

import logging
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import time
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
from .document_conversion_service import convert_source_file_to_markdown
from .fastgpt_sync_service import FastGPTSyncError, FastGPTSyncService


logger = logging.getLogger("mineru_webapp.service")


class MineruTaskRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.bridge_export_service = BridgeExportService(settings)
        self.bridge_registry_sync_service = BridgeRegistrySyncService(settings)
        self.fastgpt_sync_service = FastGPTSyncService(settings)
        self._process_lock = threading.Lock()
        self._active_process_groups: set[int] = set()
        self._reaper_stop_event = threading.Event()
        self._reaper_thread: threading.Thread | None = None
        self.executor = ThreadPoolExecutor(
            max_workers=settings.task_workers,
            thread_name_prefix="mineru-task",
        )
        self._startup_cleanup_stale_processes()
        self._start_reaper_thread_if_needed()

    def submit(self, doc_id: str) -> Future[None]:
        logger.info("Queue task %s", doc_id)
        return self.executor.submit(self._run_task, doc_id)

    def shutdown(self) -> None:
        self._reaper_stop_event.set()
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=2.0)
        self._cleanup_active_process_groups()
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

        try:
            processor_type = str(task.get("processor_type") or "mineru_pdf").strip()
            source_file_path = str(task.get("source_file_path") or task["stored_pdf_path"])
            if processor_type == "mineru_pdf":
                final_md_path = self._run_pdf_mineru_task(
                    doc_id=doc_id,
                    source_file_path=source_file_path,
                    raw_output_dir=raw_output_dir,
                    log_path=log_path,
                    started_at=started_at,
                )
            elif processor_type in {"docx_markdown", "excel_markdown"}:
                final_md_path = self._run_document_conversion_task(
                    doc_id=doc_id,
                    source_file_path=source_file_path,
                    processor_type=processor_type,
                    log_path=log_path,
                    started_at=started_at,
                )
            else:
                raise RuntimeError(f"Unsupported processor_type: {processor_type}")

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

    def _run_pdf_mineru_task(
        self,
        *,
        doc_id: str,
        source_file_path: str,
        raw_output_dir: Path,
        log_path: Path,
        started_at: str,
    ) -> Path:
        command = self._build_command(source_file_path, raw_output_dir)
        command_text = shlex.join(command)
        logger.info("Start MinerU task %s with command: %s", doc_id, command_text)

        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")

        with log_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write(f"[{started_at}] command: {command_text}\n")
            returncode = self._run_mineru_process(
                command,
                log_handle=log_handle,
                env=env,
            )
            log_handle.write(f"[{_utc_now()}] process exited with code {returncode}\n")

        if returncode != 0:
            raise RuntimeError(
                f"MinerU exited with code {returncode}. {self._tail_log(log_path)}"
            )

        final_md_source = self._find_markdown(raw_output_dir, doc_id)
        if final_md_source is None:
            raise FileNotFoundError(
                "MinerU finished but no markdown file was found in raw_output."
            )

        final_md_path = self.settings.output_dir / f"{doc_id}.md"
        shutil.copy2(final_md_source, final_md_path)
        logger.info("Task %s markdown copied from %s", doc_id, final_md_source)
        return final_md_path

    def _run_document_conversion_task(
        self,
        *,
        doc_id: str,
        source_file_path: str,
        processor_type: str,
        log_path: Path,
        started_at: str,
    ) -> Path:
        source_path = Path(source_file_path)
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(f"Source file does not exist: {source_path}")

        logger.info(
            "Start local document conversion task %s processor=%s source=%s",
            doc_id,
            processor_type,
            source_path,
        )
        with log_path.open("a", encoding="utf-8") as log_handle:
            log_handle.write(
                f"[{started_at}] local conversion processor={processor_type} source={source_path}\n"
            )
            markdown_text = convert_source_file_to_markdown(source_path, processor_type)
            final_md_path = self.settings.output_dir / f"{doc_id}.md"
            final_md_path.parent.mkdir(parents=True, exist_ok=True)
            final_md_path.write_text(markdown_text, encoding="utf-8")
            log_handle.write(
                f"[{_utc_now()}] local conversion completed chars={len(markdown_text)}\n"
            )

        logger.info("Task %s markdown generated from %s", doc_id, source_path)
        return final_md_path

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
            fastgpt_sync_status="pending",
            fastgpt_sync_error="",
            notes=note,
        )

        if not self.bridge_registry_sync_service.is_enabled():
            error_message = "Bridge registry sync skipped: BRIDGE_API_BASE_URL 未配置"
            note = _append_note(
                note,
                error_message,
            )
            db.update_task(
                self.settings,
                doc_id,
                fastgpt_sync_status="failed",
                fastgpt_sync_error=error_message,
                notes=note,
            )
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
            db.update_task(
                self.settings,
                doc_id,
                fastgpt_sync_status="failed",
                fastgpt_sync_error=str(exc),
                notes=note,
            )
            return

        note = _append_note(note, "Bridge registry sync ok")
        db.update_task(
            self.settings,
            doc_id,
            fastgpt_sync_status="synced",
            fastgpt_synced_at=_utc_now(),
            fastgpt_sync_error="",
            notes=note,
        )

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

    def _run_mineru_process(
        self,
        command: list[str],
        *,
        log_handle,
        env: dict[str, str],
    ) -> int:
        popen_kwargs: dict[str, Any] = {
            "cwd": self.settings.project_root,
            "stdout": log_handle,
            "stderr": subprocess.STDOUT,
            "text": True,
            "env": env,
        }
        if os.name == "posix":
            # Keep each MinerU task in its own process group so we can clean up
            # multiprocessing children that outlive the CLI parent.
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(command, **popen_kwargs)
        process_group_id = self._get_process_group_id(process.pid)
        self._register_active_process_group(process_group_id)
        try:
            timeout_seconds = self.settings.mineru_process_timeout_seconds
            if timeout_seconds > 0:
                return process.wait(timeout=timeout_seconds)
            return process.wait()
        except subprocess.TimeoutExpired as exc:
            log_handle.write(
                f"[{_utc_now()}] process exceeded timeout {timeout_seconds}s and will be terminated\n"
            )
            self._cleanup_process_group(process_group_id)
            raise RuntimeError(
                f"MinerU exceeded timeout of {timeout_seconds} seconds."
            ) from exc
        finally:
            self._unregister_active_process_group(process_group_id)
            self._cleanup_process_group(process_group_id)

    @staticmethod
    def _cleanup_process_group(process_pid: int) -> None:
        if os.name != "posix" or process_pid <= 0:
            return

        try:
            os.killpg(process_pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except PermissionError:
            logger.warning(
                "Permission denied when cleaning MinerU process group %s",
                process_pid,
            )
            return

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            try:
                os.killpg(process_pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)

        try:
            os.killpg(process_pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except PermissionError:
            logger.warning(
                "Permission denied when force killing MinerU process group %s",
                process_pid,
            )

    def _startup_cleanup_stale_processes(self) -> None:
        cleaned = self._cleanup_stale_mineru_processes(max_age_seconds=None)
        if cleaned:
            logger.warning("Cleaned %s stale MinerU process groups during startup", cleaned)

    def _start_reaper_thread_if_needed(self) -> None:
        if not sys.platform.startswith("linux"):
            return
        if self.settings.mineru_stale_process_scan_interval_seconds <= 0:
            return
        if self.settings.mineru_stale_process_max_age_seconds <= 0:
            return

        self._reaper_thread = threading.Thread(
            target=self._reaper_loop,
            name="mineru-stale-process-reaper",
            daemon=True,
        )
        self._reaper_thread.start()

    def _reaper_loop(self) -> None:
        interval = self.settings.mineru_stale_process_scan_interval_seconds
        max_age = self.settings.mineru_stale_process_max_age_seconds
        while not self._reaper_stop_event.wait(interval):
            cleaned = self._cleanup_stale_mineru_processes(max_age_seconds=max_age)
            if cleaned:
                logger.warning(
                    "Cleaned %s stale MinerU process groups older than %ss",
                    cleaned,
                    max_age,
                )

    def _cleanup_active_process_groups(self) -> None:
        with self._process_lock:
            active_groups = list(self._active_process_groups)
        for process_group_id in active_groups:
            self._cleanup_process_group(process_group_id)

    def _register_active_process_group(self, process_group_id: int) -> None:
        if process_group_id <= 0:
            return
        with self._process_lock:
            self._active_process_groups.add(process_group_id)

    def _unregister_active_process_group(self, process_group_id: int) -> None:
        if process_group_id <= 0:
            return
        with self._process_lock:
            self._active_process_groups.discard(process_group_id)

    @staticmethod
    def _get_process_group_id(process_pid: int) -> int:
        if os.name != "posix" or process_pid <= 0:
            return process_pid
        try:
            return os.getpgid(process_pid)
        except ProcessLookupError:
            return process_pid

    def _cleanup_stale_mineru_processes(
        self,
        *,
        max_age_seconds: int | None,
    ) -> int:
        if not sys.platform.startswith("linux"):
            return 0

        with self._process_lock:
            active_groups = set(self._active_process_groups)

        cleaned_groups: set[int] = set()
        for process_info in self._iter_linux_processes():
            if process_info["pid"] == os.getpid():
                continue
            if not self._is_managed_mineru_process(str(process_info["cmdline"])):
                continue
            process_group_id = int(process_info["pgid"])
            if process_group_id <= 0 or process_group_id in active_groups:
                continue
            age_seconds = int(process_info["age_seconds"])
            if max_age_seconds is not None and age_seconds < max_age_seconds:
                continue
            if process_group_id in cleaned_groups:
                continue
            logger.warning(
                "Cleaning stale MinerU process group %s (pid=%s age=%ss cmd=%s)",
                process_group_id,
                process_info["pid"],
                age_seconds,
                process_info["cmdline"],
            )
            self._cleanup_process_group(process_group_id)
            cleaned_groups.add(process_group_id)
        return len(cleaned_groups)

    def _is_managed_mineru_process(self, cmdline_text: str) -> bool:
        if not cmdline_text:
            return False

        runtime_markers = self._managed_runtime_markers()
        if not runtime_markers:
            return False

        is_spawn_worker = (
            "multiprocessing.spawn import spawn_main" in cmdline_text
            or "--multiprocessing-fork" in cmdline_text
        )
        is_mineru_command = any(
            marker in cmdline_text for marker in self._managed_command_markers()
        )
        belongs_to_runtime = any(marker in cmdline_text for marker in runtime_markers)
        return belongs_to_runtime and (is_spawn_worker or is_mineru_command)

    def _managed_command_markers(self) -> set[str]:
        markers: set[str] = set()
        for raw_value in self.settings.mineru_command[:1]:
            text = str(raw_value).strip()
            if not text:
                continue
            if os.path.isabs(text):
                markers.add(str(Path(text).resolve()))
            else:
                markers.add(str((self.settings.project_root / text).resolve()))
                markers.add(text)
        return markers

    def _managed_runtime_markers(self) -> set[str]:
        markers = {str(self.settings.project_root.resolve())}
        for marker in self._managed_command_markers():
            path = Path(marker)
            if not path.is_absolute():
                continue
            parts = path.parts
            if len(parts) >= 3 and parts[-2] == "bin":
                runtime_root = str(path.parent.parent)
                markers.add(runtime_root)
                markers.add(str(Path(runtime_root) / "bin"))
        return markers

    @staticmethod
    def _iter_linux_processes() -> list[dict[str, Any]]:
        process_root = Path("/proc")
        uptime_path = process_root / "uptime"
        if not uptime_path.exists():
            return []

        try:
            uptime_seconds = float(uptime_path.read_text(encoding="utf-8").split()[0])
        except (OSError, ValueError, IndexError):
            return []
        clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])

        processes: list[dict[str, Any]] = []
        for entry in process_root.iterdir():
            if not entry.name.isdigit():
                continue
            try:
                stat_text = (entry / "stat").read_text(encoding="utf-8")
                cmdline_bytes = (entry / "cmdline").read_bytes()
            except OSError:
                continue
            if not cmdline_bytes:
                continue

            stat_fields = stat_text.split()
            if len(stat_fields) < 22:
                continue
            try:
                pid = int(stat_fields[0])
                pgid = int(stat_fields[4])
                start_ticks = int(stat_fields[21])
            except ValueError:
                continue

            age_seconds = max(0, int(uptime_seconds - (start_ticks / clock_ticks)))
            cmdline_text = cmdline_bytes.replace(b"\x00", b" ").decode(
                "utf-8",
                errors="ignore",
            ).strip()
            processes.append(
                {
                    "pid": pid,
                    "pgid": pgid,
                    "age_seconds": age_seconds,
                    "cmdline": cmdline_text,
                }
            )
        return processes

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
