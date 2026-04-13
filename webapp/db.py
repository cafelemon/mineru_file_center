from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import Settings


TASK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    doc_id TEXT PRIMARY KEY,
    knowledge_base_code TEXT,
    original_filename TEXT NOT NULL,
    stored_pdf_path TEXT NOT NULL,
    stored_pdf_filename TEXT,
    final_md_path TEXT,
    final_md_filename TEXT,
    upload_time TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    processed_time TEXT,
    process_status TEXT NOT NULL,
    error_message TEXT,
    mineru_task_dir TEXT NOT NULL,
    log_path TEXT NOT NULL,
    file_sha256 TEXT,
    notes TEXT,
    file_size_bytes INTEGER,
    mineru_backend TEXT NOT NULL,
    mineru_method TEXT NOT NULL
)
"""

OPTIONAL_TASK_COLUMNS: dict[str, str] = {
    "knowledge_base_code": "TEXT",
    "stored_pdf_filename": "TEXT",
    "final_md_filename": "TEXT",
    "processed_time": "TEXT",
    "fastgpt_dataset_id": "TEXT",
    "fastgpt_dataset_name": "TEXT",
    "fastgpt_collection_id": "TEXT",
    "fastgpt_sync_status": "TEXT",
    "fastgpt_synced_at": "TEXT",
    "fastgpt_sync_error": "TEXT",
}


def _connect(settings: Settings) -> sqlite3.Connection:
    connection = sqlite3.connect(settings.database_path)
    connection.row_factory = sqlite3.Row
    return connection


def _task_columns(connection: sqlite3.Connection) -> set[str]:
    return {row[1] for row in connection.execute("PRAGMA table_info(tasks)").fetchall()}


def init_db(settings: Settings) -> None:
    with closing(_connect(settings)) as connection:
        connection.execute(TASK_TABLE_SQL)
        _migrate_tasks_schema(connection)
        connection.commit()
    from .knowledge_bases import init_knowledge_bases

    init_knowledge_bases(settings)


def _migrate_tasks_schema(connection: sqlite3.Connection) -> None:
    for column_name, column_type in OPTIONAL_TASK_COLUMNS.items():
        if column_name in _task_columns(connection):
            continue
        try:
            connection.execute(
                f"ALTER TABLE tasks ADD COLUMN {column_name} {column_type}"
            )
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise

    connection.execute(
        """
        UPDATE tasks
        SET knowledge_base_code = 'general'
        WHERE knowledge_base_code IS NULL OR knowledge_base_code = ''
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET processed_time = completed_at
        WHERE (processed_time IS NULL OR processed_time = '')
          AND completed_at IS NOT NULL
          AND completed_at != ''
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET fastgpt_sync_status = 'pending'
        WHERE fastgpt_sync_status IS NULL OR fastgpt_sync_status = ''
        """
    )
    rows = connection.execute(
        """
        SELECT doc_id, stored_pdf_path, final_md_path, stored_pdf_filename, final_md_filename
        FROM tasks
        """
    ).fetchall()
    for row in rows:
        updates: dict[str, str] = {}
        if (not row["stored_pdf_filename"]) and row["stored_pdf_path"]:
            updates["stored_pdf_filename"] = Path(row["stored_pdf_path"]).name
        if (not row["final_md_filename"]) and row["final_md_path"]:
            updates["final_md_filename"] = Path(row["final_md_path"]).name
        if updates:
            assignments = ", ".join(f"{key} = :{key}" for key in updates)
            updates["doc_id"] = row["doc_id"]
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE doc_id = :doc_id",
                updates,
            )


def mark_incomplete_tasks_as_interrupted(settings: Settings) -> None:
    with closing(_connect(settings)) as connection:
        connection.execute(
            """
            UPDATE tasks
            SET process_status = 'failed',
                completed_at = COALESCE(completed_at, upload_time),
                processed_time = COALESCE(processed_time, completed_at, upload_time),
                error_message = CASE
                    WHEN error_message IS NULL OR error_message = ''
                    THEN 'Task was interrupted because the web service restarted.'
                    ELSE error_message
                END
            WHERE process_status IN ('queued', 'processing')
            """
        )
        connection.commit()


def insert_task(settings: Settings, payload: dict[str, Any]) -> None:
    columns = ", ".join(payload.keys())
    placeholders = ", ".join(f":{key}" for key in payload)
    with closing(_connect(settings)) as connection:
        connection.execute(
            f"INSERT INTO tasks ({columns}) VALUES ({placeholders})",
            payload,
        )
        connection.commit()


def update_task(settings: Settings, doc_id: str, **fields: Any) -> None:
    if not fields:
        return
    assignments = ", ".join(f"{key} = :{key}" for key in fields)
    params = dict(fields)
    params["doc_id"] = doc_id
    with closing(_connect(settings)) as connection:
        connection.execute(
            f"UPDATE tasks SET {assignments} WHERE doc_id = :doc_id",
            params,
        )
        connection.commit()


def get_task(settings: Settings, doc_id: str) -> dict[str, Any] | None:
    with closing(_connect(settings)) as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE doc_id = ?",
            (doc_id,),
        ).fetchone()
    return dict(row) if row else None


def list_tasks(settings: Settings, limit: int = 200) -> list[dict[str, Any]]:
    with closing(_connect(settings)) as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM tasks
            ORDER BY upload_time DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_library_files(
    settings: Settings,
    *,
    knowledge_base_code: str | None = None,
    process_status: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if knowledge_base_code:
        conditions.append("knowledge_base_code = ?")
        params.append(knowledge_base_code)
    if process_status:
        conditions.append("process_status = ?")
        params.append(process_status)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    query = f"""
        SELECT *
        FROM tasks
        {where_clause}
        ORDER BY upload_time DESC
        LIMIT ?
    """
    params.append(limit)

    with closing(_connect(settings)) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def list_fastgpt_sync_candidates(
    settings: Settings,
    *,
    doc_ids: list[str] | None = None,
    sync_status: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    conditions = ["process_status = 'success'"]
    params: list[Any] = []

    if sync_status:
        conditions.append("fastgpt_sync_status = ?")
        params.append(sync_status)
    if doc_ids:
        placeholders = ", ".join("?" for _ in doc_ids)
        conditions.append(f"doc_id IN ({placeholders})")
        params.extend(doc_ids)

    query = f"""
        SELECT *
        FROM tasks
        WHERE {' AND '.join(conditions)}
        ORDER BY upload_time DESC
        LIMIT ?
    """
    params.append(limit)

    with closing(_connect(settings)) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]
