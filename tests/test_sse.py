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


@pytest.mark.asyncio
async def test_api_analyze_cancels_background_task_on_disconnect(monkeypatch):
    cancelled = asyncio.Event()

    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    async def fake_run_pipeline(**kwargs):
        try:
            await asyncio.sleep(5)
            return GenerateResponse(readme="# never", model="qwen2.5:7b", provider="ollama")
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())
    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)

    req = AnalyzeRequest(folder_path=str(Path.cwd()), provider="ollama", model="qwen2.5:7b")
    response = await api_analyze(req, DisconnectingRequest())

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)

    assert chunks == []
    assert cancelled.is_set()
