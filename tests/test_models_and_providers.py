import pytest

from app.generator import _build_analysis_cache_key, build_readme_prompt
from app.models import (
    AnalyzeRequest,
    Dependency,
    FileSnapshot,
    ListModelsRequest,
    ProjectAnalysis,
    ProviderKeys,
)
from app.providers import (
    ProviderError,
    _map_generic_error,
    _normalize_base_url,
    _ollama_connection_message,
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
    req = AnalyzeRequest(folder_path="  .  ", temperature=-1, toc_depth=99, model="  qwen  ")
    assert req.folder_path == "."
    assert req.temperature == 0.0
    assert req.toc_depth == 4
    assert req.model == "qwen"


def test_analyze_request_rejects_invalid_enum_values():
    with pytest.raises(Exception):
        AnalyzeRequest(folder_path='.', language='fr', tone='formal')


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


def test_map_generic_error_uses_ollama_specific_message():
    err = _map_generic_error(RuntimeError("connection refused"), "Ollama", "http://localhost:11434/v1")
    assert err.code == 503
    assert "Please start Ollama" in err.message
