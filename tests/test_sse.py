import asyncio
from pathlib import Path

import pytest

from app.main import api_analyze
from app.models import AnalyzeRequest, GenerateResponse


class DisconnectingRequest:
    def __init__(self):
        self.calls = 0

    async def is_disconnected(self):
        self.calls += 1
        return self.calls > 1


class ConnectedRequest:
    async def is_disconnected(self):
        return False


@pytest.mark.asyncio
async def test_api_analyze_stops_stream_on_disconnect(monkeypatch):
    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    async def fake_run_pipeline(**kwargs):
        await asyncio.sleep(5)
        return GenerateResponse(readme="# never", model="qwen2.5:7b", provider="ollama")

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())
    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)

    req = AnalyzeRequest(source_type="local_path", folder_path=str(Path.cwd()), provider="ollama", model="qwen2.5:7b")
    response = await api_analyze(req, DisconnectingRequest())

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    assert chunks == []


@pytest.mark.asyncio
async def test_api_analyze_emits_keep_alive_when_idle(monkeypatch):
    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    async def fake_run_pipeline(**kwargs):
        await asyncio.sleep(0.05)
        return GenerateResponse(readme="# done", model="qwen2.5:7b", provider="ollama")

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())
    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("app.main.SSE_HEARTBEAT_SECONDS", 0.01)

    req = AnalyzeRequest(source_type="local_path", folder_path=str(Path.cwd()), provider="ollama", model="qwen2.5:7b")
    response = await api_analyze(req, ConnectedRequest())

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    assert any(chunk == ': keep-alive\n\n' for chunk in chunks)
    assert any('event: done' in chunk for chunk in chunks)
