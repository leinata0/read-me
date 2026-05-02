from __future__ import annotations

import json
import time
from typing import Callable, Awaitable

from app.analyzer import (
    validate_path, load_gitignore_patterns, traverse_project,
    estimate_total_tokens, compute_project_hash, prioritize_files,
)
from app.models import FileSnapshot, ProjectAnalysis, GenerateResponse
from app.providers import AIProvider

ANALYSIS_SYSTEM_PROMPT = """\
You are an expert software engineer analyzing a codebase. Your task is to extract structured information about the project.

Be thorough and accurate. Identify:
- The exact project name (from package.json, pyproject.toml, setup.py, or directory name)
- A concise but informative description of what the project does
- All programming languages used
- All dependencies with their categories (runtime/dev/test)
- Entry point files (main scripts, server files, CLI entry points)
- Key architectural patterns and design decisions
"""

GENERATION_SYSTEM_PROMPT = """\
You are a technical writer creating a high-quality README.md for a software project.

Requirements:
- Write a compelling project description (not generic, specific to this project)
- Include a table of contents
- Installation section with exact commands for the project's language/ecosystem
- Usage section with realistic, runnable code examples
- Dependencies section listing key runtime dependencies
- Brief architecture overview
- License section if detectable
- Badge suggestions appropriate for the language/ecosystem
- If an existing README was found, preserve any important content not covered above
- Use proper markdown formatting with headers, code blocks, links
- Make it production-ready, not a template
"""

_analysis_cache: dict[str, tuple[ProjectAnalysis, float]] = {}
CACHE_TTL = 30 * 60  # 30 minutes


def _get_project_analysis_schema() -> dict:
    return ProjectAnalysis.model_json_schema()


def build_analysis_prompt(snapshots: list[FileSnapshot], existing_readme: str | None) -> str:
    parts = ["## Project Files\n"]
    for snap in snapshots:
        lang = snap.language if snap.language != "unknown" else ""
        parts.append(f"### {snap.relative_path}")
        if lang:
            parts.append(f"```{lang}")
        else:
            parts.append("```")
        parts.append(snap.content)
        parts.append("```\n")

    if existing_readme:
        parts.append("## Existing README (preserve important content)\n")
        parts.append(existing_readme)
    else:
        parts.append("## Existing README\nNo existing README found.")

    parts.append(
        "\n## Instructions\n"
        "Extract: project name, concise description, programming languages used, "
        "all dependencies with their categories (runtime/dev/test), entry points, "
        "key architectural patterns, and any notable features."
    )
    return "\n".join(parts)


def build_readme_prompt(analysis: ProjectAnalysis, snapshots: list[FileSnapshot]) -> str:
    parts = ["## Project Analysis\n"]
    analysis_md = f"- **Name**: {analysis.project_name}\n"
    analysis_md += f"- **Description**: {analysis.description}\n"
    analysis_md += f"- **Languages**: {', '.join(analysis.languages)}\n"
    analysis_md += f"- **Entry Points**: {', '.join(analysis.entry_points)}\n"
    analysis_md += f"- **Architecture**: {analysis.architecture_notes}\n"
    analysis_md += "\n### Dependencies\n"
    for dep in analysis.dependencies:
        analysis_md += f"- {dep.name} ({dep.category})\n"
    parts.append(analysis_md)

    entry_snippets: list[FileSnapshot] = []
    entry_names = {"main", "app", "index", "server", "cli", "run"}
    for snap in snapshots:
        stem = snap.relative_path.split("/")[-1].split("\\")[-1].rsplit(".", 1)[0].lower()
        if stem in entry_names or snap.relative_path in analysis.entry_points:
            entry_snippets.append(snap)
            if len(entry_snippets) >= 3:
                break

    if entry_snippets:
        parts.append("\n## Key Source Files (for usage examples)\n")
        for snap in entry_snippets:
            lines = snap.content.split("\n")
            snippet = "\n".join(lines[:80])
            lang = snap.language if snap.language != "unknown" else ""
            parts.append(f"### {snap.relative_path}")
            parts.append(f"```{lang}")
            parts.append(snippet)
            if len(lines) > 80:
                parts.append(f"... ({len(lines) - 80} more lines)")
            parts.append("```\n")

    if analysis.existing_readme:
        parts.append("\n## Existing README Content (preserve important parts)\n")
        parts.append(analysis.existing_readme)

    return "\n".join(parts)


async def analyze_project(
    provider: AIProvider,
    snapshots: list[FileSnapshot],
    existing_readme: str | None,
    on_progress: Callable[[str], Awaitable[None]],
) -> ProjectAnalysis:
    project_hash = compute_project_hash(snapshots)
    cached = _analysis_cache.get(project_hash)
    if cached and (time.time() - cached[1]) < CACHE_TTL:
        await on_progress("Using cached analysis...")
        return cached[0]

    await on_progress("Analyzing project structure...")

    total_tokens = estimate_total_tokens(snapshots)
    if total_tokens > 300_000:
        snapshots = prioritize_files(snapshots, max_tokens=150_000)

    user_prompt = build_analysis_prompt(snapshots, existing_readme)
    schema = _get_project_analysis_schema()

    result = await provider.analyze(ANALYSIS_SYSTEM_PROMPT, user_prompt, schema)
    analysis = ProjectAnalysis(**result)
    analysis.existing_readme = existing_readme

    _analysis_cache[project_hash] = (analysis, time.time())
    return analysis


async def generate_readme(
    provider: AIProvider,
    analysis: ProjectAnalysis,
    snapshots: list[FileSnapshot],
    on_progress: Callable[[str], Awaitable[None]],
    on_chunk: Callable[[str], Awaitable[None]],
) -> str:
    await on_progress("Generating README...")

    user_prompt = build_readme_prompt(analysis, snapshots)
    return await provider.generate_stream(GENERATION_SYSTEM_PROMPT, user_prompt, on_chunk)


async def run_pipeline(
    folder_path: str,
    provider: AIProvider,
    on_progress: Callable[[str], Awaitable[None]],
    on_chunk: Callable[[str], Awaitable[None]],
) -> GenerateResponse:
    await on_progress("Validating project path...")
    resolved = validate_path(folder_path)

    await on_progress("Reading project files...")
    gitignore = load_gitignore_patterns(resolved)
    snapshots, existing_readme = traverse_project(resolved, gitignore)

    if not snapshots:
        raise ValueError("No source files found in this project. Ensure the folder contains code files.")

    await on_progress(f"Found {len(snapshots)} source files. Analyzing...")

    analysis = await analyze_project(provider, snapshots, existing_readme, on_progress)

    readme = await generate_readme(provider, analysis, snapshots, on_progress, on_chunk)

    return GenerateResponse(
        readme=readme,
        model=provider.model,
        provider=provider.name,
    )
