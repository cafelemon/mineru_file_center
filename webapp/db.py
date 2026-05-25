from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any
from datetime import datetime, timezone

from .config import Settings


TASK_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    doc_id TEXT PRIMARY KEY,
    knowledge_base_code TEXT,
    folder_path TEXT,
    relative_source_path TEXT,
    source_archive_name TEXT,
    original_filename TEXT NOT NULL,
    stored_pdf_path TEXT NOT NULL,
    stored_pdf_filename TEXT,
    source_file_path TEXT,
    source_file_filename TEXT,
    source_file_ext TEXT,
    source_mime_type TEXT,
    processor_type TEXT,
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
    "folder_path": "TEXT",
    "relative_source_path": "TEXT",
    "source_archive_name": "TEXT",
    "stored_pdf_filename": "TEXT",
    "source_file_path": "TEXT",
    "source_file_filename": "TEXT",
    "source_file_ext": "TEXT",
    "source_mime_type": "TEXT",
    "processor_type": "TEXT",
    "final_md_filename": "TEXT",
    "processed_time": "TEXT",
    "fastgpt_dataset_id": "TEXT",
    "fastgpt_dataset_name": "TEXT",
    "fastgpt_collection_id": "TEXT",
    "fastgpt_sync_status": "TEXT",
    "fastgpt_synced_at": "TEXT",
    "fastgpt_sync_error": "TEXT",
    "source_storage_backend": "TEXT",
    "source_remote_path": "TEXT",
    "source_remote_url": "TEXT",
}

KNOWLEDGE_FOLDER_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_folders (
    knowledge_base_code TEXT NOT NULL,
    folder_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (knowledge_base_code, folder_path)
)
"""


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
        _init_knowledge_folders(connection)
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
        SET folder_path = ''
        WHERE folder_path IS NULL
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET relative_source_path = original_filename
        WHERE relative_source_path IS NULL OR relative_source_path = ''
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET source_archive_name = ''
        WHERE source_archive_name IS NULL
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET source_storage_backend = 'local'
        WHERE source_storage_backend IS NULL OR source_storage_backend = ''
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET source_remote_path = ''
        WHERE source_remote_path IS NULL
        """
    )
    connection.execute(
        """
        UPDATE tasks
        SET source_remote_url = ''
        WHERE source_remote_url IS NULL
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
        SELECT doc_id,
               stored_pdf_path,
               final_md_path,
               stored_pdf_filename,
               final_md_filename,
               source_file_path,
               source_file_filename,
               source_file_ext,
               source_mime_type,
               processor_type
        FROM tasks
        """
    ).fetchall()
    for row in rows:
        updates: dict[str, str] = {}
        if (not row["stored_pdf_filename"]) and row["stored_pdf_path"]:
            updates["stored_pdf_filename"] = Path(row["stored_pdf_path"]).name
        if (not row["final_md_filename"]) and row["final_md_path"]:
            updates["final_md_filename"] = Path(row["final_md_path"]).name
        if (not row["source_file_path"]) and row["stored_pdf_path"]:
            updates["source_file_path"] = row["stored_pdf_path"]
        source_filename = row["source_file_filename"] or row["stored_pdf_filename"]
        if (not row["source_file_filename"]) and source_filename:
            updates["source_file_filename"] = source_filename
        source_ext = str(row["source_file_ext"] or "").strip()
        if not source_ext:
            source_ext = Path(str(source_filename or row["stored_pdf_path"] or "")).suffix.lower()
            if source_ext:
                updates["source_file_ext"] = source_ext
        if not row["source_mime_type"]:
            updates["source_mime_type"] = _mime_type_for_extension(source_ext or ".pdf")
        if not row["processor_type"]:
            updates["processor_type"] = _processor_type_for_extension(source_ext or ".pdf")
        if updates:
            assignments = ", ".join(f"{key} = :{key}" for key in updates)
            updates["doc_id"] = row["doc_id"]
            connection.execute(
                f"UPDATE tasks SET {assignments} WHERE doc_id = :doc_id",
                updates,
            )


def _init_knowledge_folders(connection: sqlite3.Connection) -> None:
    connection.execute(KNOWLEDGE_FOLDER_TABLE_SQL)
    _backfill_knowledge_folders(connection)


def _backfill_knowledge_folders(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT knowledge_base_code, folder_path
        FROM tasks
        WHERE folder_path IS NOT NULL AND folder_path != ''
        """
    ).fetchall()
    now = _utc_now()
    for row in rows:
        knowledge_base_code = str(row["knowledge_base_code"] or "general").strip() or "general"
        for folder_path in _iter_folder_ancestors(str(row["folder_path"] or "")):
            connection.execute(
                """
                INSERT OR IGNORE INTO knowledge_folders (
                    knowledge_base_code, folder_path, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (knowledge_base_code, folder_path, now, now),
            )


def _mime_type_for_extension(source_ext: str) -> str:
    normalized = str(source_ext or "").strip().lower()
    return {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    }.get(normalized, "application/octet-stream")


def _processor_type_for_extension(source_ext: str) -> str:
    normalized = str(source_ext or "").strip().lower()
    if normalized == ".pdf":
        return "mineru_pdf"
    if normalized == ".docx":
        return "docx_markdown"
    if normalized in {".xlsx", ".xlsm"}:
        return "excel_markdown"
    return "unknown"


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
        _ensure_folder_ancestors(
            connection,
            str(payload.get("knowledge_base_code") or "general"),
            str(payload.get("folder_path") or ""),
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


def delete_task(settings: Settings, doc_id: str) -> None:
    with closing(_connect(settings)) as connection:
        connection.execute("DELETE FROM tasks WHERE doc_id = ?", (doc_id,))
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
    folder_path: str | None = None,
    process_status: str | None = None,
    search_query: str | None = None,
    sort_by: str | None = None,
    sort_dir: str | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    conditions, params = _library_file_conditions(
        knowledge_base_code=knowledge_base_code,
        folder_path=folder_path,
        process_status=process_status,
        search_query=search_query,
    )
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    order_clause = _library_file_order_clause(sort_by=sort_by, sort_dir=sort_dir)
    query = f"""
        SELECT *
        FROM tasks
        {where_clause}
        ORDER BY {order_clause}
        LIMIT ?
        OFFSET ?
    """
    params.extend([limit, max(0, offset)])

    with closing(_connect(settings)) as connection:
        rows = connection.execute(query, params).fetchall()
    return [dict(row) for row in rows]


def count_library_files(
    settings: Settings,
    *,
    knowledge_base_code: str | None = None,
    folder_path: str | None = None,
    process_status: str | list[str] | tuple[str, ...] | None = None,
    search_query: str | None = None,
) -> int:
    conditions, params = _library_file_conditions(
        knowledge_base_code=knowledge_base_code,
        folder_path=folder_path,
        process_status=process_status,
        search_query=search_query,
    )
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with closing(_connect(settings)) as connection:
        row = connection.execute(
            f"SELECT COUNT(*) FROM tasks {where_clause}",
            params,
        ).fetchone()
    return int(row[0] if row else 0)


def _library_file_conditions(
    *,
    knowledge_base_code: str | None = None,
    folder_path: str | None = None,
    process_status: str | list[str] | tuple[str, ...] | None = None,
    search_query: str | None = None,
) -> tuple[list[str], list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []

    if knowledge_base_code:
        conditions.append("knowledge_base_code = ?")
        params.append(knowledge_base_code)
    normalized_folder_path = (folder_path or "").strip().strip("/")
    if normalized_folder_path:
        conditions.append("(folder_path = ? OR folder_path LIKE ?)")
        params.extend([normalized_folder_path, f"{normalized_folder_path}/%"])
    if process_status:
        if isinstance(process_status, (list, tuple)):
            statuses = [str(item).strip() for item in process_status if str(item).strip()]
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                conditions.append(f"process_status IN ({placeholders})")
                params.extend(statuses)
        else:
            conditions.append("process_status = ?")
            params.append(process_status)
    normalized_search_query = str(search_query or "").strip()
    if normalized_search_query:
        pattern = f"%{normalized_search_query}%"
        conditions.append(
            """
            (
                original_filename LIKE ?
                OR folder_path LIKE ?
                OR relative_source_path LIKE ?
                OR final_md_filename LIKE ?
            )
            """
        )
        params.extend([pattern, pattern, pattern, pattern])
    return conditions, params


def _library_file_order_clause(*, sort_by: str | None = None, sort_dir: str | None = None) -> str:
    normalized_sort_by = str(sort_by or "").strip()
    normalized_sort_dir = str(sort_dir or "").strip().lower()
    direction = "ASC" if normalized_sort_dir == "asc" else "DESC"

    if normalized_sort_by == "name":
        return (
            f"LOWER(COALESCE(original_filename, '')) {direction}, "
            f"upload_time {direction}, doc_id {direction}"
        )
    if normalized_sort_by == "processed_time":
        return (
            f"COALESCE(NULLIF(processed_time, ''), NULLIF(completed_at, ''), upload_time) {direction}, "
            f"upload_time {direction}, doc_id {direction}"
        )
    return "upload_time DESC, doc_id DESC"


def list_knowledge_folders(settings: Settings, knowledge_base_code: str) -> list[dict[str, Any]]:
    with closing(_connect(settings)) as connection:
        rows = connection.execute(
            """
            SELECT knowledge_base_code, folder_path, created_at, updated_at
            FROM knowledge_folders
            WHERE knowledge_base_code = ?
            ORDER BY folder_path ASC
            """,
            (knowledge_base_code,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_folder_file_counts(settings: Settings, knowledge_base_code: str) -> dict[str, int]:
    with closing(_connect(settings)) as connection:
        rows = connection.execute(
            """
            SELECT folder_path, COUNT(*) AS file_count
            FROM tasks
            WHERE knowledge_base_code = ?
              AND folder_path IS NOT NULL
              AND folder_path != ''
            GROUP BY folder_path
            """,
            (knowledge_base_code,),
        ).fetchall()

    counts: dict[str, int] = {}
    for row in rows:
        file_count = int(row["file_count"] or 0)
        for folder_path in _iter_folder_ancestors(str(row["folder_path"] or "")):
            counts[folder_path] = counts.get(folder_path, 0) + file_count
    return counts


def folder_exists(settings: Settings, knowledge_base_code: str, folder_path: str) -> bool:
    normalized_folder_path = _normalize_folder_path(folder_path)
    if not normalized_folder_path:
        return True
    with closing(_connect(settings)) as connection:
        row = connection.execute(
            """
            SELECT 1
            FROM knowledge_folders
            WHERE knowledge_base_code = ? AND folder_path = ?
            """,
            (knowledge_base_code, normalized_folder_path),
        ).fetchone()
    return row is not None


def create_knowledge_folder(
    settings: Settings,
    *,
    knowledge_base_code: str,
    folder_path: str,
) -> None:
    normalized_folder_path = _normalize_folder_path(folder_path)
    if not normalized_folder_path:
        return
    with closing(_connect(settings)) as connection:
        _ensure_folder_ancestors(connection, knowledge_base_code, normalized_folder_path)
        connection.commit()


def delete_knowledge_folder(
    settings: Settings,
    *,
    knowledge_base_code: str,
    folder_path: str,
) -> None:
    normalized_folder_path = _normalize_folder_path(folder_path)
    if not normalized_folder_path:
        return
    with closing(_connect(settings)) as connection:
        connection.execute(
            """
            DELETE FROM knowledge_folders
            WHERE knowledge_base_code = ? AND folder_path = ?
            """,
            (knowledge_base_code, normalized_folder_path),
        )
        connection.commit()


def rename_knowledge_folder(
    settings: Settings,
    *,
    knowledge_base_code: str,
    folder_path: str,
    new_folder_name: str,
) -> str:
    normalized_folder_path = _normalize_folder_path(folder_path)
    normalized_new_name = _normalize_folder_path(new_folder_name)
    if (
        not normalized_folder_path
        or not normalized_new_name
        or "/" in normalized_new_name
        or normalized_new_name == ".."
    ):
        return ""

    parent = str(PurePosixPath(normalized_folder_path).parent)
    parent_path = "" if parent in {"", "."} else _normalize_folder_path(parent)
    target_folder_path = (
        f"{parent_path}/{normalized_new_name}" if parent_path else normalized_new_name
    )
    if target_folder_path == normalized_folder_path:
        return target_folder_path

    with closing(_connect(settings)) as connection:
        now = _utc_now()
        _ensure_folder_ancestors(connection, knowledge_base_code, parent_path)
        target_exists = connection.execute(
            """
            SELECT 1
            FROM knowledge_folders
            WHERE knowledge_base_code = ? AND folder_path = ?
            """,
            (knowledge_base_code, target_folder_path),
        ).fetchone()
        if target_exists:
            return ""
        folder_rows = connection.execute(
            """
            SELECT folder_path, created_at
            FROM knowledge_folders
            WHERE knowledge_base_code = ?
              AND (folder_path = ? OR folder_path LIKE ?)
            ORDER BY LENGTH(folder_path) ASC
            """,
            (knowledge_base_code, normalized_folder_path, f"{normalized_folder_path}/%"),
        ).fetchall()
        if not folder_rows:
            return ""
        task_rows = connection.execute(
            """
            SELECT doc_id, folder_path, original_filename, relative_source_path
            FROM tasks
            WHERE knowledge_base_code = ?
              AND (folder_path = ? OR folder_path LIKE ?)
            """,
            (knowledge_base_code, normalized_folder_path, f"{normalized_folder_path}/%"),
        ).fetchall()

        connection.execute(
            """
            DELETE FROM knowledge_folders
            WHERE knowledge_base_code = ?
              AND (folder_path = ? OR folder_path LIKE ?)
            """,
            (knowledge_base_code, normalized_folder_path, f"{normalized_folder_path}/%"),
        )
        for row in folder_rows:
            old_path = _normalize_folder_path(row["folder_path"])
            new_path = _replace_folder_prefix(old_path, normalized_folder_path, target_folder_path)
            connection.execute(
                """
                INSERT OR REPLACE INTO knowledge_folders (
                    knowledge_base_code, folder_path, created_at, updated_at
                )
                VALUES (?, ?, ?, ?)
                """,
                (knowledge_base_code, new_path, row["created_at"] or now, now),
            )

        for row in task_rows:
            new_task_folder = _replace_folder_prefix(
                _normalize_folder_path(row["folder_path"]),
                normalized_folder_path,
                target_folder_path,
            )
            original_filename = str(row["original_filename"] or "").strip()
            if not original_filename:
                original_filename = PurePosixPath(
                    _normalize_folder_path(row["relative_source_path"])
                ).name
            relative_source_path = (
                f"{new_task_folder}/{original_filename}" if new_task_folder else original_filename
            )
            connection.execute(
                """
                UPDATE tasks
                SET folder_path = ?,
                    relative_source_path = ?
                WHERE doc_id = ? AND knowledge_base_code = ?
                """,
                (new_task_folder, relative_source_path, row["doc_id"], knowledge_base_code),
            )

        connection.commit()
    return target_folder_path


def count_child_folders(
    settings: Settings,
    *,
    knowledge_base_code: str,
    folder_path: str,
) -> int:
    normalized_folder_path = _normalize_folder_path(folder_path)
    if not normalized_folder_path:
        return 0
    with closing(_connect(settings)) as connection:
        row = connection.execute(
            """
            SELECT COUNT(*)
            FROM knowledge_folders
            WHERE knowledge_base_code = ?
              AND folder_path LIKE ?
            """,
            (knowledge_base_code, f"{normalized_folder_path}/%"),
        ).fetchone()
    return int(row[0] if row else 0)


def move_tasks_to_folder(
    settings: Settings,
    *,
    knowledge_base_code: str,
    doc_ids: list[str],
    target_folder_path: str,
) -> int:
    normalized_target_folder = _normalize_folder_path(target_folder_path)
    normalized_doc_ids: list[str] = []
    seen_doc_ids: set[str] = set()
    for doc_id in doc_ids:
        normalized_doc_id = str(doc_id).strip()
        if not normalized_doc_id or normalized_doc_id in seen_doc_ids:
            continue
        normalized_doc_ids.append(normalized_doc_id)
        seen_doc_ids.add(normalized_doc_id)
    if not normalized_doc_ids:
        return 0

    with closing(_connect(settings)) as connection:
        if normalized_target_folder:
            _ensure_folder_ancestors(connection, knowledge_base_code, normalized_target_folder)
        placeholders = ", ".join("?" for _ in normalized_doc_ids)
        rows = connection.execute(
            f"""
            SELECT doc_id, original_filename
            FROM tasks
            WHERE knowledge_base_code = ?
              AND doc_id IN ({placeholders})
            """,
            [knowledge_base_code, *normalized_doc_ids],
        ).fetchall()
        if len(rows) != len(normalized_doc_ids):
            return 0
        for row in rows:
            original_filename = str(row["original_filename"] or "").strip()
            relative_source_path = (
                f"{normalized_target_folder}/{original_filename}"
                if normalized_target_folder
                else original_filename
            )
            connection.execute(
                """
                UPDATE tasks
                SET folder_path = ?,
                    relative_source_path = ?
                WHERE doc_id = ? AND knowledge_base_code = ?
                """,
                (
                    normalized_target_folder,
                    relative_source_path,
                    row["doc_id"],
                    knowledge_base_code,
                ),
            )
        connection.commit()
    return len(rows)


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


def _ensure_folder_ancestors(
    connection: sqlite3.Connection,
    knowledge_base_code: str,
    folder_path: str,
) -> None:
    normalized_knowledge_base_code = str(knowledge_base_code or "general").strip() or "general"
    now = _utc_now()
    for ancestor in _iter_folder_ancestors(folder_path):
        connection.execute(
            """
            INSERT OR IGNORE INTO knowledge_folders (
                knowledge_base_code, folder_path, created_at, updated_at
            )
            VALUES (?, ?, ?, ?)
            """,
            (normalized_knowledge_base_code, ancestor, now, now),
        )


def _iter_folder_ancestors(folder_path: str) -> list[str]:
    normalized_folder_path = _normalize_folder_path(folder_path)
    if not normalized_folder_path:
        return []
    ancestors: list[str] = []
    current_parts: list[str] = []
    for part in normalized_folder_path.split("/"):
        current_parts.append(part)
        ancestors.append("/".join(current_parts))
    return ancestors


def _replace_folder_prefix(folder_path: str, old_prefix: str, new_prefix: str) -> str:
    normalized_path = _normalize_folder_path(folder_path)
    normalized_old_prefix = _normalize_folder_path(old_prefix)
    normalized_new_prefix = _normalize_folder_path(new_prefix)
    if normalized_path == normalized_old_prefix:
        return normalized_new_prefix
    suffix = normalized_path[len(normalized_old_prefix) :].lstrip("/")
    return f"{normalized_new_prefix}/{suffix}" if suffix else normalized_new_prefix


def _normalize_folder_path(folder_path: str) -> str:
    text = str(folder_path or "").strip().replace("\\", "/")
    return "/".join(part for part in text.split("/") if part and part != ".").strip("/")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
