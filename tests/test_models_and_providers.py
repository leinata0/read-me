import pytest

from app.generator import _build_analysis_cache_key, build_readme_prompt
from app.models import (
    AnalyzeRequest,
    Dependency,
    FileSnapshot,
    ListModelsRequest,
    ProjectAnalysis,
    ProviderKeys,
    TestConnectionRequest as ConnectionRequestModel,
)
from app.providers import (
    ProviderError,
    _normalize_base_url,
    _ollama_connection_message,
    AnthropicProvider,
    _map_anthropic_error,
)


def test_normalize_base_url_rejects_metadata_host():
    with pytest.raises(ProviderError, match="blocked local or metadata"):
        _normalize_base_url("http://169.254.169.254/latest", "")


def test_normalize_base_url_rejects_non_https_remote_url():
    with pytest.raises(ProviderError, match="must use HTTPS"):
        _normalize_base_url("http://example.com/api", "")


def test_normalize_base_url_allows_ollama_localhost():
    assert _normalize_base_url("http://localhost:11434/v1", "", allow_localhost=True) == "http://localhost:11434/v1"


def test_provider_keys_clamp_limits_and_temperature():
    keys = ProviderKeys(max_tokens_analyze=10, max_tokens_generate=999999, temperature=9)
    assert keys.max_tokens_analyze == 1024
    assert keys.max_tokens_generate == 131072
    assert keys.temperature == 2.0


def test_analyze_request_trims_and_clamps_fields():
    req = AnalyzeRequest(source_type="local_path", folder_path="  .  ", provider="  openai  ", temperature=-1, toc_depth=99, model="  qwen  ")
    assert req.folder_path == "."
    assert req.provider == "openai"
    assert req.temperature == 0.0
    assert req.toc_depth == 4
    assert req.model == "qwen"


def test_analyze_request_requires_repo_url_for_repo_mode():
    with pytest.raises(Exception):
        AnalyzeRequest(source_type="repo_url", provider="openai")


def test_analyze_request_requires_folder_path_for_local_mode():
    with pytest.raises(Exception):
        AnalyzeRequest(source_type="local_path", provider="openai")


def test_analyze_request_supports_quality_mode_high():
    req = AnalyzeRequest(source_type="local_path", folder_path=".", provider="openai", quality_mode="high")
    assert req.quality_mode == "high"


def test_build_readme_prompt_includes_previous_readme_and_feedback():
    analysis = ProjectAnalysis(
        project_name="demo",
        description="demo project",
        languages=["python"],
        dependencies=[Dependency(name="fastapi")],
        entry_points=["app/main.py"],
        architecture_notes="notes",
    )
    snapshots = [
        FileSnapshot(
            path="/tmp/app/main.py",
            relative_path="app/main.py",
            language="python",
            content="print('hello')",
            size_bytes=14,
            is_config=False,
        )
    ]

    prompt = build_readme_prompt(
        analysis,
        snapshots,
        previous_readme="# Old README\n\nkeep this section",
        feedback="把简介缩短，并补一个 FAQ",
    )

    assert "## 当前版本 README（需要根据用户反馈修订）" in prompt
    assert "# Old README" in prompt
    assert "## 用户反馈" in prompt
    assert "把简介缩短，并补一个 FAQ" in prompt
    assert "只修改反馈中提到的问题" in prompt


def test_build_analysis_cache_key_includes_context_dimensions():
    snapshots = [
        FileSnapshot(
            path="/tmp/app/main.py",
            relative_path="app/main.py",
            language="python",
            content="print('hello')",
            size_bytes=14,
            is_config=False,
        )
    ]

    key_a = _build_analysis_cache_key(snapshots, "zh", "*.py", "", False)
    key_b = _build_analysis_cache_key(snapshots, "en", "*.py", "", False)
    key_c = _build_analysis_cache_key(snapshots, "zh", "*.py", "tests/*", False)
    key_d = _build_analysis_cache_key(snapshots, "zh", "*.py", "", True)

    assert key_a != key_b
    assert key_a != key_c
    assert key_a != key_d


def test_list_models_request_trims_base_url():
    req = ListModelsRequest(base_url="  https://example.com/v1  ")
    assert req.base_url == "https://example.com/v1"


def test_ollama_connection_message_for_localhost():
    msg = _ollama_connection_message("http://localhost:11434/v1")
    assert "Please start Ollama" in msg
    assert "localhost:11434" in msg


def test_build_readme_prompt_uses_entry_snippets_from_analysis_entry_points():
    analysis = ProjectAnalysis(
        project_name="demo",
        description="demo project",
        languages=["python"],
        dependencies=[Dependency(name="fastapi")],
        entry_points=["src/custom_entry.py"],
        architecture_notes="notes",
    )
    snapshots = [
        FileSnapshot(
            path="/tmp/src/custom_entry.py",
            relative_path="src/custom_entry.py",
            language="python",
            content="print('hello')\n" * 5,
            size_bytes=70,
            is_config=False,
        )
    ]

    prompt = build_readme_prompt(analysis, snapshots)

    assert "## Representative Source Files and Docs" in prompt
    assert "src/custom_entry.py" in prompt


def test_map_generic_error_uses_ollama_specific_message():
    from app.providers import _map_generic_error

    err = _map_generic_error(RuntimeError("connection refused"), "Ollama", "http://localhost:11434/v1")
    assert err.code == 503
    assert "Please start Ollama" in err.message




def test_anthropic_provider_exposes_request_and_env_debug_context(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://env-proxy.example.com/v1")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "sk-env-bearer-token")
    provider = AnthropicProvider(api_key="sk-ant-demo", model="claude-sonnet-4-6")
    assert provider.resolved_api_key_source == "request"
    assert provider.resolved_base_url_source == "env"
    assert provider.resolved_base_url == "https://env-proxy.example.com/v1"
    assert provider.debug_context["uses_custom_base_url"] is True
    assert provider.debug_context["key_preview"].startswith("sk-ant")
    assert provider.debug_context["request_key_preview"].startswith("sk-ant")
    assert provider.client.auth_token is None
    assert "Authorization" not in provider.client.auth_headers


class _AnthropicAuthError(Exception):
    pass


def test_map_anthropic_error_mentions_base_url_context():
    err = _map_anthropic_error(_AnthropicAuthError("auth"), "https://proxy.example.com/v1", "request")
    assert err.code == 500 or err.code == 401
    if err.code == 401:
        assert "Base URL: https://proxy.example.com/v1" in err.message
        assert "proxy/gateway configuration issue" in err.message


def test_prioritize_group_files_keeps_backend_core_files():
    from app.analyzer import prioritize_group_files

    snapshots = [
        FileSnapshot(path="/tmp/app/main.py", relative_path="app/main.py", language="python", content="x" * 4000, size_bytes=4000, is_config=False),
        FileSnapshot(path="/tmp/app/generator.py", relative_path="app/generator.py", language="python", content="x" * 4000, size_bytes=4000, is_config=False),
        FileSnapshot(path="/tmp/app/providers.py", relative_path="app/providers.py", language="python", content="x" * 4000, size_bytes=4000, is_config=False),
    ]

    selected = prioritize_group_files("backend", snapshots, max_tokens=2000)

    selected_paths = [item.relative_path for item in selected]
    assert "app/main.py" in selected_paths
    assert "app/generator.py" in selected_paths


def test_prioritize_group_files_keeps_frontend_app_js_first():
    from app.analyzer import prioritize_group_files

    snapshots = [
        FileSnapshot(path="/tmp/app/static/style.css", relative_path="app/static/style.css", language="text", content="x" * 4000, size_bytes=4000, is_config=False),
        FileSnapshot(path="/tmp/app/static/app.js", relative_path="app/static/app.js", language="javascript", content="x" * 4000, size_bytes=4000, is_config=False),
        FileSnapshot(path="/tmp/app/templates/index.html", relative_path="app/templates/index.html", language="html", content="x" * 4000, size_bytes=4000, is_config=False),
    ]

    selected = prioritize_group_files("frontend", snapshots, max_tokens=2000)

    assert selected[0].relative_path == "app/static/app.js"
