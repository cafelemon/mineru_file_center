from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import unittest
from unittest.mock import MagicMock, patch

from webapp.config import get_settings
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


class MineruServiceTests(unittest.TestCase):
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
