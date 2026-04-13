from __future__ import annotations

import argparse
import json

from webapp import db
from webapp.config import get_settings
from webapp.services.bridge_export_service import BridgeExportService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export successful MinerU tasks into Bridge-compatible PDF copies and manifest files."
    )
    parser.add_argument(
        "--doc-id",
        action="append",
        default=[],
        help="Export only the specified doc_id. Can be used multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="When --doc-id is omitted, export up to this many successful tasks.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    exporter = BridgeExportService(settings)
    if not exporter.is_enabled():
        raise SystemExit(
            "Bridge export is not enabled. Please set [bridge_export].enabled=true and configure pdf_root."
        )

    if args.doc_id:
        tasks = []
        for doc_id in args.doc_id:
            task = db.get_task(settings, doc_id)
            if task is not None:
                tasks.append(task)
    else:
        tasks = db.list_library_files(
            settings,
            process_status="success",
            limit=max(1, args.limit),
        )

    exported = 0
    skipped = 0
    errors: list[str] = []
    aggregate_manifest_path = None
    for task in tasks:
        if task.get("process_status") != "success":
            skipped += 1
            continue
        try:
            result = exporter.export_task(task)
        except Exception as exc:
            errors.append(f"{task.get('doc_id')}: {exc}")
            continue
        if result is None:
            skipped += 1
            continue
        exported += 1
        aggregate_manifest_path = str(result.aggregate_manifest_path)

    print(
        json.dumps(
            {
                "total": len(tasks),
                "exported": exported,
                "skipped": skipped,
                "failed": len(errors),
                "aggregate_manifest_path": aggregate_manifest_path,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
