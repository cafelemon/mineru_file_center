from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _get_nested(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _coerce_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_path(project_root: Path, raw_value: Any, default: Path) -> Path:
    if raw_value in (None, ""):
        path = default
    else:
        path = Path(str(raw_value))
        if not path.is_absolute():
            path = project_root / path
    return path.resolve()


def _coerce_list(raw_value: Any, default: list[str]) -> list[str]:
    if raw_value in (None, ""):
        return list(default)
    if isinstance(raw_value, list):
        return [str(item) for item in raw_value if str(item).strip()]
    if isinstance(raw_value, str):
        return shlex.split(raw_value)
    return list(default)


@dataclass(slots=True)
class Settings:
    project_root: Path
    config_path: Path
    host: str
    port: int
    session_secret: str
    username: str
    password: str
    max_upload_size_mb: int
    data_root: Path
    uploads_dir: Path
    pdf_store_dir: Path
    output_dir: Path
    tasks_dir: Path
    logs_dir: Path
    database_path: Path
    mineru_command: list[str] = field(default_factory=list)
    mineru_backend: str = "pipeline"
    mineru_method: str = "auto"
    mineru_lang: str = "ch"
    mineru_api_url: str | None = None
    mineru_extra_args: list[str] = field(default_factory=list)
    task_workers: int = 1
    bridge_export_enabled: bool = False
    bridge_pdf_root: Path | None = None
    bridge_manifest_dir: Path | None = None
    bridge_api_base_url: str = ""
    file_link_enabled: bool = True
    file_link_secret: str = ""
    file_link_expire_seconds: int = 600
    file_link_base_url: str = ""
    fastgpt_sync_enabled: bool = False
    fastgpt_base_url: str = ""
    fastgpt_api_key: str = ""
    fastgpt_training_type: str = "chunk"
    fastgpt_chunk_setting_mode: str = "auto"
    fastgpt_chunk_size: int | None = None

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        for path in (
            self.data_root,
            self.uploads_dir,
            self.pdf_store_dir,
            self.output_dir,
            self.tasks_dir,
            self.logs_dir,
            self.database_path.parent,
        ):
            path.mkdir(parents=True, exist_ok=True)
        if self.bridge_export_enabled:
            for path in (self.bridge_pdf_root, self.bridge_manifest_dir):
                if path is not None:
                    path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    project_root = Path(__file__).resolve().parent.parent
    config_path = Path(
        os.getenv("WEBAPP_CONFIG", str(project_root / "webapp" / "config.toml"))
    ).expanduser()
    if not config_path.is_absolute():
        config_path = (project_root / config_path).resolve()

    config = _load_toml(config_path)

    host = os.getenv("WEB_HOST") or _get_nested(config, "server", "host", default="0.0.0.0")
    port = _coerce_int(
        os.getenv("WEB_PORT") or _get_nested(config, "server", "port", default=7860),
        7860,
    )
    session_secret = (
        os.getenv("WEB_SESSION_SECRET")
        or _get_nested(config, "server", "session_secret", default="change-me-session-secret")
    )
    username = os.getenv("WEB_USERNAME") or _get_nested(
        config, "auth", "username", default="admin"
    )
    password = os.getenv("WEB_PASSWORD") or _get_nested(
        config, "auth", "password", default="change-me"
    )
    data_root = _coerce_path(
        project_root,
        os.getenv("WEB_DATA_ROOT") or _get_nested(config, "storage", "data_root"),
        project_root / "data",
    )

    uploads_dir = _coerce_path(
        project_root,
        os.getenv("WEB_UPLOADS_DIR") or _get_nested(config, "storage", "uploads_dir"),
        data_root / "uploads",
    )
    pdf_store_dir = _coerce_path(
        project_root,
        os.getenv("WEB_PDF_STORE_DIR") or _get_nested(config, "storage", "pdf_store_dir"),
        data_root / "pdf_store",
    )
    output_dir = _coerce_path(
        project_root,
        os.getenv("WEB_OUTPUT_DIR") or _get_nested(config, "storage", "output_dir"),
        data_root / "output",
    )
    tasks_dir = _coerce_path(
        project_root,
        os.getenv("WEB_TASKS_DIR") or _get_nested(config, "storage", "tasks_dir"),
        data_root / "tasks",
    )
    logs_dir = _coerce_path(
        project_root,
        os.getenv("WEB_LOGS_DIR") or _get_nested(config, "storage", "logs_dir"),
        data_root / "logs",
    )
    database_path = _coerce_path(
        project_root,
        os.getenv("WEB_DB_PATH") or _get_nested(config, "storage", "database_path"),
        data_root / "app.db",
    )
    max_upload_size_mb = _coerce_int(
        os.getenv("WEB_MAX_UPLOAD_SIZE_MB")
        or _get_nested(config, "storage", "max_upload_size_mb", default=200),
        200,
    )

    mineru_command = _coerce_list(
        os.getenv("MINERU_COMMAND") or _get_nested(config, "mineru", "command"),
        ["env/bin/mineru"] if (project_root / "env" / "bin" / "mineru").exists() else ["mineru"],
    )
    mineru_backend = os.getenv("MINERU_BACKEND") or _get_nested(
        config, "mineru", "backend", default="pipeline"
    )
    mineru_method = os.getenv("MINERU_METHOD") or _get_nested(
        config, "mineru", "method", default="auto"
    )
    mineru_lang = os.getenv("MINERU_LANG") or _get_nested(
        config, "mineru", "lang", default="ch"
    )
    mineru_api_url = os.getenv("MINERU_API_URL") or _get_nested(
        config, "mineru", "api_url", default=""
    )
    mineru_extra_args = _coerce_list(
        os.getenv("MINERU_EXTRA_ARGS") or _get_nested(config, "mineru", "extra_args"),
        [],
    )
    task_workers = _coerce_int(
        os.getenv("MINERU_MAX_WORKERS")
        or _get_nested(config, "mineru", "task_workers", default=1),
        1,
    )
    bridge_export_enabled = _coerce_bool(
        os.getenv("BRIDGE_EXPORT_ENABLED")
        or _get_nested(config, "bridge_export", "enabled", default=False),
        False,
    )
    bridge_pdf_root = None
    raw_bridge_pdf_root = os.getenv("BRIDGE_PDF_ROOT") or _get_nested(
        config, "bridge_export", "pdf_root"
    )
    if raw_bridge_pdf_root not in (None, ""):
        bridge_pdf_root = _coerce_path(project_root, raw_bridge_pdf_root, data_root / "bridge_pdf_store")
    bridge_manifest_dir = None
    raw_bridge_manifest_dir = os.getenv("BRIDGE_MANIFEST_DIR") or _get_nested(
        config, "bridge_export", "manifest_dir"
    )
    if raw_bridge_manifest_dir not in (None, ""):
        bridge_manifest_dir = _coerce_path(
            project_root,
            raw_bridge_manifest_dir,
            data_root / "bridge_exports",
        )
    elif bridge_export_enabled:
        bridge_manifest_dir = (data_root / "bridge_exports").resolve()
    bridge_api_base_url = (
        os.getenv("BRIDGE_API_BASE_URL")
        or _get_nested(config, "bridge_export", "api_base_url", default="")
    )

    file_link_enabled = _coerce_bool(
        os.getenv("FILE_LINK_ENABLED")
        or _get_nested(config, "file_link", "enabled", default=True),
        True,
    )
    file_link_secret = (
        os.getenv("FILE_LINK_SECRET")
        or _get_nested(config, "file_link", "secret", default="")
    )
    file_link_expire_seconds = _coerce_int(
        os.getenv("FILE_LINK_EXPIRE_SECONDS")
        or _get_nested(config, "file_link", "expire_seconds", default=600),
        600,
    )
    file_link_base_url = (
        os.getenv("FILE_LINK_BASE_URL")
        or _get_nested(config, "file_link", "base_url", default="")
    )
    fastgpt_sync_enabled = _coerce_bool(
        os.getenv("FASTGPT_SYNC_ENABLED")
        or _get_nested(config, "fastgpt_sync", "enabled", default=False),
        False,
    )
    fastgpt_base_url = (
        os.getenv("FASTGPT_BASE_URL")
        or _get_nested(config, "fastgpt_sync", "base_url", default="")
    )
    fastgpt_api_key = (
        os.getenv("FASTGPT_API_KEY")
        or _get_nested(config, "fastgpt_sync", "api_key", default="")
    )
    fastgpt_training_type = (
        os.getenv("FASTGPT_TRAINING_TYPE")
        or _get_nested(config, "fastgpt_sync", "training_type", default="chunk")
    )
    fastgpt_chunk_setting_mode = (
        os.getenv("FASTGPT_CHUNK_SETTING_MODE")
        or _get_nested(config, "fastgpt_sync", "chunk_setting_mode", default="auto")
    )
    raw_fastgpt_chunk_size = (
        os.getenv("FASTGPT_CHUNK_SIZE")
        or _get_nested(config, "fastgpt_sync", "chunk_size", default="")
    )
    fastgpt_chunk_size = None
    if raw_fastgpt_chunk_size not in (None, ""):
        parsed_chunk_size = _coerce_int(raw_fastgpt_chunk_size, 0)
        fastgpt_chunk_size = parsed_chunk_size if parsed_chunk_size > 0 else None

    return Settings(
        project_root=project_root,
        config_path=config_path,
        host=str(host),
        port=port,
        session_secret=str(session_secret),
        username=str(username),
        password=str(password),
        max_upload_size_mb=max_upload_size_mb,
        data_root=data_root,
        uploads_dir=uploads_dir,
        pdf_store_dir=pdf_store_dir,
        output_dir=output_dir,
        tasks_dir=tasks_dir,
        logs_dir=logs_dir,
        database_path=database_path,
        mineru_command=mineru_command,
        mineru_backend=str(mineru_backend),
        mineru_method=str(mineru_method),
        mineru_lang=str(mineru_lang),
        mineru_api_url=str(mineru_api_url).strip() or None,
        mineru_extra_args=mineru_extra_args,
        task_workers=max(1, task_workers),
        bridge_export_enabled=bridge_export_enabled,
        bridge_pdf_root=bridge_pdf_root,
        bridge_manifest_dir=bridge_manifest_dir,
        bridge_api_base_url=str(bridge_api_base_url).strip().rstrip("/"),
        file_link_enabled=file_link_enabled,
        file_link_secret=str(file_link_secret).strip(),
        file_link_expire_seconds=max(1, file_link_expire_seconds),
        file_link_base_url=str(file_link_base_url).strip().rstrip("/"),
        fastgpt_sync_enabled=fastgpt_sync_enabled,
        fastgpt_base_url=str(fastgpt_base_url).strip().rstrip("/"),
        fastgpt_api_key=str(fastgpt_api_key).strip(),
        fastgpt_training_type=str(fastgpt_training_type).strip() or "chunk",
        fastgpt_chunk_setting_mode=str(fastgpt_chunk_setting_mode).strip() or "auto",
        fastgpt_chunk_size=fastgpt_chunk_size,
    )
