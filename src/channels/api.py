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
    """Verify master token only — for token management endpoints."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not API_MASTER_TOKEN or not hmac.compare_digest(credentials.credentials, API_MASTER_TOKEN):
        raise HTTPException(status_code=403, detail="Master token required")
    return credentials


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

        loop = asyncio.get_running_loop()
        doc_id = await loop.run_in_executor(None, ingest, input_data)

        if doc_id:
            return {"status": "ok", "doc_id": doc_id, "filename": file.filename}
        else:
            raise HTTPException(status_code=500, detail="Ingest failed")
    finally:
        tmp_path.unlink(missing_ok=True)
        tmp_path.parent.rmdir()


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
