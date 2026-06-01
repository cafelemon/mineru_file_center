from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from io import BytesIO
import re
from typing import Any
from xml.sax.saxutils import escape, quoteattr
from zipfile import ZIP_DEFLATED, ZipFile


EXPORT_HEADERS = [
    "doc_id",
    "所属知识库",
    "目录",
    "原始文件名",
    "相对路径",
    "Markdown 文件名",
    "上传时间",
    "处理时间",
    "处理状态",
    "FastGPT/Bridge 同步状态",
    "FastGPT collectionId",
    "来源压缩包",
    "存储模式",
    "远端路径/本地路径",
]


def build_file_inventory_workbook(
    records: list[dict[str, Any]],
    *,
    knowledge_bases: list[dict[str, Any]],
    selected_knowledge_base_code: str = "",
) -> bytes:
    sheets = build_file_inventory_sheets(
        records,
        knowledge_bases=knowledge_bases,
        selected_knowledge_base_code=selected_knowledge_base_code,
    )
    try:
        return _build_workbook_with_openpyxl(sheets)
    except ModuleNotFoundError:
        return _build_minimal_xlsx(sheets)


def build_file_inventory_sheets(
    records: list[dict[str, Any]],
    *,
    knowledge_bases: list[dict[str, Any]],
    selected_knowledge_base_code: str = "",
) -> list[tuple[str, list[dict[str, Any]]]]:
    sheets: list[tuple[str, list[dict[str, Any]]]] = [("总表", records)]
    normalized_selected_code = str(selected_knowledge_base_code or "").strip()
    if normalized_selected_code:
        root_records: list[dict[str, Any]] = []
        folder_groups: dict[str, list[dict[str, Any]]] = {}
        for record in records:
            folder_path = _normalize_folder_path(record.get("folder_path"))
            if not folder_path:
                root_records.append(record)
                continue
            first_part = folder_path.split("/", 1)[0]
            folder_groups.setdefault(first_part, []).append(record)
        if root_records:
            sheets.append(("知识库根目录", root_records))
        for folder_name in sorted(folder_groups):
            sheets.append((folder_name, folder_groups[folder_name]))
        return sheets

    knowledge_base_names = {
        str(item.get("code") or ""): str(item.get("display_name") or item.get("name") or "")
        for item in knowledge_bases
    }
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        code = str(record.get("knowledge_base_code") or "").strip()
        grouped.setdefault(code, []).append(record)
    for code, name in knowledge_base_names.items():
        group_records = grouped.pop(code, [])
        if group_records:
            sheets.append((name or code or "未命名知识库", group_records))
    for code in sorted(grouped):
        if grouped[code]:
            sheets.append((knowledge_base_names.get(code) or code or "未命名知识库", grouped[code]))
    return sheets


def file_inventory_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"file_inventory_{stamp}.xlsx"


def _build_workbook_with_openpyxl(sheets: list[tuple[str, list[dict[str, Any]]]]) -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    used_names: set[str] = set()
    for title, records in sheets:
        sheet_name = _unique_sheet_name(title, used_names)
        worksheet = workbook.create_sheet(title=sheet_name)
        worksheet.append(EXPORT_HEADERS)
        for record in records:
            worksheet.append(_record_to_row(record))
        worksheet.freeze_panes = "A2"
        for column_cells in worksheet.columns:
            max_length = max(len(str(cell.value or "")) for cell in column_cells)
            worksheet.column_dimensions[column_cells[0].column_letter].width = min(
                max(max_length + 2, 10),
                42,
            )
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _build_minimal_xlsx(sheets: list[tuple[str, list[dict[str, Any]]]]) -> bytes:
    used_names: set[str] = set()
    normalized_sheets = [
        (_unique_sheet_name(title, used_names), [EXPORT_HEADERS, *[_record_to_row(record) for record in records]])
        for title, records in sheets
    ]
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", _content_types_xml(len(normalized_sheets)))
        package.writestr("_rels/.rels", _root_rels_xml())
        package.writestr("xl/workbook.xml", _workbook_xml([name for name, _ in normalized_sheets]))
        package.writestr("xl/_rels/workbook.xml.rels", _workbook_rels_xml(len(normalized_sheets)))
        package.writestr("docProps/app.xml", _app_xml(len(normalized_sheets)))
        package.writestr("docProps/core.xml", _core_xml())
        for index, (_, rows) in enumerate(normalized_sheets, start=1):
            package.writestr(f"xl/worksheets/sheet{index}.xml", _worksheet_xml(rows))
    return output.getvalue()


def _record_to_row(record: dict[str, Any]) -> list[str]:
    storage_path = str(record.get("source_remote_path") or record.get("source_file_path") or "")
    return [
        str(record.get("doc_id") or ""),
        str(record.get("knowledge_base_name") or ""),
        str(record.get("folder_path_display") or record.get("folder_path") or "知识库根目录"),
        str(record.get("original_filename") or ""),
        str(record.get("relative_source_path") or ""),
        str(record.get("final_md_filename") or ""),
        str(record.get("upload_time") or ""),
        str(record.get("processed_time") or ""),
        str(record.get("status_label") or record.get("process_status") or ""),
        str(record.get("fastgpt_sync_status_label") or record.get("fastgpt_sync_status") or ""),
        str(record.get("fastgpt_collection_id") or ""),
        str(record.get("source_archive_name") or ""),
        str(record.get("source_storage_backend") or ""),
        storage_path,
    ]


def _unique_sheet_name(raw_name: str, used_names: set[str]) -> str:
    base = _sanitize_sheet_name(raw_name)
    candidate = base
    index = 2
    while candidate in used_names:
        suffix = f" ({index})"
        candidate = f"{base[: 31 - len(suffix)]}{suffix}"
        index += 1
    used_names.add(candidate)
    return candidate


def _sanitize_sheet_name(raw_name: str) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "_", str(raw_name or "").strip()) or "Sheet"
    return name[:31] or "Sheet"


def _normalize_folder_path(raw_value: object) -> str:
    text = str(raw_value or "").strip().replace("\\", "/")
    return "/".join(part for part in text.split("/") if part and part != ".").strip("/")


def _worksheet_xml(rows: Iterable[list[str]]) -> str:
    row_xml: list[str] = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for col_index, value in enumerate(row, start=1):
            ref = f"{_column_name(col_index)}{row_index}"
            text = escape(str(value or ""))
            cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def _column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _content_types_xml(sheet_count: int) -> str:
    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/docProps/core.xml" '
        'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
        '<Override PartName="/docProps/app.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
        f"{sheet_overrides}</Types>"
    )


def _root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
        'Target="docProps/core.xml"/>'
        '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
        'Target="docProps/app.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name={quoteattr(name)} sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets></workbook>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    relationships = "".join(
        f'<Relationship Id="rId{index}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{relationships}</Relationships>"
    )


def _app_xml(sheet_count: int) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
        'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
        f"<Application>MinerU File Center</Application><HeadingPairs><vt:vector size=\"2\" baseType=\"variant\">"
        '<vt:variant><vt:lpstr>Worksheets</vt:lpstr></vt:variant>'
        f'<vt:variant><vt:i4>{sheet_count}</vt:i4></vt:variant>'
        "</vt:vector></HeadingPairs></Properties>"
    )


def _core_xml() -> str:
    timestamp = datetime.now(timezone.utc).isoformat()
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        "<dc:creator>MinerU File Center</dc:creator>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{timestamp}</dcterms:modified>'
        "</cp:coreProperties>"
    )
