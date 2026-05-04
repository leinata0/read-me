from __future__ import annotations

import json
import time
from typing import Callable, Awaitable

from app.analyzer import (
    validate_path, load_gitignore_patterns, traverse_project,
    estimate_total_tokens, compute_project_hash, prioritize_files,
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
"""

GENERATION_SYSTEM_PROMPT_ZH = """\
你是一名技术文档专家，正在为一个软件项目编写高质量的 README.md。

要求：
- 用中文撰写（代码块、命令、技术术语保持英文原文）
- 写一段有吸引力的项目描述（具体针对此项目，不要泛泛而谈）
- 包含目录
- 安装章节：使用项目语言/生态系统的精确命令
- 使用章节：提供可运行的代码示例
- 依赖章节：列出关键运行时依赖
- 简要架构概述
- 检测到 License 时添加许可证章节
- 添加适合该语言/生态系统的 badge
- 如果发现了已有的 README，保留其中未涵盖的重要内容
- 使用规范的 Markdown 格式：标题、代码块、链接
- 输出应是生产级别的，而非模板
"""

GENERATION_SYSTEM_PROMPT_EN = """\
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
CACHE_MAX_SIZE = 50


def _evict_expired_cache() -> None:
    """Remove expired entries and enforce max size."""
    now = time.time()
    expired = [k for k, (_, ts) in _analysis_cache.items() if now - ts >= CACHE_TTL]
    for k in expired:
        del _analysis_cache[k]
    # If still over max size, remove oldest entries
    if len(_analysis_cache) > CACHE_MAX_SIZE:
        sorted_keys = sorted(_analysis_cache, key=lambda k: _analysis_cache[k][1])
        for k in sorted_keys[:len(_analysis_cache) - CACHE_MAX_SIZE]:
            del _analysis_cache[k]


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


def build_readme_prompt(analysis: ProjectAnalysis, snapshots: list[FileSnapshot],
                        previous_readme: str = "", feedback: str = "") -> str:
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
    for snap in snapshots:
        stem = snap.relative_path.split("/")[-1].split("\\")[-1].rsplit(".", 1)[0].lower()
        if stem in ENTRY_NAMES or snap.relative_path in analysis.entry_points:
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

    # 反馈式重新生成：注入当前版本和用户反馈
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
) -> ProjectAnalysis:
    _evict_expired_cache()
    project_hash = compute_project_hash(snapshots)
    cached = _analysis_cache.get(project_hash)
    if cached and (time.time() - cached[1]) < CACHE_TTL:
        await on_progress("使用缓存的分析结果...")
        return cached[0]

    await on_progress("正在分析项目结构...")

    total_tokens = estimate_total_tokens(snapshots)
    if total_tokens > 300_000:
        snapshots = prioritize_files(snapshots, max_tokens=150_000)

    user_prompt = build_analysis_prompt(snapshots, existing_readme)
    schema = _get_project_analysis_schema()
    system_prompt = ANALYSIS_SYSTEM_PROMPT_ZH if language == "zh" else ANALYSIS_SYSTEM_PROMPT_EN

    result = await _retry_on_transient(provider.analyze, system_prompt, user_prompt, schema)
    analysis = ProjectAnalysis(**result)
    analysis.existing_readme = existing_readme

    _analysis_cache[project_hash] = (analysis, time.time())
    return analysis


def _build_generation_prompt(language: str, tone: str, include_badges: bool,
                              custom_sections: str, exclude_sections: str,
                              custom_prompt_suffix: str,
                              badge_style: str = "shields", toc_depth: int = 2,
                              code_examples: str = "normal", link_style: str = "inline",
                              section_order: str = "", audience: str = "developer") -> str:
    base = GENERATION_SYSTEM_PROMPT_ZH if language == "zh" else GENERATION_SYSTEM_PROMPT_EN

    # 语气
    tone_map = {
        "professional": {"zh": "\n- 使用专业、正式的技术文档语气", "en": "\n- Use a professional, formal technical documentation tone"},
        "casual": {"zh": "\n- 使用轻松友好的语气，适合开源社区", "en": "\n- Use a casual, friendly tone suitable for open-source communities"},
        "technical": {"zh": "\n- 使用高度技术性的语气，面向资深开发者", "en": "\n- Use a highly technical tone targeting experienced developers"},
    }
    if tone in tone_map:
        base += tone_map[tone].get(language, tone_map[tone]["en"])

    # Badge
    if not include_badges:
        badge_line = "- 添加适合该语言/生态系统的 badge" if language == "zh" else "- Badge suggestions appropriate for the language/ecosystem"
        base = base.replace(badge_line, "")
    elif badge_style != "shields":
        if language == "zh":
            base += f"\n- 使用 {badge_style} 样式的 Badge"
        else:
            base += f"\n- Use {badge_style} style badges"

    # 目录深度
    if toc_depth < 2:
        if language == "zh":
            base += f"\n- 目录只显示到 h{toc_depth + 1} 级标题"
        else:
            base += f"\n- Table of contents should only include h{toc_depth + 1} and above"

    # 代码示例详细度
    code_map = {
        "minimal": {"zh": "\n- 代码示例保持简洁，只展示核心用法", "en": "\n- Keep code examples minimal, showing only core usage"},
        "detailed": {"zh": "\n- 代码示例要详细，包含多种场景和完整的错误处理", "en": "\n- Provide detailed code examples with multiple scenarios and error handling"},
    }
    if code_examples in code_map:
        base += code_map[code_examples].get(language, code_map[code_examples]["en"])

    # 链接样式
    if link_style == "reference":
        if language == "zh":
            base += "\n- 使用 Markdown 引用式链接（reference-style links）"
        else:
            base += "\n- Use reference-style Markdown links"

    # 章节顺序
    if section_order:
        if language == "zh":
            base += f"\n- 请按以下顺序排列章节：{section_order}"
        else:
            base += f"\n- Arrange sections in this order: {section_order}"

    # 目标受众
    audience_map = {
        "user": {"zh": "\n- 面向终端用户，减少技术细节，多写使用方法和示例", "en": "\n- Target end users: reduce technical details, focus on usage and examples"},
        "contributor": {"zh": "\n- 面向贡献者，包含开发环境搭建、测试方法、提交规范", "en": "\n- Target contributors: include dev setup, testing, and contribution guidelines"},
    }
    if audience in audience_map:
        base += audience_map[audience].get(language, audience_map[audience]["en"])

    # 自定义章节
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
) -> str:
    await on_progress("正在生成 README...")

    user_prompt = build_readme_prompt(analysis, snapshots, previous_readme, feedback)
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
) -> GenerateResponse:
    await on_progress("正在校验项目路径...")
    resolved = validate_path(folder_path)

    await on_progress("正在读取项目文件...")
    gitignore = load_gitignore_patterns(resolved)
    snapshots, existing_readme = traverse_project(resolved, gitignore, include_patterns, exclude_patterns)

    if not snapshots:
        raise ValueError("项目中未找到源代码文件，请确保文件夹中包含代码文件。")

    # 有 feedback 时跳过分析步骤，直接用缓存的 analysis 重新生成
    if feedback and previous_readme:
        await on_progress("根据反馈修订中...")
        analysis = await analyze_project(provider, snapshots, existing_readme, on_progress, language)
    else:
        await on_progress(f"找到 {len(snapshots)} 个源文件，正在分析...")
        analysis = await analyze_project(provider, snapshots, existing_readme, on_progress, language)

    readme = await generate_readme(
        provider, analysis, snapshots, on_progress, on_chunk,
        language, tone, include_badges, custom_sections, exclude_sections, custom_prompt_suffix,
        feedback, previous_readme, badge_style, toc_depth, code_examples, link_style, section_order, audience,
    )

    return GenerateResponse(
        readme=readme,
        model=provider.model,
        provider=provider.name,
    )
