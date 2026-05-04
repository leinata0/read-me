from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import ProviderError


client = TestClient(app)


def test_api_analyze_rejects_sensitive_directory():
    response = client.post(
        "/api/analyze",
        json={
            "folder_path": str(Path.home() / "Downloads"),
            "provider": "ollama",
            "model": "qwen2.5:7b",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "event: error" in body
    assert "personal or sensitive directory" in body


def test_api_analyze_passes_previous_readme_to_pipeline(monkeypatch):
    captured = {}

    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    async def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        from app.models import GenerateResponse
        return GenerateResponse(readme="# updated", model="qwen2.5:7b", provider="ollama")

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())
    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)

    response = client.post(
        "/api/analyze",
        json={
            "folder_path": str(Path.cwd()),
            "provider": "ollama",
            "model": "qwen2.5:7b",
            "feedback": "补一个 FAQ",
            "previous_readme": "# Old README\n\nkeep this",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "event: done" in body
    assert captured["feedback"] == "补一个 FAQ"
    assert captured["previous_readme"] == "# Old README\n\nkeep this"
    assert captured["folder_path"] == str(Path.cwd())
    assert captured["provider"].name == "ollama"


def test_api_analyze_emits_progress_chunk_and_done(monkeypatch):
    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    async def fake_run_pipeline(**kwargs):
        await kwargs["on_progress"]("正在读取项目文件...")
        await kwargs["on_chunk"]("# Title")
        from app.models import GenerateResponse
        return GenerateResponse(readme="# Title", model="qwen2.5:7b", provider="ollama")

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())
    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)

    response = client.post(
        "/api/analyze",
        json={
            "folder_path": str(Path.cwd()),
            "provider": "ollama",
            "model": "qwen2.5:7b",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "event: progress" in body
    assert '"step": "read"' in body
    assert "event: chunk" in body
    assert '# Title' in body
    assert "event: done" in body


def test_api_test_connection_returns_provider_error(monkeypatch):
    def fake_get_provider(*args, **kwargs):
        raise ProviderError(503, "Cannot reach Ollama at http://localhost:11434/v1. Please start Ollama and confirm the model server is listening.")

    monkeypatch.setattr("app.main.get_provider", fake_get_provider)

    response = client.post(
        "/api/test-connection",
        json={
            "folder_path": ".",
            "provider": "ollama",
            "model": "qwen2.5:7b",
        },
    )

    assert response.status_code == 503
    data = response.json()
    assert data["ok"] is False
    assert data["code"] == 503
    assert "Please start Ollama" in data["message"]
