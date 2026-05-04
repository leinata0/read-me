from __future__ import annotations

from pydantic import BaseModel, Field


class ProviderKeys(BaseModel):
    """API keys and base URLs for a single provider, sent from frontend."""
    api_key: str = ""
    base_url: str = ""
    max_tokens_analyze: int = 16384
    max_tokens_generate: int = 32768
    temperature: float = 0.7


class AnalyzeRequest(BaseModel):
    folder_path: str
    provider: str | None = None
    model: str | None = None
    api_keys: dict[str, ProviderKeys] = Field(default_factory=dict)
    language: str = "zh"
    temperature: float = 0.7
    tone: str = "professional"
    custom_sections: str = ""
    exclude_sections: str = ""
    include_badges: bool = True
    custom_prompt_suffix: str = ""
    include_patterns: str = ""
    exclude_patterns: str = ""
    # 反馈式重新生成
    feedback: str = ""
    previous_readme: str = ""
    # 细致选项
    badge_style: str = "shields"  # shields / shields-flat / badgen
    toc_depth: int = 2  # 1-4
    code_examples: str = "normal"  # minimal / normal / detailed
    link_style: str = "inline"  # inline / reference
    section_order: str = ""  # 自定义章节顺序
    audience: str = "developer"  # developer / user / contributor


class ProviderInfo(BaseModel):
    name: str
    display_name: str
    available_models: list[str]
    is_configured: bool
    base_url_hint: str = ""
    env_key_hint: str = ""


class FileSnapshot(BaseModel):
    path: str
    relative_path: str
    language: str
    content: str
    size_bytes: int
    is_config: bool


class Dependency(BaseModel):
    name: str
    category: str = "runtime"  # runtime | dev | test


class ProjectAnalysis(BaseModel):
    project_name: str
    description: str
    languages: list[str]
    dependencies: list[Dependency]
    entry_points: list[str]
    architecture_notes: str
    existing_readme: str | None = None


class ListModelsRequest(BaseModel):
    api_key: str = ""
    base_url: str = ""


class ListModelsResponse(BaseModel):
    models: list[str]
    source: str  # "fetched" | "fallback"
    error: str = ""


class GenerateResponse(BaseModel):
    readme: str
    model: str
    provider: str


class ProviderError(Exception):
    def __init__(self, code: int, message: str):
        self.code = code
        self.message = message
        super().__init__(message)
