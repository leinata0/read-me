from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class ProviderKeys(BaseModel):
    """API keys and base URLs for a single provider, sent from frontend."""
    api_key: str = ""
    base_url: str = ""
    max_tokens_analyze: int = 16384
    max_tokens_generate: int = 32768
    temperature: float = 0.7

    @field_validator("base_url")
    @classmethod
    def validate_base_url_length(cls, value: str) -> str:
        return value.strip()[:500]

    @field_validator("max_tokens_analyze", "max_tokens_generate")
    @classmethod
    def validate_max_tokens(cls, value: int) -> int:
        return min(max(value, 1024), 131072)

    @field_validator("temperature")
    @classmethod
    def validate_temperature(cls, value: float) -> float:
        return min(max(value, 0.0), 2.0)


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
    feedback: str = ""
    previous_readme: str = ""
    badge_style: str = "shields"
    toc_depth: int = 2
    code_examples: str = "normal"
    link_style: str = "inline"
    section_order: str = ""
    audience: str = "developer"

    @field_validator("folder_path")
    @classmethod
    def validate_folder_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("folder_path is required")
        return value[:500]

    @field_validator(
        "provider", "model", "tone", "custom_sections", "exclude_sections", "custom_prompt_suffix",
        "include_patterns", "exclude_patterns", "feedback", "previous_readme", "badge_style",
        "code_examples", "link_style", "section_order", "audience",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()

    @field_validator("temperature")
    @classmethod
    def validate_request_temperature(cls, value: float) -> float:
        return min(max(value, 0.0), 2.0)

    @field_validator("toc_depth")
    @classmethod
    def validate_toc_depth(cls, value: int) -> int:
        return min(max(value, 1), 4)


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
    category: str = "runtime"


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

    @field_validator("base_url")
    @classmethod
    def trim_base_url(cls, value: str) -> str:
        return value.strip()[:500]


class ListModelsResponse(BaseModel):
    models: list[str]
    source: str
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
