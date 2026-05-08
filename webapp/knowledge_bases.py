from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .config import Settings


DEFAULT_KNOWLEDGE_BASE_CODE = "general"


@dataclass(slots=True)
class KnowledgeBase:
    code: str
    display_name: str
    is_builtin: int = 0


BUILTIN_KNOWLEDGE_BASES: tuple[KnowledgeBase, ...] = (
    KnowledgeBase(code="general", display_name="通用知识库"),
    KnowledgeBase(code="executive", display_name="高层知识库"),
    KnowledgeBase(code="quality_system", display_name="质量体系部知识库"),
    KnowledgeBase(code="medical_reg", display_name="医疗注册部知识库"),
)

BRIDGE_APP_CODE_MAP = {
    "general": "general_common",
    "executive": "executive_all",
    "quality_system": "quality_system",
    "medical_reg": "regulatory_affairs",
}

KNOWLEDGE_BASE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_bases (
    code TEXT PRIMARY KEY,
    display_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    is_builtin INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0
)
"""

OPTIONAL_KNOWLEDGE_BASE_COLUMNS: dict[str, str] = {
    "sort_order": "INTEGER NOT NULL DEFAULT 0",
}


class KnowledgeBaseError(ValueError):
    pass


class InvalidKnowledgeBaseNameError(KnowledgeBaseError):
    pass


class KnowledgeBaseExistsError(KnowledgeBaseError):
    pass


class KnowledgeBaseNotFoundError(KnowledgeBaseError):
    pass


class KnowledgeBaseInUseError(KnowledgeBaseError):
    pass


def init_knowledge_bases(settings: Settings) -> None:
    with _connect(settings) as connection:
        table_exists = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'knowledge_bases'
            """
        ).fetchone() is not None
        connection.execute(KNOWLEDGE_BASE_TABLE_SQL)
        _migrate_knowledge_base_schema(connection)
        if not table_exists:
            _seed_builtin_knowledge_bases(connection)
        connection.commit()


def list_knowledge_bases(settings: Settings) -> list[dict[str, Any]]:
    with _connect(settings) as connection:
        rows = connection.execute(
            """
            SELECT code, display_name, is_builtin
            FROM knowledge_bases
            ORDER BY sort_order ASC, created_at ASC, display_name ASC
            """
        ).fetchall()
    return [asdict(_row_to_knowledge_base(row)) for row in rows]


def knowledge_base_exists(settings: Settings, code: str | None) -> bool:
    if not code:
        return False
    return _find_knowledge_base(settings, code.strip()) is not None


def get_knowledge_base(settings: Settings, code: str | None) -> KnowledgeBase:
    if code:
        knowledge_base = _find_knowledge_base(settings, code.strip())
        if knowledge_base is not None:
            return knowledge_base

    knowledge_base = _find_knowledge_base(settings, DEFAULT_KNOWLEDGE_BASE_CODE)
    if knowledge_base is not None:
        return knowledge_base

    with _connect(settings) as connection:
        row = connection.execute(
            """
            SELECT code, display_name, is_builtin
            FROM knowledge_bases
            ORDER BY sort_order ASC, created_at ASC, display_name ASC
            LIMIT 1
            """
        ).fetchone()
    if row is not None:
        return _row_to_knowledge_base(row)

    return KnowledgeBase(code=DEFAULT_KNOWLEDGE_BASE_CODE, display_name="通用知识库", is_builtin=1)


def get_default_knowledge_base_code(settings: Settings) -> str:
    return get_knowledge_base(settings, DEFAULT_KNOWLEDGE_BASE_CODE).code


def create_knowledge_base(settings: Settings, display_name: str) -> KnowledgeBase:
    normalized_name = _normalize_display_name(display_name)
    now = _utc_now()

    with _connect(settings) as connection:
        existing = connection.execute(
            "SELECT 1 FROM knowledge_bases WHERE display_name = ?",
            (normalized_name,),
        ).fetchone()
        if existing is not None:
            raise KnowledgeBaseExistsError("知识库名称已存在")

        code = _generate_knowledge_base_code(connection, now)
        sort_order = connection.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 10 FROM knowledge_bases"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO knowledge_bases (
                code, display_name, created_at, updated_at, is_builtin, sort_order
            )
            VALUES (?, ?, ?, ?, 0, ?)
            """,
            (code, normalized_name, now, now, sort_order),
        )
        connection.commit()

    return KnowledgeBase(code=code, display_name=normalized_name, is_builtin=0)


def delete_knowledge_base(settings: Settings, code: str) -> None:
    normalized_code = (code or "").strip()
    if not normalized_code:
        raise KnowledgeBaseNotFoundError("知识库不存在")

    with _connect(settings) as connection:
        knowledge_base = connection.execute(
            "SELECT code FROM knowledge_bases WHERE code = ?",
            (normalized_code,),
        ).fetchone()
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("知识库不存在")

        task_count = connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE knowledge_base_code = ?",
            (normalized_code,),
        ).fetchone()[0]
        if task_count:
            raise KnowledgeBaseInUseError("该知识库下已有文件，不能删除")

        connection.execute(
            "DELETE FROM knowledge_bases WHERE code = ?",
            (normalized_code,),
        )
        connection.commit()


def get_bridge_app_code(code: str | None) -> str:
    normalized_code = (code or DEFAULT_KNOWLEDGE_BASE_CODE).strip()
    if not normalized_code:
        normalized_code = DEFAULT_KNOWLEDGE_BASE_CODE
    return BRIDGE_APP_CODE_MAP.get(normalized_code, normalized_code)


def _connect(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _migrate_knowledge_base_schema(connection: sqlite3.Connection) -> None:
    columns = {
        row[1]
        for row in connection.execute("PRAGMA table_info(knowledge_bases)").fetchall()
    }
    for column_name, column_type in OPTIONAL_KNOWLEDGE_BASE_COLUMNS.items():
        if column_name in columns:
            continue
        connection.execute(
            f"ALTER TABLE knowledge_bases ADD COLUMN {column_name} {column_type}"
        )


def _seed_builtin_knowledge_bases(connection: sqlite3.Connection) -> None:
    now = _utc_now()
    for index, item in enumerate(BUILTIN_KNOWLEDGE_BASES):
        connection.execute(
            """
            INSERT INTO knowledge_bases (
                code, display_name, created_at, updated_at, is_builtin, sort_order
            )
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (item.code, item.display_name, now, now, index * 10),
        )


def _find_knowledge_base(settings: Settings, code: str) -> KnowledgeBase | None:
    with _connect(settings) as connection:
        row = connection.execute(
            """
            SELECT code, display_name, is_builtin
            FROM knowledge_bases
            WHERE code = ?
            """,
            (code,),
        ).fetchone()
    return _row_to_knowledge_base(row) if row is not None else None


def _row_to_knowledge_base(row: sqlite3.Row) -> KnowledgeBase:
    return KnowledgeBase(
        code=str(row["code"]),
        display_name=str(row["display_name"]),
        is_builtin=int(row["is_builtin"] or 0),
    )


def _normalize_display_name(display_name: str) -> str:
    normalized = " ".join((display_name or "").strip().split())
    if not normalized:
        raise InvalidKnowledgeBaseNameError("知识库名称不能为空")
    if len(normalized) > 80:
        raise InvalidKnowledgeBaseNameError("知识库名称不能超过 80 个字符")
    return normalized


def _generate_knowledge_base_code(connection: sqlite3.Connection, now: str) -> str:
    timestamp = (
        datetime.fromisoformat(now)
        .astimezone(timezone.utc)
        .strftime("%Y%m%d%H%M%S")
    )
    base_code = f"kb_{timestamp}"
    code = base_code
    suffix = 2
    while connection.execute(
        "SELECT 1 FROM knowledge_bases WHERE code = ?",
        (code,),
    ).fetchone():
        code = f"{base_code}_{suffix}"
        suffix += 1
    return code


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
