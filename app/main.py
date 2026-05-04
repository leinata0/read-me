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


@app.post("/api/test-connection")
async def api_test_connection(req: AnalyzeRequest):
    """Test if the API key and connection work for the selected provider."""
    import time as _time
    try:
        provider = get_provider(req.provider, req.model, req.api_keys)
        start = _time.time()
        result = await provider.analyze(
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
        })
    except ProviderError as e:
        return JSONResponse(status_code=e.code, content={
            "ok": False,
            "code": e.code,
            "message": e.message,
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "ok": False,
            "code": 500,
            "message": f"测试失败: {str(e)[:200]}",
        })


@app.post("/api/analyze")
async def api_analyze(req: AnalyzeRequest):
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    _step_map = {
        "校验": "validate", "路径": "validate", "Validating": "validate",
        "读取": "read", "Reading": "read", "Found": "read",
        "分析": "analyze", "Analyzing": "analyze", "cached": "analyze",
        "生成": "generate", "Generating": "generate", "README": "generate",
    }

    async def on_progress(detail: str):
        step = ""
        for keyword, step_name in _step_map.items():
            if keyword in detail:
                step = step_name
                break
        data = json.dumps({"detail": detail, "step": step}, ensure_ascii=False)
        await queue.put(f"event: progress\ndata: {data}\n\n")

    async def on_chunk(text: str):
        data = json.dumps({"text": text}, ensure_ascii=False)
        await queue.put(f"event: chunk\ndata: {data}\n\n")

    async def background_task():
        try:
            provider = get_provider(req.provider, req.model, req.api_keys, req.temperature)
            result = await run_pipeline(
                folder_path=req.folder_path,
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


