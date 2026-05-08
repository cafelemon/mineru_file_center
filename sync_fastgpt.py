from __future__ import annotations

import argparse
import json

from webapp import db
from webapp.config import get_settings
from webapp.services.fastgpt_sync_service import FastGPTSyncError
from webapp.services.mineru_service import MineruTaskRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync successful MinerU markdown files into FastGPT datasets."
    )
    parser.add_argument(
        "--doc-id",
        action="append",
        default=[],
        help="Only sync the specified doc_id. Can be used multiple times.",
    )
    parser.add_argument(
        "--failed-only",
        action="store_true",
        help="Only retry tasks whose FastGPT sync status is failed.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum number of tasks to process when --doc-id is omitted.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()
    db.init_db(settings)
    runner = MineruTaskRunner(settings)
    sync_status = "failed" if args.failed_only else None

    if args.doc_id:
        tasks = [
            task
            for doc_id in args.doc_id
            if (task := db.get_task(settings, doc_id)) is not None
        ]
    else:
        tasks = db.list_fastgpt_sync_candidates(
            settings,
            sync_status=sync_status,
            limit=max(1, args.limit),
        )

    success = 0
    failed = 0
    errors: list[str] = []
    try:
        for task in tasks:
            doc_id = str(task["doc_id"])
            try:
                runner.sync_task_to_fastgpt(doc_id)
            except FastGPTSyncError as exc:
                failed += 1
                errors.append(f"{doc_id}: {exc}")
                continue
            success += 1
    finally:
        runner.shutdown()

    print(
        json.dumps(
            {
                "total": len(tasks),
                "success": success,
                "failed": failed,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
