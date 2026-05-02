from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, StreamingResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.models import AnalyzeRequest, ProviderError, ListModelsRequest, ListModelsResponse
from app.providers import get_provider, list_providers, PROVIDERS
from app.generator import run_pipeline

load_dotenv()
logging.basicConfig(level=logging.INFO)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="README Generator")


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


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def on_progress(detail: str):
        data = json.dumps({"detail": detail}, ensure_ascii=False)
        await queue.put(f"event: progress\ndata: {data}\n\n")

    async def on_chunk(text: str):
        data = json.dumps({"text": text}, ensure_ascii=False)
        await queue.put(f"event: chunk\ndata: {data}\n\n")

    async def background_task():
        try:
            provider = get_provider(req.provider, req.model, req.api_keys)
            result = await run_pipeline(
                folder_path=req.folder_path,
                provider=provider,
                on_progress=on_progress,
                on_chunk=on_chunk,
                language=req.language,
            )
            done_data = json.dumps({"model": result.model, "provider": result.provider}, ensure_ascii=False)
            await queue.put(f"event: done\ndata: {done_data}\n\n")
        except ProviderError as e:
            detail = e.message
            detail += f" (渠道: {req.provider}, 模型: {req.model or '默认'})"
            keys = (req.api_keys or {}).get(req.provider or "")
            if keys and keys.base_url:
                detail += f", Base URL: {keys.base_url}"
            err = json.dumps({"code": e.code, "message": detail}, ensure_ascii=False)
            await queue.put(f"event: error\ndata: {err}\n\n")
        except (FileNotFoundError, ValueError) as e:
            err = json.dumps({"code": 404, "message": str(e)}, ensure_ascii=False)
            await queue.put(f"event: error\ndata: {err}\n\n")
        except PermissionError as e:
            err = json.dumps({"code": 403, "message": f"Permission denied: {e}"}, ensure_ascii=False)
            await queue.put(f"event: error\ndata: {err}\n\n")
        except Exception as e:
            err = json.dumps({"code": 500, "message": str(e)[:300]}, ensure_ascii=False)
            await queue.put(f"event: error\ndata: {err}\n\n")
        finally:
            await queue.put(None)

    async def event_stream() -> AsyncGenerator[str, None]:
        task = asyncio.create_task(background_task())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item
        await task

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/download")
async def api_download(request: Request):
    body = await request.json()
    content = body.get("content", "")
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="README.md"'},
    )
