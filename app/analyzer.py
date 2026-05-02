from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pathspec

from app.models import FileSnapshot

BINARY_EXTENSIONS: set[str] = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp",
    ".zip", ".tar", ".gz", ".rar", ".7z",
    ".exe", ".dll", ".so", ".dylib",
    ".pyc", ".pyo", ".class", ".o", ".obj",
    ".db", ".sqlite", ".wav", ".mp3", ".mp4", ".pdf",
    ".woff", ".woff2", ".ttf", ".eot",
}

SKIP_DIRS: set[str] = {
    "node_modules", "__pycache__", ".git", ".svn", ".hg",
    ".tox", ".mypy_cache", ".pytest_cache", ".venv", "venv",
    "dist", "build", ".next", ".nuxt", "target", "bin", "obj",
    ".idea", ".vscode", ".cache",
}

SOURCE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".r", ".m", ".mm", ".lua", ".pl", ".sh",
    ".yaml", ".yml", ".json", ".toml", ".ini", ".cfg", ".conf",
    ".md", ".rst", ".txt",
}

CONFIG_FILES: set[str] = {
    "package.json", "requirements.txt", "pyproject.toml",
    "setup.py", "setup.cfg", "Pipfile", "Gemfile",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
    "Makefile", "CMakeLists.txt", "Dockerfile",
    "docker-compose.yml", "docker-compose.yaml",
    ".env.example", "tsconfig.json",
}

EXT_TO_LANG: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".java": "java", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".php": "php",
    ".c": "c", ".cpp": "cpp", ".h": "c", ".hpp": "cpp",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin",
    ".scala": "scala", ".sh": "bash", ".lua": "lua",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".md": "markdown", ".rst": "rst",
    ".txt": "text", ".cfg": "ini", ".ini": "ini", ".conf": "ini",
}

BLOCKED_PREFIXES: list[str] = [
    "/etc", "/usr", "/System", "/Library",
    "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
]

MAX_FILE_BYTES = 32 * 1024  # 32KB


def validate_path(folder_path: str) -> Path:
    resolved = Path(folder_path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"The specified folder does not exist: {folder_path}")
    if not resolved.is_dir():
        raise ValueError(f"The specified path is not a directory: {folder_path}")

    resolved_str = str(resolved)
    for prefix in BLOCKED_PREFIXES:
        if resolved_str.startswith(prefix):
            raise ValueError("Invalid path. System directories are not allowed.")

    return resolved


def load_gitignore_patterns(folder_path: Path) -> pathspec.PathSpec | None:
    gitignore_path = folder_path / ".gitignore"
    if not gitignore_path.is_file():
        return None
    try:
        with open(gitignore_path, encoding="utf-8") as f:
            return pathspec.PathSpec.from_lines("gitwildmatch", f)
    except (OSError, UnicodeDecodeError):
        return None


def _read_file_content(file_path: Path) -> str:
    try:
        size = file_path.stat().st_size
        with open(file_path, encoding="utf-8", errors="replace") as f:
            if size <= MAX_FILE_BYTES:
                return f.read()
            head_size = MAX_FILE_BYTES // 2
            head = f.read(head_size)
            f.seek(max(0, size - head_size))
            tail = f.read()
            return head + "\n\n... [truncated] ...\n\n" + tail
    except (OSError, PermissionError):
        return ""


def _detect_language(ext: str) -> str:
    return EXT_TO_LANG.get(ext.lower(), "unknown")


def traverse_project(folder_path: Path, pathspec_obj: pathspec.PathSpec | None = None) -> tuple[list[FileSnapshot], str | None]:
    snapshots: list[FileSnapshot] = []
    existing_readme: str | None = None

    for root, dirs, files in os.walk(folder_path, followlinks=False):
        rel_root = Path(root).relative_to(folder_path)
        rel_root_str = str(rel_root) if str(rel_root) != "." else ""

        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]

        if pathspec_obj and rel_root_str:
            if pathspec_obj.match_file(rel_root_str + "/"):
                dirs.clear()
                continue

        for filename in files:
            rel_file = os.path.join(rel_root_str, filename) if rel_root_str else filename

            if pathspec_obj and pathspec_obj.match_file(rel_file):
                continue

            ext = Path(filename).suffix.lower()
            if ext in BINARY_EXTENSIONS:
                continue

            full_path = Path(root) / filename
            if not full_path.is_file():
                continue

            if filename.upper() in ("README.MD", "README") and existing_readme is None:
                existing_readme = _read_file_content(full_path)
                continue

            content = _read_file_content(full_path)
            if not content:
                continue

            snapshots.append(FileSnapshot(
                path=str(full_path),
                relative_path=rel_file,
                language=_detect_language(ext),
                content=content,
                size_bytes=full_path.stat().st_size,
                is_config=filename in CONFIG_FILES,
            ))

    snapshots.sort(key=lambda s: (0 if s.is_config else 1, s.relative_path))
    return snapshots, existing_readme


def estimate_total_tokens(snapshots: list[FileSnapshot]) -> int:
    return sum(len(s.content) // 4 for s in snapshots)


def compute_project_hash(snapshots: list[FileSnapshot]) -> str:
    hasher = hashlib.sha256()
    for snap in sorted(snapshots, key=lambda s: s.relative_path):
        hasher.update(snap.relative_path.encode())
        hasher.update(hashlib.sha256(snap.content.encode()).hexdigest().encode())
    return hasher.hexdigest()


def prioritize_files(snapshots: list[FileSnapshot], max_tokens: int = 150_000) -> list[FileSnapshot]:
    entry_names = {"main", "app", "index", "server", "cli", "run"}
    selected: list[FileSnapshot] = []
    used_tokens = 0

    for snap in snapshots:
        if snap.is_config:
            tokens = len(snap.content) // 4
            if used_tokens + tokens <= max_tokens:
                selected.append(snap)
                used_tokens += tokens

    for snap in snapshots:
        if snap in selected:
            continue
        stem = Path(snap.relative_path).stem.lower()
        if stem in entry_names:
            tokens = len(snap.content) // 4
            if used_tokens + tokens <= max_tokens:
                selected.append(snap)
                used_tokens += tokens

    for snap in snapshots:
        if snap in selected:
            continue
        tokens = len(snap.content) // 4
        if used_tokens + tokens <= max_tokens:
            selected.append(snap)
            used_tokens += tokens
        else:
            break

    return selected
