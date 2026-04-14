from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import secrets
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from .config import Settings, get_settings
from .knowledge_bases import (
    InvalidKnowledgeBaseNameError,
    KnowledgeBaseExistsError,
    KnowledgeBaseInUseError,
    KnowledgeBaseNotFoundError,
    create_knowledge_base,
    delete_knowledge_base,
    get_default_knowledge_base_code,
    get_knowledge_base,
    knowledge_base_exists,
    list_knowledge_bases,
)
from .services.mineru_service import MineruTaskRunner
from .services.fastgpt_sync_service import FastGPTSyncError
from .services.file_link_service import (
    FileLinkDisabledError,
    FileLinkSecretMissingError,
    FileLinkService,
    FileLinkServiceError,
    FileLinkValidationError,
)


settings = get_settings()
templates = Jinja2Templates(directory=str(settings.project_root / "webapp" / "templates"))
logger = logging.getLogger("mineru_webapp")
file_link_service = FileLinkService(settings)
SESSION_COOKIE_NAME = "mineru_session"
SESSION_MAX_AGE_SECONDS = 12 * 60 * 60
STATUS_LABELS = {
    "queued": "排队中",
    "processing": "处理中",
    "success": "处理成功",
    "failed": "处理失败",
}
FASTGPT_SYNC_LABELS = {
    "pending": "待同步",
    "synced": "已同步",
    "failed": "同步失败",
}

app = FastAPI(title="MinerU LAN Validator", docs_url=None, redoc_url=None)
app.mount(
    "/static",
    StaticFiles(directory=str(settings.project_root / "webapp" / "static")),
    name="static",
)


def configure_logging(app_settings: Settings) -> None:
    if logging.getLogger().handlers:
        return

    app_settings.logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(
        app_settings.logs_dir / "webapp.log",
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, stream_handler],
    )


@app.on_event("startup")
def startup_event() -> None:
    settings.ensure_directories()
    configure_logging(settings)
    db.init_db(settings)
    db.mark_incomplete_tasks_as_interrupted(settings)
    app.state.task_runner = MineruTaskRunner(settings)
    logger.info("MinerU web app started with config: %s", settings.config_path)


@app.on_event("shutdown")
def shutdown_event() -> None:
    runner: MineruTaskRunner | None = getattr(app.state, "task_runner", None)
    if runner is not None:
        runner.shutdown()
    logger.info("MinerU web app stopped")


def is_authenticated(request: Request) -> bool:
    return get_current_user(request) is not None


def get_current_user(request: Request) -> str | None:
    raw_cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_cookie:
        return None
    try:
        decoded = base64.urlsafe_b64decode(raw_cookie.encode("utf-8")).decode("utf-8")
        username, expires_at, signature = decoded.split("|", 2)
        expires_at_int = int(expires_at)
    except Exception:
        return None

    payload = f"{username}|{expires_at}"
    expected_signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        return None
    if expires_at_int < int(time.time()):
        return None
    return username


def build_session_cookie(username: str) -> str:
    expires_at = str(int(time.time()) + SESSION_MAX_AGE_SECONDS)
    payload = f"{username}|{expires_at}"
    signature = hmac.new(
        settings.session_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return base64.urlsafe_b64encode(
        f"{payload}|{signature}".encode("utf-8")
    ).decode("utf-8")


def require_login(request: Request) -> None:
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")


def render(
    request: Request,
    template_name: str,
    context: dict | None,
    status_code: int = 200,
) -> HTMLResponse:
    base_context = {
        "request": request,
        "current_user": get_current_user(request),
        "is_authenticated": is_authenticated(request),
        "knowledge_bases": list_knowledge_bases(settings),
        "nav_section": None,
        "message": request.query_params.get("message", ""),
        "error": request.query_params.get("error", ""),
    }
    if context:
        base_context.update(context)
    return templates.TemplateResponse(
        request=request,
        name=template_name,
        context=base_context,
        status_code=status_code,
    )


def enrich_record(record: dict | None) -> dict | None:
    if record is None:
        return None

    item = dict(record)
    knowledge_base = get_knowledge_base(settings, item.get("knowledge_base_code"))
    item["knowledge_base_code"] = knowledge_base.code
    item["knowledge_base_name"] = knowledge_base.display_name
    item["folder_path"] = normalize_folder_path(item.get("folder_path"))
    item["folder_path_display"] = item["folder_path"] or "知识库根目录"
    item["relative_source_path"] = normalize_relative_source_path(
        item.get("relative_source_path") or item.get("original_filename") or ""
    )
    item["source_archive_name"] = item.get("source_archive_name") or "-"
    item["stored_pdf_filename"] = item.get("stored_pdf_filename") or Path(
        item["stored_pdf_path"]
    ).name

    final_md_path = item.get("final_md_path") or ""
    item["final_md_filename"] = item.get("final_md_filename") or (
        Path(final_md_path).name if final_md_path else "-"
    )
    item["processed_time"] = item.get("processed_time") or item.get("completed_at") or "-"
    item["status_label"] = STATUS_LABELS.get(
        item.get("process_status"),
        item.get("process_status") or "-",
    )
    raw_fastgpt_sync_status = str(item.get("fastgpt_sync_status") or "pending").strip()
    item["fastgpt_sync_status"] = raw_fastgpt_sync_status or "pending"
    item["fastgpt_sync_status_label"] = FASTGPT_SYNC_LABELS.get(
        item["fastgpt_sync_status"],
        item["fastgpt_sync_status"] or "-",
    )
    item["fastgpt_dataset_name"] = item.get("fastgpt_dataset_name") or "-"
    item["fastgpt_collection_id"] = item.get("fastgpt_collection_id") or "-"
    item["fastgpt_synced_at"] = item.get("fastgpt_synced_at") or "-"
    item["fastgpt_sync_error"] = item.get("fastgpt_sync_error") or "-"
    item["can_retry_fastgpt_sync"] = (
        item.get("process_status") == "success" and item["fastgpt_sync_status"] == "failed"
    )
    return item


def enrich_records(records: list[dict]) -> list[dict]:
    return [enrich_record(record) for record in records if record is not None]


def build_summary_cards(records: list[dict]) -> list[dict[str, object]]:
    total_count = len(records)
    success_count = sum(1 for item in records if item["process_status"] == "success")
    processing_count = sum(
        1 for item in records if item["process_status"] in {"queued", "processing"}
    )
    failed_count = sum(1 for item in records if item["process_status"] == "failed")
    return [
        {"label": "文件总数", "value": total_count, "tone": "neutral"},
        {"label": "已完成转换", "value": success_count, "tone": "success"},
        {"label": "处理中", "value": processing_count, "tone": "processing"},
        {"label": "异常文件", "value": failed_count, "tone": "failed"},
    ]


def normalize_folder_path(raw_value: object) -> str:
    text = str(raw_value or "").strip().replace("\\", "/")
    if not text:
        return ""
    normalized = "/".join(part for part in text.split("/") if part and part != ".")
    return normalized.strip("/")


def normalize_relative_source_path(raw_value: object) -> str:
    text = str(raw_value or "").strip().replace("\\", "/")
    return "/".join(part for part in text.split("/") if part and part != ".")


def folder_path_from_relative(relative_source_path: str) -> str:
    relative_path = normalize_relative_source_path(relative_source_path)
    if not relative_path:
        return ""
    parent = str(PurePosixPath(relative_path).parent)
    return "" if parent in {"", "."} else normalize_folder_path(parent)


def build_folder_tree(
    records: list[dict],
    *,
    knowledge_base_code: str,
    selected_folder_path: str,
    selected_process_status: str,
) -> list[dict[str, object]]:
    nodes: dict[str, dict[str, object]] = {}

    for record in records:
        folder_path = normalize_folder_path(record.get("folder_path"))
        if not folder_path:
            continue
        parent_lookup = nodes
        current_path = ""
        for part in folder_path.split("/"):
            current_path = part if not current_path else f"{current_path}/{part}"
            node = parent_lookup.setdefault(
                current_path,
                {
                    "name": part,
                    "path": current_path,
                    "count": 0,
                    "children": {},
                },
            )
            node["count"] = int(node["count"]) + 1
            parent_lookup = node["children"]  # type: ignore[assignment]

    def finalize(children: dict[str, dict[str, object]]) -> list[dict[str, object]]:
        items = sorted(
            children.values(),
            key=lambda item: (
                normalize_folder_path(item["path"]).count("/"),
                str(item["name"]).lower(),
            ),
        )
        finalized: list[dict[str, object]] = []
        for item in items:
            folder_path = str(item["path"])
            params = {"knowledge_base_code": knowledge_base_code, "folder_path": folder_path}
            if selected_process_status:
                params["process_status"] = selected_process_status
            finalized.append(
                {
                    "name": item["name"],
                    "path": folder_path,
                    "count": item["count"],
                    "is_active": folder_path == selected_folder_path,
                    "href": f"/files?{urlencode(params)}",
                    "children": finalize(item["children"]),  # type: ignore[arg-type]
                }
            )
        return finalized

    return finalize(nodes)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)

    recent_tasks = enrich_records(db.list_tasks(settings, limit=20))
    all_tasks = enrich_records(db.list_tasks(settings, limit=500))
    has_active_tasks = any(
        task["process_status"] in {"queued", "processing"} for task in recent_tasks
    )
    return render(
        request,
        "dashboard.html",
        {
            "title": "内部知识库文件管理系统",
            "nav_section": "upload",
            "tasks": recent_tasks,
            "summary_cards": build_summary_cards(all_tasks),
            "has_active_tasks": has_active_tasks,
            "max_upload_size_mb": settings.max_upload_size_mb,
            "selected_knowledge_base_code": get_default_knowledge_base_code(settings),
        },
    )


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request) -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)
    return render(request, "login.html", {})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    if (
        secrets.compare_digest(username, settings.username)
        and secrets.compare_digest(password, settings.password)
    ):
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=build_session_cookie(username),
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            samesite="lax",
        )
        return response
    return RedirectResponse(
        url="/login?error=%E7%99%BB%E5%BD%95%E5%A4%B1%E8%B4%A5%EF%BC%8C%E8%AF%B7%E6%A3%80%E6%9F%A5%E8%B4%A6%E5%8F%B7%E5%92%8C%E5%AF%86%E7%A0%81",
        status_code=303,
    )


@app.get("/logout")
def logout(request: Request):
    del request
    response = RedirectResponse(
        url="/login?message=%E5%B7%B2%E9%80%80%E5%87%BA%E7%99%BB%E5%BD%95",
        status_code=303,
    )
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


@app.post("/upload")
async def upload_files(
    request: Request,
    knowledge_base_code: str = Form(...),
    files: list[UploadFile] = File(...),
    _: None = Depends(require_login),
):
    del request
    queued_doc_ids: list[str] = []
    errors: list[str] = []

    selected_knowledge_base_code = knowledge_base_code.strip()
    if not knowledge_base_exists(settings, selected_knowledge_base_code):
        return RedirectResponse(
            url=f"/?{urlencode({'error': '请选择有效的所属知识库'})}",
            status_code=303,
        )
    knowledge_base = get_knowledge_base(settings, selected_knowledge_base_code)
    runner: MineruTaskRunner = app.state.task_runner

    for upload in files:
        original_name = Path(upload.filename or "").name
        if not original_name:
            errors.append("存在未命名文件，已跳过。")
            continue
        suffix = Path(original_name).suffix.lower()
        try:
            if suffix == ".pdf":
                doc_id = await archive_uploaded_pdf(
                    upload=upload,
                    knowledge_base_code=knowledge_base.code,
                    original_name=original_name,
                    relative_source_path=original_name,
                    source_archive_name="",
                    runner=runner,
                )
                queued_doc_ids.append(doc_id)
                continue
            if suffix == ".zip":
                zip_doc_ids, zip_errors = await archive_uploaded_zip(
                    upload=upload,
                    knowledge_base_code=knowledge_base.code,
                    archive_name=original_name,
                    runner=runner,
                )
                queued_doc_ids.extend(zip_doc_ids)
                errors.extend(zip_errors)
                continue
            errors.append(f"{original_name}: 仅支持 PDF 或 ZIP。")
        except Exception as exc:
            logger.exception("Upload failed for %s", original_name)
            errors.append(f"{original_name}: {exc}")

    if queued_doc_ids:
        preview_doc_ids = ", ".join(queued_doc_ids[:5])
        message = (
            f"文件已归档到{knowledge_base.display_name}，共加入 {len(queued_doc_ids)} 个处理任务"
        )
        if preview_doc_ids:
            message = f"{message}（示例：{preview_doc_ids}）"
        if errors:
            message = f"{message}；部分文件失败，请看页面提示。"
        error_text = " | ".join(errors)
        return RedirectResponse(
            url=f"/files?{urlencode({'knowledge_base_code': knowledge_base.code, 'message': message, 'error': error_text})}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/?{urlencode({'error': ' | '.join(errors) or '没有可处理的 PDF 文件'})}",
        status_code=303,
    )


@app.get("/tasks", response_class=HTMLResponse)
def task_list(request: Request, _: None = Depends(require_login)) -> HTMLResponse:
    tasks = enrich_records(db.list_tasks(settings))
    has_active_tasks = any(
        task["process_status"] in {"queued", "processing"} for task in tasks
    )
    return render(
        request,
        "tasks.html",
        {
            "title": "任务列表",
            "nav_section": "tasks",
            "tasks": tasks,
            "summary_cards": build_summary_cards(tasks),
            "has_active_tasks": has_active_tasks,
        },
    )


@app.get("/tasks/{doc_id}", response_class=HTMLResponse)
def task_detail(
    doc_id: str,
    request: Request,
    _: None = Depends(require_login),
) -> HTMLResponse:
    task = enrich_record(db.get_task(settings, doc_id))
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return render(
        request,
        "task_detail.html",
        {
            "title": "任务详情",
            "nav_section": "tasks",
            "task": task,
        },
    )


@app.get("/files", response_class=HTMLResponse)
def file_list(
    request: Request,
    knowledge_base_code: str = "",
    folder_path: str = "",
    process_status: str = "",
    _: None = Depends(require_login),
) -> HTMLResponse:
    selected_knowledge_base_code = knowledge_base_code.strip()
    if selected_knowledge_base_code and not knowledge_base_exists(
        settings,
        selected_knowledge_base_code,
    ):
        selected_knowledge_base_code = ""
    selected_folder_path = normalize_folder_path(folder_path if selected_knowledge_base_code else "")
    selected_status = process_status.strip()
    folder_records = (
        enrich_records(
            db.list_library_files(
                settings,
                knowledge_base_code=selected_knowledge_base_code or None,
                limit=5000,
            )
        )
        if selected_knowledge_base_code
        else []
    )
    available_folder_paths = {
        normalize_folder_path(item.get("folder_path")) for item in folder_records if item is not None
    }
    if selected_folder_path and selected_folder_path not in available_folder_paths:
        selected_folder_path = ""

    files = enrich_records(
        db.list_library_files(
            settings,
            knowledge_base_code=selected_knowledge_base_code or None,
            folder_path=selected_folder_path or None,
            process_status=selected_status or None,
        )
    )
    has_active_tasks = any(
        item["process_status"] in {"queued", "processing"} for item in files
    )
    knowledge_bases = list_knowledge_bases(settings)
    selected_knowledge_base = next(
        (
            item
            for item in knowledge_bases
            if item["code"] == selected_knowledge_base_code
        ),
        None,
    )
    folder_tree = (
        build_folder_tree(
            folder_records,
            knowledge_base_code=selected_knowledge_base_code,
            selected_folder_path=selected_folder_path,
            selected_process_status=selected_status,
        )
        if selected_knowledge_base_code
        else []
    )
    return render(
        request,
        "files.html",
        {
            "title": "知识库文件管理",
            "nav_section": "files",
            "files": files,
            "summary_cards": build_summary_cards(files),
            "has_active_tasks": has_active_tasks,
            "selected_knowledge_base_code": selected_knowledge_base_code,
            "selected_knowledge_base": selected_knowledge_base,
            "selected_folder_path": selected_folder_path,
            "selected_folder_path_display": selected_folder_path or "知识库根目录",
            "selected_process_status": selected_status,
            "folder_tree": folder_tree,
        },
    )


@app.post("/knowledge-bases")
def create_knowledge_base_route(
    display_name: str = Form(...),
    _: None = Depends(require_login),
):
    try:
        knowledge_base = create_knowledge_base(settings, display_name)
    except (InvalidKnowledgeBaseNameError, KnowledgeBaseExistsError) as exc:
        return RedirectResponse(
            url=f"/files?{urlencode({'error': str(exc)})}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/files?{urlencode({'knowledge_base_code': knowledge_base.code, 'message': f'已新建知识库：{knowledge_base.display_name}'})}",
        status_code=303,
    )


@app.post("/knowledge-bases/{code}/delete")
def delete_knowledge_base_route(
    code: str,
    password: str = Form(...),
    _: None = Depends(require_login),
):
    redirect_params = {"knowledge_base_code": code}
    if not secrets.compare_digest(password, settings.password):
        redirect_params["error"] = "删除密码不正确"
        return RedirectResponse(
            url=f"/files?{urlencode(redirect_params)}",
            status_code=303,
        )

    try:
        knowledge_base = get_knowledge_base(settings, code)
        delete_knowledge_base(settings, code)
    except (KnowledgeBaseNotFoundError, KnowledgeBaseInUseError) as exc:
        redirect_params["error"] = str(exc)
        return RedirectResponse(
            url=f"/files?{urlencode(redirect_params)}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/files?{urlencode({'message': f'已删除知识库：{knowledge_base.display_name}'})}",
        status_code=303,
    )


@app.get("/files/{doc_id}", response_class=HTMLResponse)
def file_detail(
    doc_id: str,
    request: Request,
    _: None = Depends(require_login),
) -> HTMLResponse:
    file_record = enrich_record(db.get_task(settings, doc_id))
    if file_record is None:
        raise HTTPException(status_code=404, detail="File not found")
    pdf_link = build_pdf_link_payload(doc_id, require_file=False)
    return render(
        request,
        "file_detail.html",
        {
            "title": "知识库文件详情",
            "nav_section": "files",
            "file": file_record,
            "pdf_link": pdf_link,
            "file_link_enabled": settings.file_link_enabled,
            "file_link_error": "" if pdf_link else build_pdf_link_error_hint(doc_id),
        },
    )


@app.post("/files/{doc_id}/retry-fastgpt-sync")
def retry_fastgpt_sync(
    doc_id: str,
    request: Request,
    _: None = Depends(require_login),
):
    del request
    runner: MineruTaskRunner = app.state.task_runner
    try:
        runner.sync_task_to_fastgpt(doc_id)
    except FastGPTSyncError as exc:
        return RedirectResponse(
            url=f"/files/{doc_id}?{urlencode({'error': str(exc)})}",
            status_code=303,
        )
    except Exception as exc:
        logger.exception("FastGPT sync retry failed for doc_id=%s", doc_id)
        return RedirectResponse(
            url=f"/files/{doc_id}?{urlencode({'error': f'重试失败：{exc}'})}",
            status_code=303,
        )

    return RedirectResponse(
        url=f"/files/{doc_id}?{urlencode({'message': 'FastGPT 同步已重试'})}",
        status_code=303,
    )


def _load_record_or_404(doc_id: str) -> dict:
    task = db.get_task(settings, doc_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return task


def resolve_pdf_path(task: dict) -> Path | None:
    doc_id = str(task["doc_id"])
    candidates: list[Path] = []
    stored_pdf_path = str(task.get("stored_pdf_path") or "").strip()
    stored_pdf_filename = str(task.get("stored_pdf_filename") or "").strip()

    if stored_pdf_path:
        candidates.append(Path(stored_pdf_path).expanduser())
    if stored_pdf_filename:
        candidates.append(settings.pdf_store_dir / stored_pdf_filename)
    candidates.append(settings.pdf_store_dir / f"{doc_id}.pdf")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.exists() and resolved.is_file() and resolved.suffix.lower() == ".pdf":
            return resolved
    return None


def build_pdf_link_payload(doc_id: str, *, require_file: bool = True) -> dict | None:
    task = db.get_task(settings, doc_id)
    if task is None:
        if require_file:
            logger.info("PDF link generation failed reason=doc_not_found doc_id=%s", doc_id)
        return None

    pdf_path = resolve_pdf_path(task)
    if pdf_path is None:
        if require_file:
            logger.info("PDF link generation failed reason=file_missing doc_id=%s", doc_id)
        return None

    try:
        result = file_link_service.generate_pdf_url(doc_id)
    except FileLinkServiceError as exc:
        if require_file:
            logger.warning(
                "PDF link generation failed reason=%s doc_id=%s",
                exc.__class__.__name__,
                doc_id,
            )
        return None

    logger.info("PDF link generated doc_id=%s expires_at=%s", doc_id, result.expires_at)
    return {
        "doc_id": result.doc_id,
        "pdf_url": result.pdf_url,
        "expires_at": result.expires_at,
        "expires_in": result.expires_in,
    }


def build_pdf_link_error_hint(doc_id: str) -> str:
    if not settings.file_link_enabled:
        return "原始文件受控访问链接能力当前未启用。"
    if not settings.file_link_secret:
        return "原始文件受控访问链接未配置签名密钥。"
    task = db.get_task(settings, doc_id)
    if task is None:
        return "未找到对应文件记录。"
    if resolve_pdf_path(task) is None:
        return "原始 PDF 文件暂不可用。"
    return "暂时无法生成原始文件受控访问链接。"


@app.get("/api/files/pdf-link")
def api_pdf_link(
    doc_id: str = Query(..., alias="doc_id"),
) -> dict:
    payload = build_pdf_link_payload(doc_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=build_pdf_link_error_hint(doc_id))
    return payload


@app.get("/files/pdf/open")
def open_signed_pdf(
    doc_id: str | None = Query(default=None, alias="docId"),
    exp: str | None = Query(default=None),
    sig: str | None = Query(default=None),
):
    if not doc_id or not exp or not sig:
        logger.info("PDF open failed reason=missing_parameters doc_id=%s", doc_id or "-")
        raise HTTPException(status_code=400, detail="Missing required parameters")

    try:
        file_link_service.verify_pdf_url(doc_id, exp, sig)
    except FileLinkDisabledError as exc:
        logger.info("PDF open failed reason=disabled doc_id=%s", doc_id)
        raise HTTPException(status_code=503, detail="File link is disabled") from exc
    except FileLinkSecretMissingError as exc:
        logger.warning("PDF open failed reason=secret_missing doc_id=%s", doc_id)
        raise HTTPException(status_code=500, detail="File link secret is not configured") from exc
    except FileLinkValidationError as exc:
        status_code = 410 if exc.reason == "expired" else 403
        logger.info("PDF open failed reason=%s doc_id=%s", exc.reason, doc_id)
        raise HTTPException(status_code=status_code, detail=exc.reason) from exc

    task = db.get_task(settings, doc_id)
    if task is None:
        logger.info("PDF open failed reason=doc_not_found doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="File record not found")

    pdf_path = resolve_pdf_path(task)
    if pdf_path is None:
        logger.info("PDF open failed reason=file_missing doc_id=%s", doc_id)
        raise HTTPException(status_code=404, detail="PDF file not found")

    logger.info("PDF open success doc_id=%s", doc_id)
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=task.get("original_filename") or pdf_path.name,
        content_disposition_type="inline",
    )


@app.get("/tasks/{doc_id}/download/pdf")
@app.get("/files/{doc_id}/download/pdf")
def download_pdf(
    doc_id: str,
    request: Request,
    _: None = Depends(require_login),
):
    del request
    task = _load_record_or_404(doc_id)
    pdf_path = resolve_pdf_path(task)
    if pdf_path is None:
        raise HTTPException(status_code=404, detail="PDF not found")
    return FileResponse(pdf_path, media_type="application/pdf", filename=pdf_path.name)


@app.get("/tasks/{doc_id}/download/md")
@app.get("/files/{doc_id}/download/md")
def download_md(
    doc_id: str,
    request: Request,
    _: None = Depends(require_login),
):
    del request
    task = _load_record_or_404(doc_id)
    final_md_path = task.get("final_md_path")
    if not final_md_path:
        raise HTTPException(status_code=404, detail="Markdown not ready")
    md_path = Path(final_md_path)
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Markdown not ready")
    return FileResponse(md_path, media_type="text/markdown", filename=md_path.name)


@app.get("/tasks/{doc_id}/download/log")
def download_log(
    doc_id: str,
    request: Request,
    _: None = Depends(require_login),
):
    del request
    task = db.get_task(settings, doc_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    log_path = Path(task["log_path"])
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Task log not found")
    return FileResponse(log_path, media_type="text/plain", filename=log_path.name)


def build_task_paths(doc_id: str) -> dict[str, Path]:
    task_dir = settings.tasks_dir / doc_id
    return {
        "task_dir": task_dir,
        "raw_output_dir": task_dir / "raw_output",
        "temp_upload_path": settings.uploads_dir / f"{doc_id}.uploading",
        "stored_pdf_path": settings.pdf_store_dir / f"{doc_id}.pdf",
        "final_md_path": settings.output_dir / f"{doc_id}.md",
        "log_path": task_dir / "task.log",
    }


def insert_queued_task(
    *,
    doc_id: str,
    knowledge_base_code: str,
    original_name: str,
    relative_source_path: str,
    source_archive_name: str,
    stored_pdf_path: Path,
    final_md_path: Path,
    log_path: Path,
    task_dir: Path,
    file_sha256: str,
    file_size: int,
) -> None:
    db.insert_task(
        settings,
        {
            "doc_id": doc_id,
            "knowledge_base_code": knowledge_base_code,
            "folder_path": folder_path_from_relative(relative_source_path),
            "relative_source_path": normalize_relative_source_path(relative_source_path) or original_name,
            "source_archive_name": source_archive_name,
            "original_filename": original_name,
            "stored_pdf_path": str(stored_pdf_path),
            "stored_pdf_filename": stored_pdf_path.name,
            "final_md_path": str(final_md_path),
            "final_md_filename": final_md_path.name,
            "upload_time": utc_now(),
            "started_at": None,
            "completed_at": None,
            "processed_time": None,
            "process_status": "queued",
            "error_message": "",
            "mineru_task_dir": str(task_dir),
            "log_path": str(log_path),
            "file_sha256": file_sha256,
            "notes": "",
            "file_size_bytes": file_size,
            "mineru_backend": settings.mineru_backend,
            "mineru_method": settings.mineru_method,
            "fastgpt_sync_status": "pending",
            "fastgpt_sync_error": "",
        },
    )


async def archive_uploaded_pdf(
    *,
    upload: UploadFile,
    knowledge_base_code: str,
    original_name: str,
    relative_source_path: str,
    source_archive_name: str,
    runner: MineruTaskRunner,
) -> str:
    doc_id = generate_doc_id()
    task_paths = build_task_paths(doc_id)
    task_paths["task_dir"].mkdir(parents=True, exist_ok=True)
    task_paths["raw_output_dir"].mkdir(parents=True, exist_ok=True)

    try:
        file_sha256, file_size = await save_pdf_upload(
            upload,
            task_paths["temp_upload_path"],
            task_paths["stored_pdf_path"],
            settings.max_upload_size_bytes,
        )
        insert_queued_task(
            doc_id=doc_id,
            knowledge_base_code=knowledge_base_code,
            original_name=original_name,
            relative_source_path=relative_source_path,
            source_archive_name=source_archive_name,
            stored_pdf_path=task_paths["stored_pdf_path"],
            final_md_path=task_paths["final_md_path"],
            log_path=task_paths["log_path"],
            task_dir=task_paths["task_dir"],
            file_sha256=file_sha256,
            file_size=file_size,
        )
    except Exception:
        cleanup_paths(
            task_paths["temp_upload_path"],
            task_paths["stored_pdf_path"],
            task_paths["task_dir"],
        )
        raise

    runner.submit(doc_id)
    logger.info(
        "Accepted upload %s as doc_id=%s, knowledge_base=%s, folder=%s",
        relative_source_path,
        doc_id,
        knowledge_base_code,
        folder_path_from_relative(relative_source_path) or "/",
    )
    return doc_id


async def archive_uploaded_zip(
    *,
    upload: UploadFile,
    knowledge_base_code: str,
    archive_name: str,
    runner: MineruTaskRunner,
) -> tuple[list[str], list[str]]:
    work_dir = settings.uploads_dir / "_zip_imports" / generate_doc_id()
    archive_path = work_dir / archive_name
    queued_doc_ids: list[str] = []
    errors: list[str] = []

    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        await save_uploaded_file(upload, archive_path)
        try:
            with zipfile.ZipFile(archive_path) as archive:
                pdf_found = False
                for member in archive.infolist():
                    normalized_path = normalize_archive_member_path(member.filename)
                    if normalized_path is None:
                        if should_skip_archive_member(member.filename):
                            continue
                        errors.append(f"{archive_name}: 包含非法路径，已跳过 {member.filename}")
                        continue
                    if member.is_dir():
                        continue
                    if Path(normalized_path).suffix.lower() != ".pdf":
                        continue
                    pdf_found = True
                    original_name = Path(normalized_path).name
                    try:
                        with archive.open(member) as source_handle:
                            doc_id = archive_pdf_stream(
                                source_handle=source_handle,
                                knowledge_base_code=knowledge_base_code,
                                original_name=original_name,
                                relative_source_path=normalized_path,
                                source_archive_name=archive_name,
                                runner=runner,
                            )
                    except Exception as exc:
                        logger.exception(
                            "ZIP import failed for %s entry %s",
                            archive_name,
                            normalized_path,
                        )
                        errors.append(f"{archive_name}/{normalized_path}: {exc}")
                        continue
                    queued_doc_ids.append(doc_id)
                if not pdf_found:
                    errors.append(f"{archive_name}: ZIP 内没有可处理的 PDF 文件。")
        except zipfile.BadZipFile as exc:
            raise ValueError("ZIP 文件无效或已损坏。") from exc
    finally:
        await upload.close()
        cleanup_paths(work_dir)

    return queued_doc_ids, errors


async def save_uploaded_file(upload: UploadFile, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        await upload.seek(0)
        with destination.open("wb") as output_handle:
            shutil.copyfileobj(upload.file, output_handle)
    finally:
        try:
            await upload.seek(0)
        except Exception:
            return


def archive_pdf_stream(
    *,
    source_handle,
    knowledge_base_code: str,
    original_name: str,
    relative_source_path: str,
    source_archive_name: str,
    runner: MineruTaskRunner,
) -> str:
    doc_id = generate_doc_id()
    task_paths = build_task_paths(doc_id)
    task_paths["task_dir"].mkdir(parents=True, exist_ok=True)
    task_paths["raw_output_dir"].mkdir(parents=True, exist_ok=True)

    try:
        file_sha256, file_size = store_pdf_stream(
            source_handle,
            task_paths["temp_upload_path"],
            task_paths["stored_pdf_path"],
            settings.max_upload_size_bytes,
        )
        insert_queued_task(
            doc_id=doc_id,
            knowledge_base_code=knowledge_base_code,
            original_name=original_name,
            relative_source_path=relative_source_path,
            source_archive_name=source_archive_name,
            stored_pdf_path=task_paths["stored_pdf_path"],
            final_md_path=task_paths["final_md_path"],
            log_path=task_paths["log_path"],
            task_dir=task_paths["task_dir"],
            file_sha256=file_sha256,
            file_size=file_size,
        )
    except Exception:
        cleanup_paths(
            task_paths["temp_upload_path"],
            task_paths["stored_pdf_path"],
            task_paths["task_dir"],
        )
        raise

    runner.submit(doc_id)
    logger.info(
        "Accepted archive member %s as doc_id=%s, knowledge_base=%s, archive=%s",
        relative_source_path,
        doc_id,
        knowledge_base_code,
        source_archive_name,
    )
    return doc_id


def normalize_archive_member_path(member_name: str) -> str | None:
    raw_name = (member_name or "").strip().replace("\\", "/")
    if not raw_name or raw_name.endswith("/"):
        return None
    if raw_name.startswith("/"):
        return None
    path = PurePosixPath(raw_name)
    if any(part in {"", ".", ".."} for part in path.parts):
        return None
    if any(part == "__MACOSX" for part in path.parts):
        return None
    if path.parts and path.parts[0].endswith(":"):
        return None
    return normalize_relative_source_path(str(path))


def should_skip_archive_member(member_name: str) -> bool:
    raw_name = (member_name or "").strip().replace("\\", "/")
    if not raw_name:
        return True
    return "__MACOSX/" in raw_name or raw_name.endswith("/")


def store_pdf_stream(
    source_handle,
    temp_path: Path,
    stored_pdf_path: Path,
    max_size_bytes: int,
) -> tuple[str, int]:
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    stored_pdf_path.parent.mkdir(parents=True, exist_ok=True)

    sha256 = hashlib.sha256()
    file_size = 0
    first_chunk = True

    try:
        with temp_path.open("wb") as output_handle:
            while True:
                chunk = source_handle.read(1024 * 1024)
                if not chunk:
                    break
                if first_chunk:
                    first_chunk = False
                    if not chunk.startswith(b"%PDF"):
                        raise ValueError("文件内容不是有效的 PDF。")
                file_size += len(chunk)
                if file_size > max_size_bytes:
                    raise ValueError(
                        f"文件超过大小限制，当前限制为 {settings.max_upload_size_mb} MB。"
                    )
                sha256.update(chunk)
                output_handle.write(chunk)
        if file_size == 0:
            raise ValueError("上传文件为空。")
        os.replace(temp_path, stored_pdf_path)
        return sha256.hexdigest(), file_size
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


async def save_pdf_upload(
    upload: UploadFile,
    temp_path: Path,
    stored_pdf_path: Path,
    max_size_bytes: int,
) -> tuple[str, int]:
    try:
        await upload.seek(0)
        return store_pdf_stream(
            upload.file,
            temp_path,
            stored_pdf_path,
            max_size_bytes,
        )
    finally:
        await upload.close()


def cleanup_paths(*paths: Path) -> None:
    for path in paths:
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            continue
        path.unlink(missing_ok=True)


def generate_doc_id() -> str:
    return f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{secrets.token_hex(4)}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
