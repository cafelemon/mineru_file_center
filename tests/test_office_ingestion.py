from __future__ import annotations

from dataclasses import replace
import io
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
import zipfile

from fastapi.testclient import TestClient

from webapp import db
from webapp import main as main_module
from webapp.main import app
from webapp.services.document_conversion_service import (
    convert_docx_to_markdown,
    convert_excel_to_markdown,
)


class StubRunner:
    def __init__(self):
        self.doc_ids: list[str] = []

    def submit(self, doc_id: str):
        self.doc_ids.append(doc_id)
        return None

    def shutdown(self) -> None:
        return None


def build_settings(tmp_path: Path):
    base = main_module.settings
    return replace(
        base,
        data_root=tmp_path,
        uploads_dir=tmp_path / "uploads",
        pdf_store_dir=tmp_path / "pdf_store",
        output_dir=tmp_path / "output",
        tasks_dir=tmp_path / "tasks",
        logs_dir=tmp_path / "logs",
        database_path=tmp_path / "app.db",
        bridge_pdf_root=None,
        bridge_manifest_dir=None,
        file_link_enabled=True,
        file_link_secret="test-secret",
        file_link_base_url="",
    )


def make_docx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>员工手册</w:t></w:r></w:p>
    <w:p><w:r><w:t>入职流程说明</w:t></w:r></w:p>
    <w:tbl>
      <w:tr>
        <w:tc><w:p><w:r><w:t>部门</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>联系人</w:t></w:r></w:p></w:tc>
      </w:tr>
      <w:tr>
        <w:tc><w:p><w:r><w:t>质量</w:t></w:r></w:p></w:tc>
        <w:tc><w:p><w:r><w:t>张三</w:t></w:r></w:p></w:tc>
      </w:tr>
    </w:tbl>
  </w:body>
</w:document>""",
        )
    return buffer.getvalue()


def make_xlsx_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        archive.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="人员" sheetId="1" r:id="rId1"/>
    <sheet name="库存" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>""",
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>""",
        )
        archive.writestr(
            "xl/sharedStrings.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>姓名</t></si>
  <si><t>分数</t></si>
  <si><t>张三</t></si>
  <si><t>物料</t></si>
  <si><t>数量</t></si>
  <si><t>手套</t></si>
</sst>""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>
    <row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>98</v></c></row>
  </sheetData>
</worksheet>""",
        )
        archive.writestr(
            "xl/worksheets/sheet2.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c r="A1" t="s"><v>3</v></c><c r="B1" t="s"><v>4</v></c></row>
    <row r="2"><c r="A2" t="s"><v>5</v></c><c r="B2"><v>12</v></c></row>
  </sheetData>
</worksheet>""",
        )
    return buffer.getvalue()


class OfficeIngestionTests(unittest.TestCase):
    def test_docx_conversion_generates_markdown(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        source_path = tmp_path / "demo.docx"
        source_path.write_bytes(make_docx_bytes())

        markdown = convert_docx_to_markdown(source_path)

        self.assertIn("员工手册", markdown)
        self.assertIn("入职流程说明", markdown)
        self.assertIn("| 部门 | 联系人 |", markdown)

    def test_xlsx_conversion_generates_sheet_sections(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        source_path = tmp_path / "demo.xlsx"
        source_path.write_bytes(make_xlsx_bytes())

        markdown = convert_excel_to_markdown(source_path)

        self.assertIn("## 工作表：人员", markdown)
        self.assertIn("| 姓名 | 分数 |", markdown)
        self.assertIn("| 张三 | 98 |", markdown)
        self.assertIn("## 工作表：库存", markdown)

    def test_upload_office_files_creates_generic_source_records(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        runner = StubRunner()

        with patch.object(main_module, "settings", settings):
            with TestClient(app) as client:
                app.state.task_runner = runner
                response = client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)

                response = client.post(
                    "/upload",
                    data={"knowledge_base_code": "general"},
                    files=[
                        (
                            "files",
                            (
                                "员工手册.docx",
                                make_docx_bytes(),
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                            ),
                        ),
                        (
                            "files",
                            (
                                "人员清单.xlsx",
                                make_xlsx_bytes(),
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            ),
                        ),
                        (
                            "files",
                            (
                                "宏表.xlsm",
                                make_xlsx_bytes(),
                                "application/vnd.ms-excel.sheet.macroEnabled.12",
                            ),
                        ),
                    ],
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(runner.doc_ids), 3)
        records = db.list_library_files(settings, knowledge_base_code="general", limit=10)
        by_name = {item["original_filename"]: item for item in records}

        self.assertEqual(by_name["员工手册.docx"]["source_file_ext"], ".docx")
        self.assertEqual(by_name["员工手册.docx"]["processor_type"], "docx_markdown")
        self.assertTrue(by_name["员工手册.docx"]["source_file_path"].endswith(".docx"))
        self.assertEqual(
            by_name["员工手册.docx"]["stored_pdf_path"],
            by_name["员工手册.docx"]["source_file_path"],
        )
        self.assertEqual(by_name["人员清单.xlsx"]["processor_type"], "excel_markdown")
        self.assertEqual(by_name["宏表.xlsm"]["source_file_ext"], ".xlsm")

    def test_zip_upload_accepts_supported_mixed_sources(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        runner = StubRunner()
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            archive.writestr("制度库/人事/员工手册.docx", make_docx_bytes())
            archive.writestr("制度库/财务/人员清单.xlsx", make_xlsx_bytes())
            archive.writestr("制度库/质量/培训材料.pdf", b"%PDF-1.4\n%test")
            archive.writestr("制度库/说明.txt", "skip me")
        archive_buffer.seek(0)

        with patch.object(main_module, "settings", settings):
            with TestClient(app) as client:
                app.state.task_runner = runner
                response = client.post(
                    "/login",
                    data={"username": settings.username, "password": settings.password},
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)
                response = client.post(
                    "/upload",
                    data={"knowledge_base_code": "general"},
                    files=[("files", ("batch.zip", archive_buffer.getvalue(), "application/zip"))],
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(len(runner.doc_ids), 3)
        records = db.list_library_files(settings, knowledge_base_code="general", limit=10)
        self.assertEqual(
            {item["source_file_ext"] for item in records},
            {".pdf", ".docx", ".xlsx"},
        )

    def test_file_link_supports_office_source_file(self):
        tmp_path = Path(self.id().replace(".", "_"))
        if tmp_path.exists():
            shutil.rmtree(tmp_path)
        tmp_path.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: shutil.rmtree(tmp_path, ignore_errors=True))

        settings = build_settings(tmp_path)
        settings.ensure_directories()
        db.init_db(settings)
        task_dir = settings.tasks_dir / "doc-1"
        task_dir.mkdir(parents=True, exist_ok=True)
        source_path = settings.pdf_store_dir / "doc-1.docx"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_bytes = make_docx_bytes()
        source_path.write_bytes(source_bytes)

        db.insert_task(
            settings,
            {
                "doc_id": "doc-1",
                "knowledge_base_code": "general",
                "folder_path": "",
                "relative_source_path": "员工手册.docx",
                "source_archive_name": "",
                "original_filename": "员工手册.docx",
                "source_file_path": str(source_path),
                "source_file_filename": source_path.name,
                "source_file_ext": ".docx",
                "source_mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "processor_type": "docx_markdown",
                "stored_pdf_path": str(source_path),
                "stored_pdf_filename": source_path.name,
                "final_md_path": str(settings.output_dir / "doc-1.md"),
                "final_md_filename": "doc-1.md",
                "upload_time": "2026-01-01T00:00:00+00:00",
                "started_at": None,
                "completed_at": None,
                "processed_time": None,
                "process_status": "success",
                "error_message": "",
                "mineru_task_dir": str(task_dir),
                "log_path": str(task_dir / "task.log"),
                "file_sha256": "abc123",
                "notes": "",
                "file_size_bytes": source_path.stat().st_size,
                "mineru_backend": settings.mineru_backend,
                "mineru_method": settings.mineru_method,
                "fastgpt_sync_status": "pending",
                "fastgpt_sync_error": "",
            },
        )

        with patch.object(main_module, "settings", settings):
            with TestClient(app) as client:
                response = client.get("/api/files/file-link", params={"doc_id": "doc-1"})
                self.assertEqual(response.status_code, 200)
                payload = response.json()
                self.assertEqual(payload["filename"], "员工手册.docx")
                self.assertEqual(payload["file_type"], "docx")
                self.assertEqual(payload["file_url"], payload["pdf_url"])
                self.assertIn("/files/file/open?", payload["file_url"])

                old_response = client.get("/api/files/pdf-link", params={"doc_id": "doc-1"})
                self.assertEqual(old_response.status_code, 200)
                self.assertIn("file_url", old_response.json())

                open_response = client.get(payload["file_url"])
                self.assertEqual(open_response.status_code, 200)
                self.assertIn("attachment", open_response.headers["content-disposition"])
                self.assertEqual(open_response.content, source_bytes)


if __name__ == "__main__":
    unittest.main()
