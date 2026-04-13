from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import Settings
from ..knowledge_bases import get_bridge_app_code


DEFAULT_EXPORTER_NAME = "mineru_file_center.bridge_export"


@dataclass(slots=True)
class BridgeExportResult:
    exported_pdf_path: Path
    item_manifest_path: Path
    aggregate_manifest_path: Path
    app_code: str
    kb_category: str


class BridgeExportService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def is_enabled(self) -> bool:
        return bool(
            self.settings.bridge_export_enabled
            and self.settings.bridge_pdf_root is not None
            and self.settings.bridge_manifest_dir is not None
        )

    def export_task(self, task: dict[str, Any]) -> BridgeExportResult | None:
        if not self.is_enabled():
            return None

        doc_id = str(task["doc_id"])
        kb_category = str(task.get("knowledge_base_code") or "general")
        app_code = get_bridge_app_code(task.get("knowledge_base_code")) or "general_common"
        source_pdf_path = self._resolve_source_pdf_path(task)

        bridge_pdf_root = self.settings.bridge_pdf_root
        manifest_dir = self.settings.bridge_manifest_dir
        if bridge_pdf_root is None or manifest_dir is None:
            raise RuntimeError("Bridge export paths are not configured.")

        exported_pdf_path = bridge_pdf_root / app_code / kb_category / f"{doc_id}.pdf"
        exported_pdf_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_pdf_path, exported_pdf_path)

        item = self._build_manifest_item(
            task=task,
            source_pdf_path=source_pdf_path,
            exported_pdf_path=exported_pdf_path,
            app_code=app_code,
            kb_category=kb_category,
        )
        manifest_dir.mkdir(parents=True, exist_ok=True)
        item_manifest_path = manifest_dir / f"{doc_id}.json"
        aggregate_manifest_path = manifest_dir / "latest_manifest.json"
        self._write_manifest_document(item_manifest_path, [item])
        self._upsert_aggregate_manifest(aggregate_manifest_path, item)
        return BridgeExportResult(
            exported_pdf_path=exported_pdf_path,
            item_manifest_path=item_manifest_path,
            aggregate_manifest_path=aggregate_manifest_path,
            app_code=app_code,
            kb_category=kb_category,
        )

    def _build_manifest_item(
        self,
        *,
        task: dict[str, Any],
        source_pdf_path: Path,
        exported_pdf_path: Path,
        app_code: str,
        kb_category: str,
    ) -> dict[str, Any]:
        markdown_path = self._resolve_markdown_path(task)
        original_filename = str(task.get("original_filename") or exported_pdf_path.name)
        source_name = Path(markdown_path).name if markdown_path else original_filename
        return {
            "doc_id": str(task["doc_id"]),
            "collection_id": None,
            "source_name": source_name,
            "origin_pdf_name": original_filename,
            "pdf_abs_path": str(exported_pdf_path.resolve()),
            "source_pdf_path": str(source_pdf_path.resolve()),
            "markdown_path": markdown_path,
            "kb_category": kb_category,
            "perm_level": 1,
            "app_code": app_code,
            "status": 1 if task.get("process_status") == "success" else 0,
            "sha256": str(task.get("file_sha256") or "").strip() or None,
        }

    def _resolve_source_pdf_path(self, task: dict[str, Any]) -> Path:
        doc_id = str(task["doc_id"])
        candidates: list[Path] = []
        stored_pdf_path = str(task.get("stored_pdf_path") or "").strip()
        stored_pdf_filename = str(task.get("stored_pdf_filename") or "").strip()
        if stored_pdf_path:
            candidates.append(Path(stored_pdf_path).expanduser())
        if stored_pdf_filename:
            candidates.append(self.settings.pdf_store_dir / stored_pdf_filename)
        candidates.append(self.settings.pdf_store_dir / f"{doc_id}.pdf")
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists() and resolved.is_file():
                return resolved
        raise FileNotFoundError(f"Stored PDF does not exist for doc_id={doc_id}")

    def _resolve_markdown_path(self, task: dict[str, Any]) -> str | None:
        doc_id = str(task["doc_id"])
        candidates: list[Path] = []
        final_md_path = str(task.get("final_md_path") or "").strip()
        final_md_filename = str(task.get("final_md_filename") or "").strip()
        if final_md_path:
            candidates.append(Path(final_md_path).expanduser())
        if final_md_filename:
            candidates.append(self.settings.output_dir / final_md_filename)
        candidates.append(self.settings.output_dir / f"{doc_id}.md")
        for candidate in candidates:
            resolved = candidate.resolve()
            if resolved.exists() and resolved.is_file():
                return str(resolved)
        return None

    def _upsert_aggregate_manifest(
        self,
        aggregate_manifest_path: Path,
        item: dict[str, Any],
    ) -> None:
        payload = self._load_manifest_document(aggregate_manifest_path)
        items = payload.setdefault("items", [])
        doc_id = item["doc_id"]
        replaced = False
        for index, existing in enumerate(items):
            if str(existing.get("doc_id")) == doc_id:
                items[index] = item
                replaced = True
                break
        if not replaced:
            items.append(item)
        self._write_manifest_document(aggregate_manifest_path, items)

    def _load_manifest_document(self, manifest_path: Path) -> dict[str, Any]:
        if not manifest_path.exists():
            return {
                "exporter": DEFAULT_EXPORTER_NAME,
                "exported_at": _utc_now(),
                "bridge_pdf_root": str(self.settings.bridge_pdf_root.resolve()) if self.settings.bridge_pdf_root else None,
                "items": [],
            }
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            payload = {"items": payload}
        payload.setdefault("items", [])
        payload["exporter"] = payload.get("exporter") or DEFAULT_EXPORTER_NAME
        payload["bridge_pdf_root"] = payload.get("bridge_pdf_root") or (
            str(self.settings.bridge_pdf_root.resolve()) if self.settings.bridge_pdf_root else None
        )
        return payload

    def _write_manifest_document(
        self,
        manifest_path: Path,
        items: list[dict[str, Any]],
    ) -> None:
        payload = {
            "exporter": DEFAULT_EXPORTER_NAME,
            "exported_at": _utc_now(),
            "bridge_pdf_root": str(self.settings.bridge_pdf_root.resolve()) if self.settings.bridge_pdf_root else None,
            "items": items,
        }
        _write_json_atomic(manifest_path, payload)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
