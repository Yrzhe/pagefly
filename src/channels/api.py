"""REST API — FastAPI interface for PageFly."""

import asyncio
import hmac
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, Depends
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.shared.config import (
    API_MAX_UPLOAD_MB,
    API_MASTER_TOKEN,
    DATA_DIR,
    KNOWLEDGE_DIR,
    WIKI_DIR,
)
from src.shared.logger import get_logger
from src.shared.packaging import cleanup_temp_file, create_pdf_from_markdown, zip_document
from src.storage import db

logger = get_logger("channels.api")

app = FastAPI(title="PageFly API", version="0.1.0")

from src.auth.routes import router as auth_router
app.include_router(auth_router)

from fastapi.middleware.cors import CORSMiddleware
from src.shared.config import FRONTEND_ORIGIN

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _safe_doc_path(raw_path: str) -> Path:
    """Validate and resolve a document path from DB. Raises HTTPException on traversal."""
    doc_dir = Path(raw_path).resolve()
    if not doc_dir.is_relative_to(DATA_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid document path")
    return doc_dir
security = HTTPBearer(auto_error=False)


# ── Health check (no auth required) ──

@app.get("/health")
async def health_check():
    """Health check for Docker / load balancer."""
    try:
        conn = db.get_connection()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok"}
    except Exception as e:
        logger.error("Health check failed: %s", e)
        return JSONResponse(status_code=503, content={"status": "error", "detail": "Service unavailable"})


# ── Help (no auth required) ──

@app.get("/")
@app.get("/api")
async def api_help():
    """API reference — no auth required."""
    return {
        "name": "PageFly API",
        "version": "0.1.0",
        "auth": "Bearer token in Authorization header",
        "endpoints": {
            "POST /api/ingest": "Upload a file for ingest (pdf, txt, md, docx, images, audio)",
            "GET /api/documents": "List documents (query: category, status, search, limit, offset)",
            "GET /api/documents/{id}": "Get document metadata + content",
            "GET /api/documents/{id}/download": "Download as ZIP or PDF (query: format=zip|pdf)",
            "GET /api/wiki": "List wiki articles",
            "GET /api/wiki/{id}": "Get wiki article content",
            "POST /api/query": "Agent-powered Q&A (body: {question})",
            "POST /api/search": "Full-text search (body: {keyword})",
            "GET /api/schedules": "List scheduled tasks",
            "POST /api/schedules": "Create schedule (body: {name, cron_expr, task_type, prompt})",
            "PUT /api/schedules/{id}": "Update schedule",
            "GET /api/documents/{id}/delete-preview": "Preview deletion impact",
            "DELETE /api/documents/{id}?confirm=true": "Delete document with reference cleanup",
            "DELETE /api/schedules/{id}": "Delete schedule",
            "GET /api/prompts": "List custom prompts (query: category)",
            "POST /api/prompts": "Save prompt (body: {name, content, category})",
            "DELETE /api/prompts/{name}": "Delete prompt",
            "GET /api/stats": "System statistics",
            "GET /api/tokens": "List API tokens (master token required)",
            "POST /api/tokens": "Create new token (body: {name}, master token required)",
            "DELETE /api/tokens/{id}": "Revoke token (master token required)",
        },
    }

# Allowed file extensions for ingest
ALLOWED_EXTENSIONS = {
    ".pdf", ".txt", ".md", ".markdown",
    ".docx", ".doc",
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp3", ".wav", ".ogg", ".m4a",
}

# Track temp files for cleanup after response
_temp_files: list[Path] = []


# ── Auth ──

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify Bearer token — accepts JWT session, master token, or DB token."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = credentials.credentials

    # Check JWT session token (from login flow)
    from src.auth.service import verify_jwt
    if verify_jwt(token) is not None:
        return credentials

    # Check master token
    if API_MASTER_TOKEN and hmac.compare_digest(token, API_MASTER_TOKEN):
        return credentials

    # Check DB tokens
    if db.validate_api_token(token):
        return credentials

    raise HTTPException(status_code=401, detail="Invalid token")


def verify_master_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify master token or valid JWT — for token management endpoints."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    # Accept master token
    if API_MASTER_TOKEN and hmac.compare_digest(credentials.credentials, API_MASTER_TOKEN):
        return credentials
    # Accept valid JWT (logged-in admin)
    from src.auth.service import verify_jwt
    if verify_jwt(credentials.credentials):
        return credentials
    raise HTTPException(status_code=403, detail="Master token or valid login required")


# ── Ingest ──

@app.post("/api/ingest", dependencies=[Depends(verify_token)])
async def ingest_file(file: UploadFile = File(...)):
    """Upload and ingest a file."""
    # Validate extension
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported format: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # Read and validate size
    content = await file.read()
    max_bytes = API_MAX_UPLOAD_MB * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large: {len(content) / 1024 / 1024:.1f}MB. Max: {API_MAX_UPLOAD_MB}MB",
        )

    # Sanitize filename to prevent path traversal
    import re
    safe_name = re.sub(r'[^\w\-.]', '_', Path(file.filename).name) or "upload"
    tmp_path = Path(tempfile.mkdtemp()) / safe_name
    tmp_path.write_bytes(content)

    try:
        from src.ingest.pipeline import ingest
        from src.shared.types import IngestInput

        input_data = IngestInput(
            type="file",
            file_path=str(tmp_path),
            original_filename=file.filename,
        )

        # Run ingest in background so the API returns immediately
        import concurrent.futures
        _ingest_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="api_ingest")

        def _bg_ingest():
            try:
                ingest(input_data)
            except Exception as e:
                logger.error("Background ingest failed for %s: %s", file.filename, e)
            finally:
                tmp_path.unlink(missing_ok=True)
                tmp_path.parent.rmdir()

        _ingest_executor.submit(_bg_ingest)
        return {"status": "ok", "filename": file.filename, "message": "File received, processing in background"}
    except Exception as e:
        tmp_path.unlink(missing_ok=True)
        tmp_path.parent.rmdir()
        raise HTTPException(status_code=500, detail=str(e))


# ── Documents ──

@app.get("/api/documents", dependencies=[Depends(verify_token)])
async def list_documents(
    category: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List documents with optional filters."""
    conn = db.get_connection()

    conditions = []
    params = []
    if category:
        conditions.append("category = ?")
        params.append(category)
    if status:
        conditions.append("status = ?")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    if search:
        # With search: fetch all matching rows, filter, then paginate
        query_str = f"SELECT * FROM documents {where} ORDER BY ingested_at DESC"
        rows = conn.execute(query_str, params).fetchall()
        conn.close()

        keyword = search.lower()
        filtered = []
        for doc_row in rows:
            doc = dict(doc_row)
            if keyword in doc.get("title", "").lower() or keyword in doc.get("description", "").lower():
                filtered.append(doc)
                continue
            try:
                doc_dir = _safe_doc_path(doc["current_path"])
                md_path = doc_dir / "document.md"
                if md_path.exists() and keyword in md_path.read_text(encoding="utf-8").lower():
                    filtered.append(doc)
            except Exception:
                pass

        total = len(filtered)
        docs = filtered[offset:offset + limit]
    else:
        # Without search: paginate at SQL level
        query_str = f"SELECT * FROM documents {where} ORDER BY ingested_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        rows = conn.execute(query_str, params).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM documents {where}", params[:-2] if conditions else []).fetchone()[0]
        conn.close()
        docs = [dict(r) for r in rows]

    return {"total": total, "documents": docs}


@app.get("/api/documents/{doc_id}", dependencies=[Depends(verify_token)])
async def get_document(doc_id: str):
    """Get document metadata and content."""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_dir = _safe_doc_path(doc["current_path"])
    md_path = doc_dir / "document.md"
    meta_path = doc_dir / "metadata.json"

    result = dict(doc)
    if md_path.exists():
        result["content"] = md_path.read_text(encoding="utf-8")
    if meta_path.exists():
        result["metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))

    return result


@app.put("/api/documents/{doc_id}/content", dependencies=[Depends(verify_token)])
async def update_document_content(doc_id: str, body: dict):
    """Update document markdown content."""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_dir = _safe_doc_path(doc["current_path"])
    md_path = doc_dir / "document.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Document file not found")
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="Content must be a string")
    md_path.write_text(content, encoding="utf-8")
    return {"status": "ok"}


@app.get("/api/documents/{doc_id}/files/{file_path:path}")
async def get_document_file(
    doc_id: str,
    file_path: str,
    token: str = Query(default=""),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Serve a file from a document's directory. Supports token as query param for img tags."""
    # Verify auth: header OR query param
    auth_token = credentials.credentials if credentials else token
    if not auth_token:
        raise HTTPException(status_code=401, detail="Missing token")
    from src.auth.service import verify_jwt
    if not (verify_jwt(auth_token) or (API_MASTER_TOKEN and hmac.compare_digest(auth_token, API_MASTER_TOKEN)) or db.validate_api_token(auth_token)):
        raise HTTPException(status_code=401, detail="Invalid token")

    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    doc_dir = _safe_doc_path(doc["current_path"])
    target = (doc_dir / file_path).resolve()
    if not target.is_relative_to(doc_dir.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(target))


@app.get("/api/documents/{doc_id}/download", dependencies=[Depends(verify_token)])
async def download_document(doc_id: str, format: str = Query(default="zip", pattern="^(zip|pdf)$")):
    """Download document as ZIP or PDF."""
    doc = db.get_document(doc_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_dir = _safe_doc_path(doc["current_path"])
    if not doc_dir.exists():
        raise HTTPException(status_code=404, detail="Document folder not found on disk")

    try:
        if format == "pdf":
            md_path = doc_dir / "document.md"
            if not md_path.exists():
                raise HTTPException(status_code=404, detail="No document.md found")
            file_path = create_pdf_from_markdown(md_path, doc.get("title", doc_dir.name))
            media_type = "application/pdf"
        else:
            file_path = zip_document(doc_dir)
            media_type = "application/zip"

        return _temp_file_response(file_path, media_type)

    except RuntimeError as e:
        if "weasyprint" in str(e):
            raise HTTPException(status_code=501, detail="PDF generation unavailable (weasyprint not installed)")
        raise


# ── Document Deletion ──

@app.get("/api/documents/{doc_id}/delete-preview", dependencies=[Depends(verify_token)])
async def preview_delete(doc_id: str):
    """Preview what deleting a document would affect."""
    from src.storage.deletion import preview_deletion
    preview = preview_deletion(doc_id)
    return {
        "found": preview.found,
        "doc_id": preview.doc_id,
        "doc_title": preview.doc_title,
        "affected_wiki_articles": preview.affected_wiki_articles,
        "summary": preview.summary(),
    }


@app.delete("/api/documents/{doc_id}", dependencies=[Depends(verify_token)])
async def delete_doc(doc_id: str, confirm: bool = Query(default=False)):
    """Delete a document with reference cleanup. Requires confirm=true."""
    if not confirm:
        from src.storage.deletion import preview_deletion
        preview = preview_deletion(doc_id)
        if not preview.found:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "action": "preview",
            "message": "Add ?confirm=true to actually delete",
            "summary": preview.summary(),
            "affected_wiki_articles": len(preview.affected_wiki_articles),
        }

    from src.storage.deletion import execute_deletion
    result = execute_deletion(doc_id)
    if "not found" in result:
        raise HTTPException(status_code=404, detail=result)
    if result.startswith("Error"):
        raise HTTPException(status_code=500, detail=result)
    return {"action": "deleted", "result": result}


# ── Wiki ──

@app.get("/api/wiki", dependencies=[Depends(verify_token)])
async def list_wiki():
    """List all wiki articles."""
    conn = db.get_connection()
    rows = conn.execute("SELECT * FROM wiki_articles ORDER BY created_at DESC").fetchall()
    conn.close()
    return {"articles": [dict(r) for r in rows]}


@app.get("/api/wiki/{article_id}", dependencies=[Depends(verify_token)])
async def get_wiki_article(article_id: str):
    """Get a wiki article's content."""
    conn = db.get_connection()
    row = conn.execute("SELECT * FROM wiki_articles WHERE id = ?", (article_id,)).fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Wiki article not found")

    result = dict(row)
    article_dir = _safe_doc_path(result["file_path"])
    md_path = article_dir / "document.md"
    meta_path = article_dir / "metadata.json"

    if md_path.exists():
        result["content"] = md_path.read_text(encoding="utf-8")
    if meta_path.exists():
        result["metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))

    return result


# ── Query ──

@app.post("/api/query", dependencies=[Depends(verify_token)])
async def agent_query(body: dict):
    """Agent-powered question answering."""
    question = body.get("question", "")
    if not question:
        raise HTTPException(status_code=400, detail="Missing 'question' field")

    from src.agents.query import ask
    response = await ask(question)

    return {"question": question, "answer": response}


@app.post("/api/search", dependencies=[Depends(verify_token)])
async def full_text_search(body: dict):
    """Full-text keyword search across all documents."""
    keyword = body.get("keyword", "").lower()
    if not keyword:
        raise HTTPException(status_code=400, detail="Missing 'keyword' field")

    results = []
    for root_dir, doc_type in ((KNOWLEDGE_DIR, "knowledge"), (WIKI_DIR, "wiki")):
        if not root_dir.exists():
            continue
        for md_path in root_dir.rglob("document.md"):
            content = md_path.read_text(encoding="utf-8")
            if keyword not in content.lower():
                continue

            meta_path = md_path.parent / "metadata.json"
            meta = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

            idx = content.lower().index(keyword)
            start = max(0, idx - 100)
            end = min(len(content), idx + len(keyword) + 100)
            snippet = content[start:end].replace("\n", " ")

            results.append({
                "type": doc_type,
                "id": meta.get("id", ""),
                "title": meta.get("title", md_path.parent.name),
                "snippet": f"...{snippet}...",
            })

    return {"keyword": keyword, "total": len(results), "results": results}


# ── Schedules ──

@app.get("/api/schedules", dependencies=[Depends(verify_token)])
async def list_all_schedules():
    """List all scheduled tasks."""
    from src.shared.config import (
        SCHEDULE_DAILY_REVIEW, SCHEDULE_WEEKLY_REVIEW,
        SCHEDULE_MONTHLY_REVIEW, SCHEDULE_COMPILER,
    )

    system = [
        {"name": "Daily Review", "cron": SCHEDULE_DAILY_REVIEW, "type": "review", "source": "system"},
        {"name": "Weekly Review", "cron": SCHEDULE_WEEKLY_REVIEW, "type": "review", "source": "system"},
        {"name": "Monthly Review", "cron": SCHEDULE_MONTHLY_REVIEW, "type": "review", "source": "system"},
        {"name": "Compiler", "cron": SCHEDULE_COMPILER, "type": "compiler", "source": "system"},
    ]

    user_tasks = db.list_scheduled_tasks()
    user = [
        {
            "id": t["id"],
            "name": t["name"],
            "cron": t["cron_expr"],
            "type": t["task_type"],
            "prompt": t["prompt"],
            "enabled": bool(t["enabled"]),
            "source": "user",
        }
        for t in user_tasks
    ]

    return {"schedules": system + user}


@app.post("/api/schedules", dependencies=[Depends(verify_token)])
async def create_schedule(body: dict):
    """Create a new scheduled task."""
    from src.ingest.metadata import generate_id

    name = body.get("name", "")
    cron_expr = body.get("cron_expr", "")
    task_type = body.get("task_type", "custom")
    prompt = body.get("prompt", "")

    if not name or not cron_expr:
        raise HTTPException(status_code=400, detail="Missing 'name' or 'cron_expr'")

    parts = cron_expr.strip().split()
    if len(parts) != 5:
        raise HTTPException(status_code=400, detail="Invalid cron expression (need 5 fields)")

    task_id = generate_id()
    db.insert_scheduled_task(task_id, name, cron_expr, task_type, prompt)

    return {"status": "ok", "id": task_id, "name": name}


@app.put("/api/schedules/{task_id}", dependencies=[Depends(verify_token)])
async def update_schedule_api(task_id: str, body: dict):
    """Update a scheduled task."""
    allowed = {"name", "cron_expr", "prompt", "enabled", "task_type"}
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    db.update_scheduled_task(task_id, **updates)
    return {"status": "ok", "updated": list(updates.keys())}


@app.delete("/api/schedules/{task_id}", dependencies=[Depends(verify_token)])
async def delete_schedule_api(task_id: str):
    """Delete a scheduled task."""
    db.delete_scheduled_task(task_id)
    return {"status": "ok"}


# ── Prompts ──

@app.get("/api/prompts", dependencies=[Depends(verify_token)])
async def list_all_prompts(category: str | None = None):
    """List custom prompts."""
    prompts = db.list_custom_prompts(category)
    return {"prompts": [dict(p) for p in prompts]}


@app.post("/api/prompts", dependencies=[Depends(verify_token)])
async def save_prompt_api(body: dict):
    """Create or update a custom prompt."""
    from src.ingest.metadata import generate_id

    name = body.get("name", "")
    content = body.get("content", "")
    category = body.get("category", "general")

    if not name or not content:
        raise HTTPException(status_code=400, detail="Missing 'name' or 'content'")

    prompt_id = generate_id()
    db.upsert_custom_prompt(prompt_id, name, content, category)
    return {"status": "ok", "name": name}


@app.delete("/api/prompts/{name}", dependencies=[Depends(verify_token)])
async def delete_prompt_api(name: str):
    """Delete a custom prompt."""
    db.delete_custom_prompt(name)
    return {"status": "ok"}


# ── Workspace ──

from src.shared.config import WORKSPACE_DIR, RAW_DIR

@app.get("/api/workspace", dependencies=[Depends(verify_token)])
async def list_workspace_folders():
    """List workspace folders (each has document.md + optional images/)."""
    WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    folders = []
    for p in sorted(WORKSPACE_DIR.iterdir()):
        if p.is_dir() and (p / "document.md").exists():
            md = p / "document.md"
            images_dir = p / "images"
            image_count = len(list(images_dir.iterdir())) if images_dir.is_dir() else 0
            folders.append({
                "name": p.name,
                "size": md.stat().st_size,
                "modified": md.stat().st_mtime,
                "image_count": image_count,
            })
    return {"folders": folders}


@app.get("/api/workspace/{folder_name}/content", dependencies=[Depends(verify_token)])
async def read_workspace_content(folder_name: str):
    """Read document.md from a workspace folder."""
    folder = (WORKSPACE_DIR / folder_name).resolve()
    if not folder.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    md_path = folder / "document.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return {"content": md_path.read_text(encoding="utf-8"), "name": folder_name}


@app.put("/api/workspace/{folder_name}/content", dependencies=[Depends(verify_token)])
async def update_workspace_content(folder_name: str, body: dict):
    """Update document.md content."""
    folder = (WORKSPACE_DIR / folder_name).resolve()
    if not folder.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    md_path = folder / "document.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Not found")
    md_path.write_text(body.get("content", ""), encoding="utf-8")
    return {"status": "ok"}


@app.get("/api/workspace/{folder_name}/images", dependencies=[Depends(verify_token)])
async def list_workspace_images(folder_name: str):
    """List images in a workspace folder."""
    images_dir = (WORKSPACE_DIR / folder_name / "images").resolve()
    if not images_dir.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    if not images_dir.is_dir():
        return {"images": []}
    return {"images": [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(images_dir.iterdir()) if f.is_file()
    ]}


@app.post("/api/workspace/{folder_name}/images", dependencies=[Depends(verify_token)])
async def upload_workspace_image(folder_name: str, file: UploadFile = File(...)):
    """Upload an image to a workspace folder's images/ dir."""
    images_dir = (WORKSPACE_DIR / folder_name / "images").resolve()
    if not images_dir.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    images_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "image.png").name
    target = images_dir / safe_name
    target.write_bytes(await file.read())
    return {"status": "ok", "name": safe_name, "markdown": f"![{safe_name}](images/{safe_name})"}


@app.get("/api/workspace/{folder_name}/images/{image_name}")
async def serve_workspace_image(
    folder_name: str, image_name: str,
    token: str = Query(default=""),
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    """Serve a workspace image (supports token query param for img tags)."""
    auth_token = credentials.credentials if credentials else token
    if not auth_token:
        raise HTTPException(status_code=401, detail="Missing token")
    from src.auth.service import verify_jwt
    if not (verify_jwt(auth_token) or (API_MASTER_TOKEN and hmac.compare_digest(auth_token, API_MASTER_TOKEN)) or db.validate_api_token(auth_token)):
        raise HTTPException(status_code=401, detail="Invalid token")
    target = (WORKSPACE_DIR / folder_name / "images" / image_name).resolve()
    if not target.is_relative_to(WORKSPACE_DIR.resolve()) or not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(target))


@app.delete("/api/workspace/{folder_name}/images/{image_name}", dependencies=[Depends(verify_token)])
async def delete_workspace_image(folder_name: str, image_name: str):
    """Delete an image from a workspace folder."""
    target = (WORKSPACE_DIR / folder_name / "images" / image_name).resolve()
    if not target.is_relative_to(WORKSPACE_DIR.resolve()) or not target.exists():
        raise HTTPException(status_code=404, detail="Not found")
    target.unlink()
    return {"status": "ok"}


@app.post("/api/workspace/{folder_name}/ingest", dependencies=[Depends(verify_token)])
async def ingest_workspace_folder(folder_name: str):
    """Ingest a workspace folder (document.md + images/) into the pipeline."""
    import shutil
    folder = (WORKSPACE_DIR / folder_name).resolve()
    if not folder.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    if not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")
    md_path = folder / "document.md"
    if not md_path.exists():
        raise HTTPException(status_code=400, detail="No document.md in folder")

    # Ingest the markdown through pipeline
    from src.ingest.pipeline import ingest as run_ingest
    from src.shared.types import IngestInput

    loop = asyncio.get_running_loop()
    doc_id = await loop.run_in_executor(
        None, run_ingest,
        IngestInput(type="file", file_path=str(md_path), original_filename=f"{folder_name}.md"),
    )

    if not doc_id:
        raise HTTPException(status_code=500, detail="Ingest failed")

    # Copy images/ into the newly created doc folder
    ws_images = folder / "images"
    if ws_images.is_dir() and any(ws_images.iterdir()):
        doc = db.get_document(doc_id)
        if doc:
            doc_images = Path(doc["current_path"]) / "images"
            doc_images.mkdir(parents=True, exist_ok=True)
            for img in ws_images.iterdir():
                if img.is_file():
                    shutil.copy2(str(img), str(doc_images / img.name))

    # Remove workspace folder
    shutil.rmtree(str(folder), ignore_errors=True)
    return {"status": "ok", "doc_id": doc_id, "folder": folder_name}


@app.post("/api/workspace", dependencies=[Depends(verify_token)])
async def create_workspace_folder(body: dict):
    """Create a new workspace folder with document.md."""
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    safe_name = "".join(c for c in name if c.isalnum() or c in " -_\u4e00-\u9fff").strip()
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid name")
    folder = (WORKSPACE_DIR / safe_name).resolve()
    if not folder.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid path")
    folder.mkdir(parents=True, exist_ok=True)
    md_path = folder / "document.md"
    if not md_path.exists():
        md_path.write_text(f"# {name}\n\n", encoding="utf-8")
    return {"status": "ok", "name": safe_name}


@app.put("/api/workspace/{folder_name}", dependencies=[Depends(verify_token)])
async def rename_workspace_folder(folder_name: str, body: dict):
    """Rename a workspace folder."""
    new_name = body.get("name", "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name required")
    safe_name = "".join(c for c in new_name if c.isalnum() or c in " -_\u4e00-\u9fff").strip()
    folder = (WORKSPACE_DIR / folder_name).resolve()
    if not folder.is_relative_to(WORKSPACE_DIR.resolve()) or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")
    new_folder = (WORKSPACE_DIR / safe_name).resolve()
    if not new_folder.is_relative_to(WORKSPACE_DIR.resolve()):
        raise HTTPException(status_code=403, detail="Invalid name")
    folder.rename(new_folder)
    return {"status": "ok", "name": safe_name}


@app.delete("/api/workspace/{folder_name}", dependencies=[Depends(verify_token)])
async def delete_workspace_folder(folder_name: str):
    """Delete an entire workspace folder."""
    import shutil
    folder = (WORKSPACE_DIR / folder_name).resolve()
    if not folder.is_relative_to(WORKSPACE_DIR.resolve()) or not folder.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")
    shutil.rmtree(str(folder), ignore_errors=True)
    return {"status": "ok"}


# ── Knowledge Graph ──

@app.get("/api/graph", dependencies=[Depends(verify_token)])
async def get_knowledge_graph():
    """Build a graph of documents and wiki articles with their references."""
    conn = db.get_connection()
    docs = conn.execute("SELECT id, title, category, subcategory, status FROM documents").fetchall()
    wikis = conn.execute("SELECT id, title, article_type, source_document_ids FROM wiki_articles").fetchall()
    conn.close()

    nodes = []
    edges = []

    for d in docs:
        nodes.append({
            "id": d["id"],
            "label": d["title"] or d["id"][:8],
            "type": "document",
            "category": d["category"] or "",
            "subcategory": d["subcategory"] or "",
        })

    for w in wikis:
        nodes.append({
            "id": w["id"],
            "label": w["title"] or w["id"][:8],
            "type": "wiki",
            "article_type": w["article_type"] or "",
        })
        # Edges from wiki to source documents
        source_ids = []
        try:
            source_ids = json.loads(w["source_document_ids"] or "[]")
        except (json.JSONDecodeError, TypeError):
            pass
        for src_id in source_ids:
            edges.append({"source": src_id, "target": w["id"], "relation": "compiled_from"})

    return {"nodes": nodes, "edges": edges}


# ── Tokens (master token required) ──

@app.get("/api/tokens", dependencies=[Depends(verify_master_token)])
async def list_tokens():
    """List all API tokens (master token required)."""
    tokens = db.list_api_tokens()
    return {"tokens": tokens}


@app.post("/api/tokens", dependencies=[Depends(verify_master_token)])
async def create_token(body: dict):
    """Generate a new API token (master token required)."""
    import secrets
    from src.ingest.metadata import generate_id

    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="Missing 'name' field")

    token_id = generate_id()
    token_value = f"pf_{secrets.token_urlsafe(32)}"

    db.insert_api_token(token_id, name, token_value)
    logger.info("API token created: %s", name)

    # Return full token only on creation — never shown again
    return {"id": token_id, "name": name, "token": token_value}


@app.delete("/api/tokens/{token_id}", dependencies=[Depends(verify_master_token)])
async def revoke_token(token_id: str):
    """Revoke an API token (master token required)."""
    db.delete_api_token(token_id)
    return {"status": "ok"}


# ── Categories ──

@app.get("/api/categories", dependencies=[Depends(verify_token)])
async def get_categories():
    """Get category definitions from config."""
    from src.shared.config import load_categories
    return load_categories()


@app.put("/api/categories/{old_id}", dependencies=[Depends(verify_token)])
async def rename_category(old_id: str, body: dict):
    """Rename a category with full cascade: config + DB + filesystem + metadata."""
    import shutil
    from src.shared.config import CONFIG_DIR, KNOWLEDGE_DIR, load_categories

    new_id = body.get("new_id", "").strip()
    new_name = body.get("new_name", "").strip()
    if not new_id:
        raise HTTPException(status_code=400, detail="new_id required")

    # 1. Update categories.json
    cats_path = CONFIG_DIR / "categories.json"
    cats_data = load_categories()
    cat_def = next((c for c in cats_data["categories"] if c["id"] == old_id), None)
    if not cat_def:
        raise HTTPException(status_code=404, detail=f"Category '{old_id}' not found")
    cat_def["id"] = new_id
    if new_name:
        cat_def["name"] = new_name
    cats_path.write_text(json.dumps(cats_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # 2. Rename filesystem directory
    old_dir = KNOWLEDGE_DIR / old_id
    new_dir = KNOWLEDGE_DIR / new_id
    if old_dir.exists() and old_dir != new_dir:
        if new_dir.exists():
            raise HTTPException(status_code=409, detail=f"Directory '{new_id}' already exists")
        old_dir.rename(new_dir)

    # 3. Update all metadata.json files in the renamed directory
    updated_files = 0
    if new_dir.exists():
        for meta_path in new_dir.rglob("metadata.json"):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("category") == old_id:
                    meta["category"] = new_id
                    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                    updated_files += 1
            except Exception:
                continue

    # 4. Update database
    conn = db.get_connection()
    conn.execute("UPDATE documents SET category = ? WHERE category = ?", (new_id, old_id))
    # Update current_path column
    rows = conn.execute("SELECT id, current_path FROM documents WHERE category = ?", (new_id,)).fetchall()
    for row in rows:
        old_path = row["current_path"]
        if old_id in old_path:
            new_path = old_path.replace(f"/{old_id}/", f"/{new_id}/")
            conn.execute("UPDATE documents SET current_path = ? WHERE id = ?", (new_path, row["id"]))
    conn.commit()
    conn.close()

    logger.info("Category renamed: %s → %s (%d metadata files updated)", old_id, new_id, updated_files)
    return {"status": "ok", "old_id": old_id, "new_id": new_id, "files_updated": updated_files}


@app.post("/api/categories", dependencies=[Depends(verify_token)])
async def add_category(body: dict):
    """Add a new category to config."""
    from src.shared.config import CONFIG_DIR, load_categories

    cat_id = body.get("id", "").strip()
    cat_name = body.get("name", "").strip()
    if not cat_id or not cat_name:
        raise HTTPException(status_code=400, detail="id and name required")

    cats_path = CONFIG_DIR / "categories.json"
    cats_data = load_categories()
    if any(c["id"] == cat_id for c in cats_data["categories"]):
        raise HTTPException(status_code=409, detail=f"Category '{cat_id}' already exists")

    cats_data["categories"].append({"id": cat_id, "name": cat_name, "subcategories": []})
    cats_path.write_text(json.dumps(cats_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "id": cat_id}


@app.delete("/api/categories/{cat_id}", dependencies=[Depends(verify_token)])
async def delete_category(cat_id: str, merge_into: str = Query(default="")):
    """Delete a category. If merge_into is set, move all documents to that category first."""
    import shutil
    from src.shared.config import CONFIG_DIR, KNOWLEDGE_DIR, load_categories

    cats_path = CONFIG_DIR / "categories.json"
    cats_data = load_categories()
    cat_def = next((c for c in cats_data["categories"] if c["id"] == cat_id), None)
    if not cat_def:
        raise HTTPException(status_code=404, detail=f"Category '{cat_id}' not found")

    source_dir = KNOWLEDGE_DIR / cat_id
    moved_count = 0

    if merge_into:
        # Validate target exists
        if not any(c["id"] == merge_into for c in cats_data["categories"]):
            raise HTTPException(status_code=404, detail=f"Target category '{merge_into}' not found")
        if merge_into == cat_id:
            raise HTTPException(status_code=400, detail="Cannot merge into self")

        target_dir = KNOWLEDGE_DIR / merge_into
        target_dir.mkdir(parents=True, exist_ok=True)

        # Move all document folders from source to target
        if source_dir.exists():
            for item in source_dir.iterdir():
                if item.is_dir():
                    dest = target_dir / item.name
                    shutil.move(str(item), str(dest))
                    # Update metadata.json
                    meta_path = dest / "metadata.json"
                    if meta_path.exists():
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        meta["category"] = merge_into
                        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
                    moved_count += 1
            # Remove empty source directory
            shutil.rmtree(str(source_dir), ignore_errors=True)

        # Update database
        conn = db.get_connection()
        rows = conn.execute("SELECT id, current_path FROM documents WHERE category = ?", (cat_id,)).fetchall()
        for row in rows:
            new_path = row["current_path"].replace(f"/{cat_id}/", f"/{merge_into}/")
            conn.execute("UPDATE documents SET category = ?, current_path = ? WHERE id = ?",
                         (merge_into, new_path, row["id"]))
        conn.commit()
        conn.close()

    # Remove from config
    cats_data["categories"] = [c for c in cats_data["categories"] if c["id"] != cat_id]
    cats_path.write_text(json.dumps(cats_data, indent=2, ensure_ascii=False), encoding="utf-8")

    return {"status": "ok", "merged_into": merge_into or None, "documents_moved": moved_count}


# ── Stats ──

@app.get("/api/stats", dependencies=[Depends(verify_token)])
async def get_stats():
    """Get system statistics."""
    conn = db.get_connection()
    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    wiki_count = conn.execute("SELECT COUNT(*) FROM wiki_articles").fetchone()[0]
    ops_count = conn.execute("SELECT COUNT(*) FROM operations_log").fetchone()[0]
    schedule_count = conn.execute("SELECT COUNT(*) FROM scheduled_tasks").fetchone()[0]
    prompt_count = conn.execute("SELECT COUNT(*) FROM custom_prompts").fetchone()[0]

    categories = conn.execute(
        "SELECT category, COUNT(*) as count FROM documents WHERE category != '' GROUP BY category"
    ).fetchall()
    conn.close()

    return {
        "documents": doc_count,
        "wiki_articles": wiki_count,
        "operations": ops_count,
        "scheduled_tasks": schedule_count,
        "custom_prompts": prompt_count,
        "categories": {r["category"]: r["count"] for r in categories},
    }


# ── Web Chat ──

# Use Telegram chat_id for shared session. Fallback to 0 if not configured.
def _web_chat_id() -> int:
    from src.shared.config import TELEGRAM_CHAT_ID
    return int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else 0


@app.get("/api/chat/history", dependencies=[Depends(verify_token)])
async def get_chat_history():
    """Get chat history (shared with Telegram)."""
    chat_id = _web_chat_id()
    messages = db.load_session(chat_id) or []
    return {"messages": messages, "chat_id": chat_id}


@app.post("/api/chat", dependencies=[Depends(verify_token)])
async def web_chat(body: dict):
    """Send a message to the query agent (shared session with Telegram)."""
    from src.agents.query import QuerySession, ask

    user_message = body.get("message", "").strip()
    if not user_message:
        raise HTTPException(status_code=400, detail="message required")

    chat_id = _web_chat_id()
    saved = db.load_session(chat_id)
    session = QuerySession(messages=saved) if saved else QuerySession()

    # Trim if too long
    if len(session.messages) > 100:
        session.messages = session.messages[-100:]

    response = await ask(user_message, session)

    # Persist
    db.save_session(chat_id, session.messages)

    return {"response": response, "messages": session.messages}


@app.post("/api/chat/reset", dependencies=[Depends(verify_token)])
async def reset_chat():
    """Clear chat history."""
    chat_id = _web_chat_id()
    db.save_session(chat_id, [])
    return {"status": "ok"}


# ── Trends ──

@app.get("/api/trends", dependencies=[Depends(verify_token)])
async def get_trends(days: int = Query(default=14)):
    """Get daily operation counts for trend charts."""
    conn = db.get_connection()
    rows = conn.execute(
        """SELECT DATE(created_at) as day, operation, COUNT(*) as count
           FROM operations_log
           WHERE created_at >= DATE('now', ?)
           GROUP BY day, operation
           ORDER BY day""",
        (f"-{min(days, 90)} days",),
    ).fetchall()
    conn.close()

    daily: dict[str, dict[str, int]] = {}
    for r in rows:
        day = r["day"]
        if day not in daily:
            daily[day] = {"ingest": 0, "classify": 0, "wiki_compile": 0, "total": 0}
        op = r["operation"]
        if op in daily[day]:
            daily[day][op] = r["count"]
        daily[day]["total"] += r["count"]

    return {"trends": [{"date": d, **v} for d, v in sorted(daily.items())]}


# ── Activity ──

@app.get("/api/activity", dependencies=[Depends(verify_token)])
async def get_activity(limit: int = Query(default=30)):
    """Get recent operations log."""
    conn = db.get_connection()
    rows = conn.execute(
        """SELECT o.id, o.document_id, o.operation, o.from_path, o.to_path, o.created_at,
                  d.title as doc_title
           FROM operations_log o
           LEFT JOIN documents d ON o.document_id = d.id
           ORDER BY o.created_at DESC LIMIT ?""",
        (min(limit, 100),),
    ).fetchall()
    conn.close()
    return {"activity": [dict(r) for r in rows]}


# ── Helpers ──

def _temp_file_response(file_path: Path, media_type: str) -> FileResponse:
    """Create a FileResponse that cleans up the temp file after sending."""
    from starlette.background import BackgroundTask

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type=media_type,
        background=BackgroundTask(cleanup_temp_file, file_path),
    )
