from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
import unittest

from webapp import db
from webapp.config import get_settings


def build_settings(tmp_path: Path):
    base = get_settings()
    return replace(
        base,
        data_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        pdf_store_dir=tmp_path / "pdf_store",
        output_dir=tmp_path / "output",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
        database_path=tmp_path / "app.db",
    )


def insert_record(
    settings,
    *,
    doc_id: str,
    folder_path: str,
    original_filename: str = "demo.pdf",
    knowledge_base_code: str = "general",
):
    db.insert_task(
        settings,
        {
            "doc_id": doc_id,
            "knowledge_base_code": knowledge_base_code,
            "folder_path": folder_path,
            "relative_source_path": f"{folder_path + '/' if folder_path else ''}{original_filename}",
            "source_archive_name": "batch.zip" if folder_path else "",
            "original_filename": original_filename,
            "stored_pdf_path": str(settings.pdf_store_dir / f"{doc_id}.pdf"),
            "stored_pdf_filename": f"{doc_id}.pdf",
            "final_md_path": str(settings.output_dir / f"{doc_id}.md"),
            "final_md_filename": f"{doc_id}.md",
            "upload_time": f"2026-01-01T00:00:{doc_id[-1]}+00:00",
            "started_at": None,
            "completed_at": None,
            "processed_time": None,
            "process_status": "success",
            "error_message": "",
            "mineru_task_dir": str(settings.tasks_dir / doc_id),
            "log_path": str(settings.tasks_dir / doc_id / "task.log"),
            "file_sha256": "",
            "notes": "",
            "file_size_bytes": 128,
            "mineru_backend": settings.mineru_backend,
            "mineru_method": settings.mineru_method,
            "fastgpt_collection_id": "collection-keep",
            "fastgpt_sync_status": "synced",
            "fastgpt_sync_error": "",
        },
    )


class FolderManagementDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_path = Path(self.id().replace(".", "_"))
        if self.tmp_path.exists():
            shutil.rmtree(self.tmp_path)
        self.tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(self.tmp_path, ignore_errors=True))
        self.settings = build_settings(self.tmp_path)
        self.settings.ensure_directories()
        db.init_db(self.settings)

    def test_insert_task_backfills_folder_and_ancestors(self):
        insert_record(self.settings, doc_id="doc-1", folder_path="制度库/人事/入职")

        folders = {
            item["folder_path"]
            for item in db.list_knowledge_folders(self.settings, "general")
        }

        self.assertIn("制度库", folders)
        self.assertIn("制度库/人事", folders)
        self.assertIn("制度库/人事/入职", folders)

    def test_folder_file_counts_include_descendant_files(self):
        insert_record(self.settings, doc_id="doc-1", folder_path="制度库/人事")
        insert_record(self.settings, doc_id="doc-2", folder_path="制度库/人事/入职")
        insert_record(self.settings, doc_id="doc-3", folder_path="制度库/质量")

        counts = db.list_folder_file_counts(self.settings, "general")

        self.assertEqual(counts["制度库"], 3)
        self.assertEqual(counts["制度库/人事"], 2)
        self.assertEqual(counts["制度库/人事/入职"], 1)
        self.assertEqual(counts["制度库/质量"], 1)

    def test_move_tasks_to_folder_updates_only_file_center_directory_fields(self):
        insert_record(self.settings, doc_id="doc-2", folder_path="旧目录", original_filename="员工手册.pdf")
        db.create_knowledge_folder(
            self.settings,
            knowledge_base_code="general",
            folder_path="新目录/子目录",
        )

        moved_count = db.move_tasks_to_folder(
            self.settings,
            knowledge_base_code="general",
            doc_ids=["doc-2"],
            target_folder_path="新目录/子目录",
        )
        task = db.get_task(self.settings, "doc-2")

        self.assertEqual(moved_count, 1)
        self.assertEqual(task["folder_path"], "新目录/子目录")
        self.assertEqual(task["relative_source_path"], "新目录/子目录/员工手册.pdf")
        self.assertEqual(task["final_md_filename"], "doc-2.md")
        self.assertEqual(task["fastgpt_collection_id"], "collection-keep")

    def test_move_tasks_to_folder_rejects_cross_knowledge_base_selection(self):
        insert_record(self.settings, doc_id="doc-general", folder_path="")
        insert_record(
            self.settings,
            doc_id="doc-other",
            folder_path="",
            knowledge_base_code="executive",
        )

        moved_count = db.move_tasks_to_folder(
            self.settings,
            knowledge_base_code="general",
            doc_ids=["doc-general", "doc-other"],
            target_folder_path="目标目录",
        )

        self.assertEqual(moved_count, 0)
        self.assertEqual(db.get_task(self.settings, "doc-general")["folder_path"], "")
        self.assertEqual(db.get_task(self.settings, "doc-other")["folder_path"], "")

    def test_list_library_files_supports_pagination_and_count(self):
        for index in range(25):
            insert_record(self.settings, doc_id=f"doc-{index}", folder_path="")

        first_page = db.list_library_files(self.settings, limit=20, offset=0)
        second_page = db.list_library_files(self.settings, limit=20, offset=20)

        self.assertEqual(db.count_library_files(self.settings), 25)
        self.assertEqual(len(first_page), 20)
        self.assertEqual(len(second_page), 5)

    def test_list_library_files_supports_search_query(self):
        insert_record(
            self.settings,
            doc_id="doc-manual",
            folder_path="制度库/人事",
            original_filename="员工手册.pdf",
        )
        insert_record(
            self.settings,
            doc_id="doc-quality",
            folder_path="质量体系",
            original_filename="检验规范.pdf",
        )

        filename_matches = db.list_library_files(self.settings, search_query="员工")
        folder_matches = db.list_library_files(self.settings, search_query="制度库")
        md_matches = db.list_library_files(self.settings, search_query="doc-quality.md")

        self.assertEqual([item["doc_id"] for item in filename_matches], ["doc-manual"])
        self.assertEqual(db.count_library_files(self.settings, search_query="制度库"), 1)
        self.assertEqual([item["doc_id"] for item in folder_matches], ["doc-manual"])
        self.assertEqual([item["doc_id"] for item in md_matches], ["doc-quality"])
        self.assertEqual(
            db.count_library_files(
                self.settings,
                knowledge_base_code="general",
                folder_path="制度库",
                process_status="success",
                search_query="员工",
            ),
            1,
        )

    def test_rename_knowledge_folder_updates_descendants_and_tasks(self):
        insert_record(
            self.settings,
            doc_id="doc-1",
            folder_path="制度库/人事",
            original_filename="员工手册.pdf",
        )
        insert_record(
            self.settings,
            doc_id="doc-2",
            folder_path="制度库/人事/入职",
            original_filename="入职流程.pdf",
        )
        insert_record(
            self.settings,
            doc_id="doc-3",
            folder_path="制度库/财务",
            original_filename="报销制度.pdf",
        )

        new_path = db.rename_knowledge_folder(
            self.settings,
            knowledge_base_code="general",
            folder_path="制度库/人事",
            new_folder_name="人力资源",
        )
        folders = {
            item["folder_path"]
            for item in db.list_knowledge_folders(self.settings, "general")
        }
        task_1 = db.get_task(self.settings, "doc-1")
        task_2 = db.get_task(self.settings, "doc-2")
        task_3 = db.get_task(self.settings, "doc-3")

        self.assertEqual(new_path, "制度库/人力资源")
        self.assertIn("制度库/人力资源", folders)
        self.assertIn("制度库/人力资源/入职", folders)
        self.assertNotIn("制度库/人事", folders)
        self.assertEqual(task_1["folder_path"], "制度库/人力资源")
        self.assertEqual(task_1["relative_source_path"], "制度库/人力资源/员工手册.pdf")
        self.assertEqual(task_2["folder_path"], "制度库/人力资源/入职")
        self.assertEqual(task_2["relative_source_path"], "制度库/人力资源/入职/入职流程.pdf")
        self.assertEqual(task_2["final_md_filename"], "doc-2.md")
        self.assertEqual(task_2["fastgpt_collection_id"], "collection-keep")
        self.assertEqual(task_3["folder_path"], "制度库/财务")

    def test_rename_knowledge_folder_rejects_invalid_or_duplicate_target(self):
        insert_record(self.settings, doc_id="doc-1", folder_path="制度库/人事")
        db.create_knowledge_folder(
            self.settings,
            knowledge_base_code="general",
            folder_path="制度库/质量",
        )

        duplicate = db.rename_knowledge_folder(
            self.settings,
            knowledge_base_code="general",
            folder_path="制度库/人事",
            new_folder_name="质量",
        )
        invalid = db.rename_knowledge_folder(
            self.settings,
            knowledge_base_code="general",
            folder_path="",
            new_folder_name="新名称",
        )

        self.assertEqual(duplicate, "")
        self.assertEqual(invalid, "")
        self.assertEqual(db.get_task(self.settings, "doc-1")["folder_path"], "制度库/人事")

    def test_folder_delete_guards_can_detect_children_and_files(self):
        insert_record(self.settings, doc_id="doc-3", folder_path="制度库/人事")
        db.create_knowledge_folder(
            self.settings,
            knowledge_base_code="general",
            folder_path="制度库/质量/体系",
        )

        self.assertEqual(
            db.count_library_files(
                self.settings,
                knowledge_base_code="general",
                folder_path="制度库/人事",
            ),
            1,
        )
        self.assertEqual(
            db.count_child_folders(
                self.settings,
                knowledge_base_code="general",
                folder_path="制度库/质量",
            ),
            1,
        )
