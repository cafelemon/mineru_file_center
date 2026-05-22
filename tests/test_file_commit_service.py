from __future__ import annotations

import errno
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from webapp.services.file_commit_service import commit_uploaded_file


class FileCommitServiceTests(unittest.TestCase):
    def test_commit_uploaded_file_falls_back_when_temp_and_destination_cross_devices(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            import shutil

            shutil.rmtree(tmp_path)
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_path, ignore_errors=True))

        source_dir = tmp_path / "uploads"
        destination_dir = tmp_path / "source_cache"
        source_dir.mkdir(parents=True, exist_ok=True)
        destination_dir.mkdir(parents=True, exist_ok=True)
        temp_path = source_dir / "doc.uploading"
        destination_path = destination_dir / "doc.pdf"
        temp_path.write_bytes(b"%PDF-1.4\n")

        real_replace = os.replace
        calls: list[tuple[str, str]] = []

        def fake_replace(src, dst):
            calls.append((str(src), str(dst)))
            if Path(src) == temp_path and Path(dst) == destination_path:
                raise OSError(errno.EXDEV, "Invalid cross-device link")
            return real_replace(src, dst)

        with patch("webapp.services.file_commit_service.os.replace", side_effect=fake_replace):
            commit_uploaded_file(temp_path, destination_path)

        self.assertFalse(temp_path.exists())
        self.assertEqual(destination_path.read_bytes(), b"%PDF-1.4\n")
        self.assertGreaterEqual(len(calls), 2)
