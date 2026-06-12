from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from webapp import main as main_module
from webapp.main import app
from webapp.services.fastgpt_sync_service import FastGPTSyncError


class StubRunner:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.doc_ids: list[str] = []

    def sync_task_to_fastgpt(self, doc_id: str) -> None:
        self.doc_ids.append(doc_id)
        if self.error is not None:
            raise self.error

    def shutdown(self) -> None:
        return None

class FastGPTRetryRouteTests(unittest.TestCase):
    def test_retry_fastgpt_sync_preserves_list_context(self):
        runner = StubRunner()
        settings = main_module.settings
        with TestClient(app) as client:
            app.state.task_runner = runner
            client.post(
                "/login",
                data={"username": settings.username, "password": settings.password},
                follow_redirects=False,
            )
            response = client.post(
                "/files/doc-1/retry-fastgpt-sync",
                data={
                    "knowledge_base_code": "general",
                    "folder_path": "制度库/人事",
                    "process_status": "success",
                    "q": "员工",
                    "sort_by": "name",
                    "sort_dir": "asc",
                    "page_size": "50",
                    "page": "2",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            location = response.headers["location"]
            self.assertIn("knowledge_base_code=general", location)
            self.assertIn("folder_path=%E5%88%B6%E5%BA%A6%E5%BA%93%2F%E4%BA%BA%E4%BA%8B", location)
            self.assertIn("page_size=50", location)
            self.assertIn("page=2", location)

    def test_retry_fastgpt_sync_redirects_with_message(self):
        runner = StubRunner()
        with TestClient(app) as client:
            app.state.task_runner = runner
            response = client.post(
                "/login",
                data={"username": "admin", "password": "change-me"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

            response = client.post(
                "/files/doc-1/retry-fastgpt-sync",
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("message=", response.headers["location"])
            self.assertEqual(runner.doc_ids, ["doc-1"])

    def test_retry_fastgpt_sync_redirects_with_error(self):
        runner = StubRunner(FastGPTSyncError("同步失败"))
        with TestClient(app) as client:
            app.state.task_runner = runner
            response = client.post(
                "/login",
                data={"username": "admin", "password": "change-me"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

            response = client.post(
                "/files/doc-2/retry-fastgpt-sync",
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertIn("error=", response.headers["location"])
            self.assertEqual(runner.doc_ids, ["doc-2"])
