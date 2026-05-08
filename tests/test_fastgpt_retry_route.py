from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

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
