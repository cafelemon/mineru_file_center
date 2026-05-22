from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path


def commit_uploaded_file(temp_path: Path, destination_path: Path) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.replace(temp_path, destination_path)
        return
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise

    destination_temp_path = destination_path.with_name(
        f".{destination_path.name}.{os.getpid()}.tmp"
    )
    try:
        shutil.copy2(temp_path, destination_temp_path)
        os.replace(destination_temp_path, destination_path)
    except Exception:
        destination_temp_path.unlink(missing_ok=True)
        raise
    finally:
        temp_path.unlink(missing_ok=True)
