from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models import ProviderError


client = TestClient(app)


def test_api_analyze_rejects_sensitive_directory(monkeypatch):
    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())

    response = client.post(
        "/api/analyze",
        json={
            "source_type": "local_path",
            "folder_path": str(Path.home() / "Downloads"),
            "provider": "ollama",
            "model": "qwen2.5:7b",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "event: error" in body
    assert '"code": 400' in body
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
            "source_type": "local_path",
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
            "source_type": "local_path",
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


def test_api_analyze_repo_url_mode_calls_repo_resolver(monkeypatch):
    captured = {}

    class StubProvider:
        model = "qwen2.5:7b"
        name = "ollama"

    async def fake_run_pipeline(**kwargs):
        captured.update(kwargs)
        from app.models import GenerateResponse
        return GenerateResponse(readme="# repo", model="qwen2.5:7b", provider="ollama")

    async def fake_download_repo(repo_url):
        captured["repo_url"] = repo_url
        return str(Path.cwd()), None

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubProvider())
    monkeypatch.setattr("app.main.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr("app.main._download_github_repo_to_tempdir", fake_download_repo)

    response = client.post(
        "/api/analyze",
        json={
            "source_type": "repo_url",
            "repo_url": "https://github.com/example/project",
            "provider": "ollama",
            "model": "qwen2.5:7b",
            "quality_mode": "high",
        },
    )

    assert response.status_code == 200
    body = response.text
    assert "event: done" in body
    assert captured["repo_url"] == "https://github.com/example/project"
    assert captured["folder_path"] == str(Path.cwd())
    assert captured["quality_mode"] == "high"


def test_api_test_connection_returns_provider_error(monkeypatch):
    def fake_get_provider(*args, **kwargs):
        raise ProviderError(
            503,
            "Cannot reach Ollama at http://localhost:11434/v1. "
            "Please start Ollama and confirm the model server is listening.",
        )

    monkeypatch.setattr("app.main.get_provider", fake_get_provider)

    response = client.post(
        "/api/test-connection",
        json={
            "provider": "ollama",
            "model": "qwen2.5:7b",
        },
    )

    assert response.status_code == 503
    data = response.json()
    assert data["ok"] is False
    assert data["code"] == 503
    assert "Please start Ollama" in data["message"]


def test_api_test_connection_accepts_request_base_url_without_local_key(monkeypatch):
    captured = {}

    def fake_get_provider(provider_name, model=None, api_keys=None, temperature=0.7):
        captured["provider_name"] = provider_name
        captured["api_keys"] = api_keys

        class StubProvider:
            name = "anthropic"
            debug_context = {
                "provider": "anthropic",
                "model": model or "claude-sonnet-4-6",
                "key_source": "env",
                "base_url_source": "request",
                "base_url": "https://proxy.example.com/anthropic",
            }

            def __init__(self):
                self.model = model or "claude-sonnet-4-6"

            async def analyze(self, **kwargs):
                return {"status": "ok"}

        return StubProvider()

    monkeypatch.setattr("app.main.get_provider", fake_get_provider)

    response = client.post(
        "/api/test-connection",
        json={
            "provider": "anthropic",
            "api_keys": {
                "anthropic": {
                    "base_url": "https://proxy.example.com/anthropic"
                }
            },
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert captured["provider_name"] == "anthropic"
    assert captured["api_keys"]["anthropic"].base_url == "https://proxy.example.com/anthropic"


def test_api_test_connection_returns_anthropic_debug_context(monkeypatch):
    class StubAnthropicProvider:
        model = "claude-sonnet-4-6"
        name = "anthropic"
        debug_context = {
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "key_source": "request",
            "base_url_source": "env",
            "base_url": "https://proxy.example.com/v1",
            "uses_custom_base_url": True,
        }

        async def analyze(self, **kwargs):
            raise ProviderError(
                401,
                "Anthropic authentication failed. This may be caused by an invalid API key, an incompatible Base URL, or a proxy/gateway configuration issue. Current Base URL: https://proxy.example.com/v1 (source: env).",
            )

    monkeypatch.setattr("app.main.get_provider", lambda *args, **kwargs: StubAnthropicProvider())

    response = client.post(
        "/api/test-connection",
        json={
            "provider": "anthropic",
            "model": "claude-sonnet-4-6",
            "api_keys": {
                "anthropic": {
                    "api_key": "sk-ant-demo",
                }
            },
        },
    )

    assert response.status_code == 401
    data = response.json()
    assert data["ok"] is False
    assert "proxy/gateway configuration issue" in data["message"]
    assert data["debug"]["provider"] == "anthropic"
    assert data["debug"]["has_request_key"] is True
    assert data["debug"]["key_source"] == "request"
    assert data["debug"]["base_url_source"] == "env"
    assert data["debug"]["base_url"] == "https://proxy.example.com/v1"
