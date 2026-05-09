from __future__ import annotations

import asyncio
import json
import time
from typing import Callable, Awaitable

from app.analyzer import (
    validate_path, load_gitignore_patterns, traverse_project,
    estimate_total_tokens, compute_project_hash, prioritize_files,
    split_analysis_groups, should_use_concurrent_analysis, prioritize_group_files,
    ENTRY_NAMES,
)
from app.models import FileSnapshot, ProjectAnalysis, GenerateResponse
from app.providers import AIProvider, _retry_on_transient

ANALYSIS_SYSTEM_PROMPT_ZH = """\
你是一名资深软件工程师，正在分析一个代码仓库。你的任务是提取项目的结构化信息。

请准确识别以下内容：
- 项目名称（从 package.json、pyproject.toml、setup.py 或目录名中提取）
- 项目功能的简洁描述（用中文）
- 使用的所有编程语言
- 所有依赖及其分类（运行时/开发/测试）
- 入口文件（主脚本、服务器文件、CLI 入口）
- 关键架构模式和设计决策
- README 应该覆盖的真实使用方式、部署方式、配置方式、开发方式
- 项目中最值得展示的代码路径和示例来源
"""

ANALYSIS_SYSTEM_PROMPT_EN = """\
You are an expert software engineer analyzing a codebase. Your task is to extract structured information about the project.

Be thorough and accurate. Identify:
- The exact project name (from package.json, pyproject.toml, setup.py, or directory name)
- A concise but informative description of what the project does
- All programming languages used
- All dependencies with their categories (runtime/dev/test)
- Entry point files (main scripts, server files, CLI entry points)
- Key architectural patterns and design decisions
- The real usage, deployment, configuration, and development workflows the README should explain
- The most representative code paths and example sources worth showing in the README
"""

GENERATION_SYSTEM_PROMPT_ZH = """\
你是一名技术文档专家，正在为一个软件项目编写高质量的 README.md。

要求：
- 用中文撰写（代码块、命令、技术术语保持英文原文）
- 写一段有吸引力且准确的项目描述，必须基于项目真实实现，而不是模板化概括
- 包含目录
- 安装章节：使用项目语言/生态系统的精确命令
- 使用章节：提供真实、可运行、贴近项目结构的代码示例
- 依赖章节：列出关键运行时依赖
- 简要架构概述
- 检测到 License 时添加许可证章节
- 添加适合该语言/生态系统的 badge
- 如果发现了已有的 README，保留其中未涵盖的重要内容
- 使用规范的 Markdown 格式：标题、代码块、链接
- 输出应是生产级别的，而非模板
- 如果信息不足，不要编造；优先根据上下文谨慎表述
"""

GENERATION_SYSTEM_PROMPT_EN = """\
You are a technical writer creating a high-quality README.md for a software project.

Requirements:
- Write a compelling and accurate project description grounded in the real implementation, not a template summary
- Include a table of contents
- Installation section with exact commands for the project's language/ecosystem
- Usage section with realistic, runnable code examples aligned with the actual project structure
- Dependencies section listing key runtime dependencies
- Brief architecture overview
- License section if detectable
- Badge suggestions appropriate for the language/ecosystem
- If an existing README was found, preserve any important content not covered above
- Use proper markdown formatting with headers, code blocks, links
- Make it production-ready, not a template
- If information is incomplete, do not invent details; prefer cautious, evidence-based phrasing
"""

GROUP_ANALYSIS_BUDGETS = {
    "config": 8_000,
    "backend": 18_000,
    "frontend": 14_000,
    "tests": 6_000,
    "docs": 8_000,
}

GROUP_ANALYSIS_INSTRUCTIONS = {
    "config": {
        "zh": "重点提取项目名称、依赖、安装运行方式、环境配置、部署方式和 CI/工作流信息。",
        "en": "Focus on project name, dependencies, installation/run commands, environment config, deployment shape, and CI/workflow details.",
    },
    "backend": {
        "zh": "重点提取后端入口、核心调用链、服务能力、数据模型、接口约定和架构要点。",
        "en": "Focus on backend entry points, call flows, service capabilities, data models, interface contracts, and architectural decisions.",
    },
    "frontend": {
        "zh": "重点提取用户界面能力、前端交互流程、设置项和用户可见功能。",
        "en": "Focus on user-facing UI capabilities, interaction flows, settings, and visible product features.",
    },
    "tests": {
        "zh": "重点提取测试命令、验证方式、开发/调试辅助信息，以及 README 中应保留的重要说明。",
        "en": "Focus on test commands, verification methods, developer/debugging hints, and important README-worthy notes.",
    },
    "docs": {
        "zh": "重点提取现有文档、示例、FAQ、运维说明和对 README 有帮助的解释性内容。",
        "en": "Focus on existing docs, examples, FAQ, ops notes, and explanatory content useful for the README.",
    },
}

_analysis_cache: dict[str, tuple[ProjectAnalysis, float]] = {}
CACHE_TTL = 10 * 60
CACHE_MAX_SIZE = 50


def _evict_expired_cache() -> None:
    now = time.time()
    expired = [k for k, (_, ts) in _analysis_cache.items() if now - ts >= CACHE_TTL]
    for k in expired:
        del _analysis_cache[k]
    if len(_analysis_cache) > CACHE_MAX_SIZE:
        sorted_keys = sorted(_analysis_cache, key=lambda k: _analysis_cache[k][1])
        for k in sorted_keys[:len(_analysis_cache) - CACHE_MAX_SIZE]:
            del _analysis_cache[k]


def _build_analysis_cache_key(
    snapshots: list[FileSnapshot],
    language: str,
    include_patterns: str = "",
    exclude_patterns: str = "",
    feedback_mode: bool = False,
    existing_readme: str | None = None,
    quality_mode: str = "balanced",
) -> str:
    base_hash = compute_project_hash(snapshots)
    readme_hash = ""
    if existing_readme:
        readme_hash = compute_project_hash([
            FileSnapshot(
                path="existing_readme",
                relative_path="README.md",
                language="markdown",
                content=existing_readme,
                size_bytes=len(existing_readme.encode("utf-8")),
                is_config=False,
            )
        ])
    return "|".join([
        base_hash,
        language,
        include_patterns.strip(),
        exclude_patterns.strip(),
        "feedback" if feedback_mode else "normal",
        quality_mode,
        readme_hash,
    ])


def _get_project_analysis_schema() -> dict:
    return ProjectAnalysis.model_json_schema()


def _select_readme_support_files(snapshots: list[FileSnapshot], analysis: ProjectAnalysis, quality_mode: str = "balanced") -> list[FileSnapshot]:
    selected: list[FileSnapshot] = []
    seen: set[str] = set()
    rel_lookup = {snap.relative_path.replace("\\", "/").lower(): snap for snap in snapshots}

    def add(snapshot: FileSnapshot | None) -> None:
        if snapshot is None:
            return
        if snapshot.relative_path in seen:
            return
        seen.add(snapshot.relative_path)
        selected.append(snapshot)

    normalized_entries = {
        entry.replace("\\", "/").lower()
        for entry in analysis.entry_points
    }

    candidate_paths: list[str] = []
    for rel_path, snap in rel_lookup.items():
        if snap.is_config:
            candidate_paths.append(rel_path)
            continue
        if rel_path in normalized_entries:
            candidate_paths.append(rel_path)
            continue
        if rel_path.endswith(("readme.md", "readme", "package.json", "pyproject.toml", "requirements.txt", "go.mod", "cargo.toml", "dockerfile", "docker-compose.yml", "docker-compose.yaml")):
            candidate_paths.append(rel_path)
            continue
        if any(token in rel_path for token in ["routes", "router", "api", "service", "handler", "controller", "command", "cli", "main", "server", "app."]):
            candidate_paths.append(rel_path)
            continue
        if rel_path.startswith(("docs/", "examples/")):
            candidate_paths.append(rel_path)
            continue

    for rel_path in candidate_paths:
        add(rel_lookup.get(rel_path))

    if quality_mode == "high":
        for snap in snapshots:
            rel_path = snap.relative_path.replace("\\", "/").lower()
            if any(segment in rel_path for segment in ["config", "settings", "schema", "model", "types", "auth", "deploy"]):
                add(snap)

    limit = 12 if quality_mode == "high" else 8
    return selected[:limit]


async def _analyze_snapshot_group(
    provider: AIProvider,
    group_name: str,
    snapshots: list[FileSnapshot],
    existing_readme: str | None,
    language: str,
) -> dict:
    selected = prioritize_group_files(group_name, snapshots, GROUP_ANALYSIS_BUDGETS.get(group_name, 8_000))
    group_prompt = build_analysis_prompt(selected, existing_readme)
    instruction = GROUP_ANALYSIS_INSTRUCTIONS[group_name]["zh" if language == "zh" else "en"]
    if language == "zh":
        group_prompt += f"\n\n## 本轮额外要求\n当前分析分组：{group_name}\n{instruction}"
    else:
        group_prompt += f"\n\n## Extra instructions\nCurrent analysis group: {group_name}\n{instruction}"

    schema = {
        "type": "object",
        "properties": {
            "project_name": {"type": "string"},
            "description": {"type": "string"},
            "languages": {"type": "array", "items": {"type": "string"}},
            "dependencies": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                    },
                    "required": ["name"],
                },
            },
            "entry_points": {"type": "array", "items": {"type": "string"}},
            "architecture_notes": {"type": "string"},
            "notable_features": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["project_name", "description", "languages", "dependencies", "entry_points", "architecture_notes"],
    }
    system_prompt = ANALYSIS_SYSTEM_PROMPT_ZH if language == "zh" else ANALYSIS_SYSTEM_PROMPT_EN
    return await _retry_on_transient(provider.analyze, system_prompt, group_prompt, schema)


async def _analyze_project_concurrently(
    provider: AIProvider,
    snapshots: list[FileSnapshot],
    existing_readme: str | None,
    on_progress: Callable[[str], Awaitable[None]],
    language: str,
) -> ProjectAnalysis:
    groups = split_analysis_groups(snapshots)
    await on_progress(f"正在并发分析 {len(groups)} 个项目分组...")

    async def analyze_one(group_name: str, items: list[FileSnapshot]):
        await on_progress(f"正在分析 {group_name} 分组（{len(items)} 个文件）...")
        return group_name, await _analyze_snapshot_group(provider, group_name, items, existing_readme, language)

    results = await asyncio.gather(*(analyze_one(name, items) for name, items in groups.items()))
    merged = []
    for group_name, payload in results:
        merged.append({
            "group": group_name,
            "project_name": payload.get("project_name", ""),
            "description": payload.get("description", ""),
            "languages": payload.get("languages", []),
            "dependencies": payload.get("dependencies", []),
            "entry_points": payload.get("entry_points", []),
            "architecture_notes": payload.get("architecture_notes", ""),
            "notable_features": payload.get("notable_features", []),
        })

    if language == "zh":
        summary_prompt = (
            "## 分组分析结果\n" + json.dumps(merged, ensure_ascii=False, indent=2) +
            "\n\n## 任务\n请汇总以上各组分析结果，输出统一的项目结构化结论。不要丢掉关键架构、真实使用方式、部署和配置细节。"
        )
    else:
        summary_prompt = (
            "## Group analysis results\n" + json.dumps(merged, ensure_ascii=False, indent=2) +
            "\n\n## Task\nConsolidate the group analysis results into a single structured project analysis. Preserve key architecture, real usage, deployment, and configuration details."
        )
    schema = _get_project_analysis_schema()
    system_prompt = ANALYSIS_SYSTEM_PROMPT_ZH if language == "zh" else ANALYSIS_SYSTEM_PROMPT_EN
    result = await _retry_on_transient(provider.analyze, system_prompt, summary_prompt, schema)
    analysis = ProjectAnalysis(**result)
    analysis.existing_readme = existing_readme
    return analysis


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
        "key architectural patterns, notable features, real installation and usage flows, "
        "deployment/configuration expectations, and the best files to use as README examples."
    )
    return "\n".join(parts)


def build_readme_prompt(analysis: ProjectAnalysis, snapshots: list[FileSnapshot],
                        previous_readme: str = "", feedback: str = "", quality_mode: str = "balanced") -> str:
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

    support_files = _select_readme_support_files(snapshots, analysis, quality_mode)
    if support_files:
        parts.append("\n## Representative Source Files and Docs\n")
        line_limit = 180 if quality_mode == "high" else 120
        for snap in support_files:
            lines = snap.content.split("\n")
            snippet = "\n".join(lines[:line_limit])
            lang = snap.language if snap.language != "unknown" else ""
            parts.append(f"### {snap.relative_path}")
            parts.append(f"```{lang}")
            parts.append(snippet)
            if len(lines) > line_limit:
                parts.append(f"... ({len(lines) - line_limit} more lines)")
            parts.append("```\n")

    if analysis.existing_readme:
        parts.append("\n## Existing README Content (preserve important parts)\n")
        parts.append(analysis.existing_readme)

    if feedback and previous_readme:
        parts.append("\n## 当前版本 README（需要根据用户反馈修订）\n")
        parts.append(previous_readme)
        parts.append(f"\n## 用户反馈\n{feedback}")
        parts.append("\n请根据以上反馈对当前版本进行修订，保留好的部分，只修改反馈中提到的问题。")

    return "\n".join(parts)


async def analyze_project(
    provider: AIProvider,
    snapshots: list[FileSnapshot],
    existing_readme: str | None,
    on_progress: Callable[[str], Awaitable[None]],
    language: str = "zh",
    include_patterns: str = "",
    exclude_patterns: str = "",
    feedback_mode: bool = False,
    quality_mode: str = "balanced",
) -> ProjectAnalysis:
    if quality_mode != "high":
        _evict_expired_cache()
        cache_key = _build_analysis_cache_key(
            snapshots,
            language,
            include_patterns,
            exclude_patterns,
            feedback_mode,
            existing_readme,
            quality_mode,
        )
        cached = _analysis_cache.get(cache_key)
        if cached and (time.time() - cached[1]) < CACHE_TTL:
            await on_progress("使用缓存的分析结果...")
            return cached[0]
    else:
        cache_key = None

    await on_progress("正在分析项目结构...")

    if should_use_concurrent_analysis(snapshots):
        analysis = await _analyze_project_concurrently(provider, snapshots, existing_readme, on_progress, language)
    else:
        total_tokens = estimate_total_tokens(snapshots)
        if quality_mode == "high":
            if total_tokens > 60_000:
                snapshots = prioritize_files(snapshots, max_tokens=45_000)
        else:
            if total_tokens > 18_000:
                snapshots = prioritize_files(snapshots, max_tokens=14_000)

        user_prompt = build_analysis_prompt(snapshots, existing_readme)
        schema = _get_project_analysis_schema()
        system_prompt = ANALYSIS_SYSTEM_PROMPT_ZH if language == "zh" else ANALYSIS_SYSTEM_PROMPT_EN

        result = await _retry_on_transient(provider.analyze, system_prompt, user_prompt, schema)
        analysis = ProjectAnalysis(**result)
        analysis.existing_readme = existing_readme

    if cache_key:
        _analysis_cache[cache_key] = (analysis, time.time())
    return analysis


def _build_generation_prompt(language: str, tone: str, include_badges: bool,
                              custom_sections: str, exclude_sections: str,
                              custom_prompt_suffix: str,
                              badge_style: str = "shields", toc_depth: int = 2,
                              code_examples: str = "normal", link_style: str = "inline",
                              section_order: str = "", audience: str = "developer") -> str:
    base = GENERATION_SYSTEM_PROMPT_ZH if language == "zh" else GENERATION_SYSTEM_PROMPT_EN

    tone_map = {
        "professional": {"zh": "\n- 使用专业、正式的技术文档语气", "en": "\n- Use a professional, formal technical documentation tone"},
        "casual": {"zh": "\n- 使用轻松友好的语气，适合开源社区", "en": "\n- Use a casual, friendly tone suitable for open-source communities"},
        "technical": {"zh": "\n- 使用高度技术性的语气，面向资深开发者", "en": "\n- Use a highly technical tone targeting experienced developers"},
    }
    if tone in tone_map:
        base += tone_map[tone].get(language, tone_map[tone]["en"])

    if not include_badges:
        badge_line = "- 添加适合该语言/生态系统的 badge" if language == "zh" else "- Badge suggestions appropriate for the language/ecosystem"
        base = base.replace(badge_line, "")
    elif badge_style != "shields":
        if language == "zh":
            base += f"\n- 使用 {badge_style} 样式的 Badge"
        else:
            base += f"\n- Use {badge_style} style badges"

    if toc_depth < 2:
        if language == "zh":
            base += f"\n- 目录只显示到 h{toc_depth + 1} 级标题"
        else:
            base += f"\n- Table of contents should only include h{toc_depth + 1} and above"

    code_map = {
        "minimal": {"zh": "\n- 代码示例保持简洁，只展示核心用法", "en": "\n- Keep code examples minimal, showing only core usage"},
        "detailed": {"zh": "\n- 代码示例要详细，包含多种场景和完整的错误处理", "en": "\n- Provide detailed code examples with multiple scenarios and error handling"},
    }
    if code_examples in code_map:
        base += code_map[code_examples].get(language, code_map[code_examples]["en"])

    if link_style == "reference":
        if language == "zh":
            base += "\n- 使用 Markdown 引用式链接（reference-style links）"
        else:
            base += "\n- Use reference-style Markdown links"

    if section_order:
        if language == "zh":
            base += f"\n- 请按以下顺序排列章节：{section_order}"
        else:
            base += f"\n- Arrange sections in this order: {section_order}"

    audience_map = {
        "user": {"zh": "\n- 面向终端用户，减少技术细节，多写使用方法和示例", "en": "\n- Target end users: reduce technical details, focus on usage and examples"},
        "contributor": {"zh": "\n- 面向贡献者，包含开发环境搭建、测试方法、提交规范", "en": "\n- Target contributors: include dev setup, testing, and contribution guidelines"},
    }
    if audience in audience_map:
        base += audience_map[audience].get(language, audience_map[audience]["en"])

    if custom_sections:
        if language == "zh":
            base += f"\n- 请额外包含以下章节：{custom_sections}"
        else:
            base += f"\n- Additionally include these sections: {custom_sections}"

    if exclude_sections:
        if language == "zh":
            base += f"\n- 请跳过以下章节：{exclude_sections}"
        else:
            base += f"\n- Skip these sections: {exclude_sections}"

    if custom_prompt_suffix:
        base += f"\n\n{custom_prompt_suffix}"

    return base


async def generate_readme(
    provider: AIProvider,
    analysis: ProjectAnalysis,
    snapshots: list[FileSnapshot],
    on_progress: Callable[[str], Awaitable[None]],
    on_chunk: Callable[[str], Awaitable[None]],
    language: str = "zh",
    tone: str = "professional",
    include_badges: bool = True,
    custom_sections: str = "",
    exclude_sections: str = "",
    custom_prompt_suffix: str = "",
    feedback: str = "",
    previous_readme: str = "",
    badge_style: str = "shields",
    toc_depth: int = 2,
    code_examples: str = "normal",
    link_style: str = "inline",
    section_order: str = "",
    audience: str = "developer",
    quality_mode: str = "balanced",
) -> str:
    await on_progress("正在生成 README...")

    user_prompt = build_readme_prompt(analysis, snapshots, previous_readme, feedback, quality_mode)
    system_prompt = _build_generation_prompt(
        language, tone, include_badges, custom_sections, exclude_sections, custom_prompt_suffix,
        badge_style, toc_depth, code_examples, link_style, section_order, audience,
    )
    return await provider.generate_stream(system_prompt, user_prompt, on_chunk)


async def run_pipeline(
    folder_path: str,
    provider: AIProvider,
    on_progress: Callable[[str], Awaitable[None]],
    on_chunk: Callable[[str], Awaitable[None]],
    language: str = "zh",
    tone: str = "professional",
    include_badges: bool = True,
    custom_sections: str = "",
    exclude_sections: str = "",
    custom_prompt_suffix: str = "",
    include_patterns: str = "",
    exclude_patterns: str = "",
    feedback: str = "",
    previous_readme: str = "",
    badge_style: str = "shields",
    toc_depth: int = 2,
    code_examples: str = "normal",
    link_style: str = "inline",
    section_order: str = "",
    audience: str = "developer",
    quality_mode: str = "balanced",
) -> GenerateResponse:
    await on_progress("正在校验项目路径...")
    resolved = validate_path(folder_path)

    await on_progress("正在读取项目文件...")
    gitignore = load_gitignore_patterns(resolved)
    snapshots, existing_readme = traverse_project(resolved, gitignore, include_patterns, exclude_patterns)

    if not snapshots:
        raise ValueError("项目中未找到源代码文件，请确保文件夹中包含代码文件。")

    await on_progress(f"找到 {len(snapshots)} 个源文件，正在分析...")
    analysis = await analyze_project(
        provider,
        snapshots,
        existing_readme,
        on_progress,
        language,
        include_patterns,
        exclude_patterns,
        feedback_mode=bool(feedback.strip() or previous_readme.strip()),
        quality_mode=quality_mode,
    )

    readme = await generate_readme(
        provider, analysis, snapshots, on_progress, on_chunk,
        language, tone, include_badges, custom_sections, exclude_sections, custom_prompt_suffix,
        feedback, previous_readme, badge_style, toc_depth, code_examples, link_style, section_order, audience, quality_mode,
    )

    return GenerateResponse(
        readme=readme,
        model=provider.model,
        provider=provider.name,
    )
