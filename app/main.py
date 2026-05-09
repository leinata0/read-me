from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import AsyncGenerator
from urllib.parse import urlparse
from zipfile import ZipFile

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models import AnalyzeRequest, ProviderError, ListModelsRequest, ListModelsResponse, TestConnectionRequest
from app.providers import get_provider, list_providers, PROVIDERS
from app.generator import run_pipeline

load_dotenv()
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent
REPO_CACHE_DIR = BASE_DIR.parent / ".cache" / "repo-imports"
SSE_QUEUE_MAXSIZE = 256
SSE_HEARTBEAT_SECONDS = 10
MAX_REPO_ARCHIVE_BYTES = 25 * 1024 * 1024
SUPPORTED_REPO_HOSTS = {"github.com", "www.github.com"}

app = FastAPI(title="README Generator", version="1.2.0")


@app.exception_handler(ProviderError)
async def provider_error_handler(request: Request, exc: ProviderError):
    return JSONResponse(status_code=exc.code, content={"detail": exc.message})


app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/providers")
async def api_providers():
    return [p.model_dump() for p in list_providers()]


@app.post("/api/providers/{provider_name}/models", response_model=ListModelsResponse)
async def api_list_models(provider_name: str, req: ListModelsRequest):
    cls = PROVIDERS.get(provider_name)
    if not cls:
        raise ProviderError(400, f"Unknown provider: {provider_name}")

    if not req.api_key:
        return ListModelsResponse(models=cls.available_models, source="fallback")

    try:
        models = await cls.list_models(req.api_key, req.base_url)
        return ListModelsResponse(models=models, source="fetched")
    except ProviderError as e:
        return ListModelsResponse(models=cls.available_models, source="fallback", error=f"[{e.code}] {e.message}")
    except Exception as e:
        return ListModelsResponse(models=cls.available_models, source="fallback", error=str(e)[:200])


def _build_provider_debug(req_provider: str, req_model: str | None, req_api_keys: dict) -> dict:
    keys = (req_api_keys or {}).get(req_provider or "")
    request_key = getattr(keys, "api_key", "") if keys is not None else ""
    request_base_url = getattr(keys, "base_url", "") if keys is not None else ""
    return {
        "provider": req_provider,
        "model": req_model or "",
        "has_request_key": bool(request_key),
        "has_request_base_url": bool(request_base_url),
    }


def _normalize_repo_url(repo_url: str) -> str:
    value = repo_url.strip()
    if not value:
        raise ProviderError(400, "repo_url is required for repo_url mode")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProviderError(400, "仓库 URL 必须是有效的 HTTPS 地址。")
    hostname = (parsed.hostname or "").lower()
    if hostname not in SUPPORTED_REPO_HOSTS:
        raise ProviderError(400, "当前仅支持 GitHub 公开仓库 URL。")
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 2:
        raise ProviderError(400, "仓库 URL 格式不正确，请使用 https://github.com/owner/repo")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not owner or not repo:
        raise ProviderError(400, "仓库 URL 格式不正确，请使用 https://github.com/owner/repo")
    return f"https://github.com/{owner}/{repo}"


async def _download_github_repo_to_tempdir(repo_url: str) -> tuple[str, str]:
    normalized = _normalize_repo_url(repo_url)
    owner, repo = normalized.removeprefix("https://github.com/").split("/", 1)
    archive_candidates = [
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/main",
        f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/master",
    ]

    REPO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="job-", dir=str(REPO_CACHE_DIR)))
    archive_path = temp_root / "repo.zip"

    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            last_status = None
            for archive_url in archive_candidates:
                resp = await client.get(archive_url)
                last_status = resp.status_code
                if resp.status_code == 200:
                    if len(resp.content) > MAX_REPO_ARCHIVE_BYTES:
                        raise ProviderError(400, "仓库归档过大，请改用本地路径模式或缩小仓库范围。")
                    archive_path.write_bytes(resp.content)
                    break
            else:
                if last_status == 404:
                    raise ProviderError(404, "未找到公开仓库，或默认分支不是 main/master。")
                raise ProviderError(502, f"拉取仓库归档失败 (HTTP {last_status})")

        with ZipFile(archive_path) as zf:
            members = zf.infolist()
            if len(members) > 5000:
                raise ProviderError(400, "仓库归档文件过多，请改用本地路径模式或缩小仓库范围。")
            extract_dir = temp_root / "repo"
            extract_dir.mkdir(parents=True, exist_ok=True)
            total_uncompressed = 0
            for member in members:
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ProviderError(400, "仓库归档包含非法路径，已拒绝处理。")
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_REPO_ARCHIVE_BYTES * 4:
                    raise ProviderError(400, "仓库解压内容过大，请改用本地路径模式或缩小仓库范围。")
            zf.extractall(extract_dir)

        children = [item for item in extract_dir.iterdir()]
        if len(children) == 1 and children[0].is_dir():
            return str(children[0]), str(temp_root)
        return str(extract_dir), str(temp_root)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise


@app.post("/api/test-connection")
async def api_test_connection(req: TestConnectionRequest):
    """Test if the API key and connection work for the selected provider."""
    import time as _time
    debug = _build_provider_debug(req.provider, req.model, req.api_keys)
    try:
        provider = get_provider(req.provider, req.model, req.api_keys)
        debug.update(getattr(provider, "debug_context", {}))
        start = _time.time()
        await provider.analyze(
            system_prompt="You are a test assistant. Respond with a short confirmation.",
            user_prompt='Respond with exactly: {"status":"ok"}',
            json_schema={"type": "object", "properties": {"status": {"type": "string"}}},
        )
        elapsed = round(_time.time() - start, 2)
        return JSONResponse(content={
            "ok": True,
            "model": provider.model,
            "provider": provider.name,
            "elapsed_seconds": elapsed,
            "message": f"连接成功！模型 {provider.model} 响应正常（{elapsed}s）",
            "debug": debug,
        })
    except ProviderError as e:
        return JSONResponse(status_code=e.code, content={
            "ok": False,
            "code": e.code,
            "message": e.message,
            "debug": debug,
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "ok": False,
            "code": 500,
            "message": f"测试失败: {str(e)[:200]}",
        })


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest, request: Request):
    queue: asyncio.Queue[str | None] = asyncio.Queue(maxsize=SSE_QUEUE_MAXSIZE)
    stream_closed = False

    _step_map = {
        "校验": "validate", "路径": "validate", "Validating": "validate",
        "读取": "read", "Reading": "read", "Found": "read",
        "分析": "analyze", "Analyzing": "analyze", "cached": "analyze",
        "生成": "generate", "Generating": "generate", "README": "generate",
    }

    async def push_event(payload: str | None):
        nonlocal stream_closed
        if stream_closed:
            return
        if await request.is_disconnected():
            stream_closed = True
            raise asyncio.CancelledError
        await queue.put(payload)

    async def on_progress(detail: str):
        step = ""
        for keyword, step_name in _step_map.items():
            if keyword in detail:
                step = step_name
                break
        data = json.dumps({"detail": detail, "step": step}, ensure_ascii=False)
        await push_event(f"event: progress\ndata: {data}\n\n")

    async def on_chunk(text: str):
        data = json.dumps({"text": text}, ensure_ascii=False)
        await push_event(f"event: chunk\ndata: {data}\n\n")

    async def background_task():
        temp_root_to_cleanup: str | None = None
        try:
            provider = get_provider(req.provider, req.model, req.api_keys, req.temperature)
            if req.source_type == "repo_url":
                await on_progress("正在拉取公开仓库...")
                working_dir, temp_root_to_cleanup = await _download_github_repo_to_tempdir(req.repo_url)
            else:
                working_dir = req.folder_path

            result = await run_pipeline(
                folder_path=working_dir,
                provider=provider,
                on_progress=on_progress,
                on_chunk=on_chunk,
                language=req.language,
                tone=req.tone,
                include_badges=req.include_badges,
                custom_sections=req.custom_sections,
                exclude_sections=req.exclude_sections,
                custom_prompt_suffix=req.custom_prompt_suffix,
                include_patterns=req.include_patterns,
                exclude_patterns=req.exclude_patterns,
                feedback=req.feedback,
                previous_readme=req.previous_readme,
                badge_style=req.badge_style,
                toc_depth=req.toc_depth,
                code_examples=req.code_examples,
                link_style=req.link_style,
                section_order=req.section_order,
                audience=req.audience,
                quality_mode=req.quality_mode,
            )

            done_data = json.dumps({"model": result.model, "provider": result.provider}, ensure_ascii=False)
            await push_event(f"event: done\ndata: {done_data}\n\n")
        except asyncio.CancelledError:
            logging.info("README generation cancelled after client disconnect")
            raise
        except ProviderError as e:
            detail = e.message
            detail += f" (渠道: {req.provider}, 模型: {req.model or '默认'})"
            keys = (req.api_keys or {}).get(req.provider or "")
            if keys and keys.base_url:
                detail += f", Base URL: {keys.base_url}"
            err = json.dumps({"code": e.code, "message": detail}, ensure_ascii=False)
            await push_event(f"event: error\ndata: {err}\n\n")
        except FileNotFoundError as e:
            err = json.dumps({"code": 404, "message": str(e)}, ensure_ascii=False)
            await push_event(f"event: error\ndata: {err}\n\n")
        except ValueError as e:
            err = json.dumps({"code": 400, "message": str(e)}, ensure_ascii=False)
            await push_event(f"event: error\ndata: {err}\n\n")
        except PermissionError as e:
            err = json.dumps({"code": 403, "message": f"Permission denied: {e}"}, ensure_ascii=False)
            await push_event(f"event: error\ndata: {err}\n\n")
        except Exception as e:
            err = json.dumps({"code": 500, "message": str(e)[:300]}, ensure_ascii=False)
            await push_event(f"event: error\ndata: {err}\n\n")
        finally:
            if temp_root_to_cleanup:
                shutil.rmtree(temp_root_to_cleanup, ignore_errors=True)
            await queue.put(None)

    async def event_stream() -> AsyncGenerator[str, None]:
        nonlocal stream_closed
        task = asyncio.create_task(background_task())
        try:
            while True:
                if await request.is_disconnected():
                    stream_closed = True
                    task.cancel()
                    break
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield item
        finally:
            stream_closed = True
            if not task.done():
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


