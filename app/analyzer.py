from __future__ import annotations

import hashlib
import os
import platform
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
    ".idea", ".vscode", ".cache", ".ruff_cache",
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

_system = platform.system()
if _system == "Windows":
    BLOCKED_PREFIXES: list[str] = [
        "C:\\Windows", "C:\\Program Files", "C:\\Program Files (x86)",
        "C:\\ProgramData",
    ]
else:
    BLOCKED_PREFIXES = [
        "/etc", "/usr", "/System", "/Library", "/boot", "/dev", "/proc", "/sys",
    ]

MAX_FILE_BYTES = 32 * 1024  # 32KB
MAX_PATH_LENGTH = 500
MAX_PROJECT_FILES = 2000
MAX_PROJECT_BYTES = 8 * 1024 * 1024  # 8MB of source/config text before truncation

ENTRY_NAMES: set[str] = {"main", "app", "index", "server", "cli", "run"}
PROJECT_DIR_MARKERS: set[str] = {
    ".git", ".hg", ".svn", "app", "src", "lib", "packages", "cmd",
    "server", "client", "frontend", "backend", "tests",
}
PROJECT_CODE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs",
    ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs", ".swift",
    ".kt", ".scala", ".lua", ".pl", ".sh",
}


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_sensitive_user_path(resolved: Path) -> bool:
    home = Path.home().resolve()
    exact_blocked = [
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
        home / "Pictures",
        home / "Music",
        home / "Videos",
        home / "OneDrive",
    ]
    nested_blocked = [
        home / ".ssh",
        home / ".aws",
        home / ".gnupg",
        home / ".config",
        home / ".kube",
        home / "AppData",
    ]
    if any(resolved == path for path in exact_blocked):
        return True
    return any(resolved == path or _is_relative_to(resolved, path) for path in nested_blocked)


def _looks_like_project(folder_path: Path) -> bool:
    try:
        for entry in folder_path.iterdir():
            if entry.name in CONFIG_FILES:
                return True
            if entry.is_dir() and entry.name in PROJECT_DIR_MARKERS:
                return True
            if entry.is_file() and entry.suffix.lower() in PROJECT_CODE_EXTENSIONS:
                return True
    except OSError:
        return False
    return False


def validate_path(folder_path: str) -> Path:
    resolved = Path(folder_path).resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"The specified folder does not exist: {folder_path}")
    if not resolved.is_dir():
        raise ValueError(f"The specified path is not a directory: {folder_path}")

    resolved_str = str(resolved)
    if len(resolved_str) > MAX_PATH_LENGTH:
        raise ValueError("Path too long.")

    sep = "\\" if _system == "Windows" else "/"
    for prefix in BLOCKED_PREFIXES:
        norm_prefix = prefix if prefix.endswith(sep) else prefix + sep
        if resolved_str.startswith(norm_prefix) or resolved_str == prefix:
            raise ValueError("Invalid path. System directories are not allowed.")

    if _is_sensitive_user_path(resolved):
        raise ValueError("Invalid path. Please select a project folder instead of a personal or sensitive directory.")

    if not _looks_like_project(resolved):
        raise ValueError("Invalid path. Please select a project folder that contains source code or project files.")

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


def traverse_project(folder_path: Path, pathspec_obj: pathspec.PathSpec | None = None,
                     include_patterns: str = "", exclude_patterns: str = "") -> tuple[list[FileSnapshot], str | None]:
    import fnmatch

    include_list = [p.strip() for p in include_patterns.split(",") if p.strip()] if include_patterns else []
    exclude_list = [p.strip() for p in exclude_patterns.split(",") if p.strip()] if exclude_patterns else []
    snapshots: list[FileSnapshot] = []
    existing_readme: str | None = None
    total_bytes = 0

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
            normalized_rel_file = rel_file.replace("\\", "/")

            if pathspec_obj and pathspec_obj.match_file(normalized_rel_file):
                continue

            if include_list and not any(fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(normalized_rel_file, pat) for pat in include_list):
                continue
            if exclude_list and any(fnmatch.fnmatch(filename, pat) or fnmatch.fnmatch(normalized_rel_file, pat) for pat in exclude_list):
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

            file_size = full_path.stat().st_size
            total_bytes += file_size
            snapshots.append(FileSnapshot(
                path=str(full_path),
                relative_path=rel_file,
                language=_detect_language(ext),
                content=content,
                size_bytes=file_size,
                is_config=filename in CONFIG_FILES,
            ))

            if len(snapshots) > MAX_PROJECT_FILES:
                raise ValueError(f"项目包含的可读文件过多（>{MAX_PROJECT_FILES}），请使用包含/排除文件模式缩小范围。")
            if total_bytes > MAX_PROJECT_BYTES:
                raise ValueError(f"项目读取内容过大（>{MAX_PROJECT_BYTES // (1024 * 1024)}MB），请使用包含/排除文件模式缩小范围。")

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
    selected: list[FileSnapshot] = []
    selected_paths: set[str] = set()
    used_tokens = 0

    def try_add(snapshot: FileSnapshot) -> bool:
        nonlocal used_tokens
        if snapshot.relative_path in selected_paths:
            return False
        tokens = max(1, len(snapshot.content) // 4)
        if used_tokens + tokens > max_tokens:
            return False
        selected.append(snapshot)
        selected_paths.add(snapshot.relative_path)
        used_tokens += tokens
        return True

    def priority(snapshot: FileSnapshot) -> tuple[int, int, str]:
        rel_path = snapshot.relative_path.replace('\\', '/').lower()
        name = Path(rel_path).name.lower()
        stem = Path(rel_path).stem.lower()

        if snapshot.is_config:
            return (0, snapshot.size_bytes, rel_path)
        if stem in ENTRY_NAMES or rel_path in {'app/main.py', 'main.py', 'src/main.py'}:
            return (1, snapshot.size_bytes, rel_path)
        if rel_path.endswith('readme.md') or rel_path == 'readme':
            return (2, snapshot.size_bytes, rel_path)
        if '/static/' in rel_path or rel_path.endswith(('.css', '.scss', '.sass', '.less')):
            return (6, snapshot.size_bytes, rel_path)
        if '/templates/' in rel_path or rel_path.endswith('.html'):
            return (5, snapshot.size_bytes, rel_path)
        if rel_path.startswith('tests/') or '/tests/' in rel_path or name.startswith('test_'):
            return (4, snapshot.size_bytes, rel_path)
        return (3, snapshot.size_bytes, rel_path)

    for snap in sorted(snapshots, key=priority):
        try_add(snap)

    return selected


def split_analysis_groups(snapshots: list[FileSnapshot]) -> dict[str, list[FileSnapshot]]:
    groups: dict[str, list[FileSnapshot]] = {
        "config": [],
        "backend": [],
        "frontend": [],
        "tests": [],
    }
    for snapshot in snapshots:
        rel_path = snapshot.relative_path.replace('\\', '/').lower()
        stem = Path(rel_path).stem.lower()
        name = Path(rel_path).name.lower()

        if snapshot.is_config or rel_path.startswith('.github/') or rel_path in {'.gitignore', 'readme.md', 'readme'}:
            groups["config"].append(snapshot)
            continue
        if rel_path.startswith('tests/') or '/tests/' in rel_path or name.startswith('test_'):
            groups["tests"].append(snapshot)
            continue
        if rel_path.endswith(('.js', '.ts', '.tsx', '.html')) or '/templates/' in rel_path:
            groups["frontend"].append(snapshot)
            continue
        if stem in ENTRY_NAMES or rel_path.startswith(('app/', 'src/')):
            groups["backend"].append(snapshot)
            continue
        groups["backend"].append(snapshot)
    return {group_name: items for group_name, items in groups.items() if items}



def should_use_concurrent_analysis(snapshots: list[FileSnapshot], token_threshold: int = 12_000, file_threshold: int = 12) -> bool:
    return len(snapshots) >= file_threshold or estimate_total_tokens(snapshots) > token_threshold



def prioritize_group_files(group_name: str, snapshots: list[FileSnapshot], max_tokens: int) -> list[FileSnapshot]:
    if estimate_total_tokens(snapshots) <= max_tokens:
        return snapshots

    selected: list[FileSnapshot] = []
    used_tokens = 0

    def try_add(snapshot: FileSnapshot) -> bool:
        nonlocal used_tokens
        tokens = max(1, len(snapshot.content) // 4)
        if used_tokens + tokens > max_tokens:
            return False
        selected.append(snapshot)
        used_tokens += tokens
        return True

    def priority(snapshot: FileSnapshot) -> tuple[int, int, str]:
        rel_path = snapshot.relative_path.replace('\\', '/').lower()
        stem = Path(rel_path).stem.lower()
        name = Path(rel_path).name.lower()
        if group_name == 'config':
            return (0 if snapshot.is_config else 1, snapshot.size_bytes, rel_path)
        if group_name == 'backend':
            if rel_path in {'app/main.py', 'app/generator.py', 'app/analyzer.py', 'app/providers.py', 'app/models.py'}:
                return (0, snapshot.size_bytes, rel_path)
            if stem in ENTRY_NAMES:
                return (1, snapshot.size_bytes, rel_path)
            return (2, snapshot.size_bytes, rel_path)
        if group_name == 'frontend':
            if rel_path.endswith('app.js'):
                return (0, snapshot.size_bytes, rel_path)
            if rel_path.endswith(('.js', '.ts', '.tsx')):
                return (1, snapshot.size_bytes, rel_path)
            if rel_path.endswith('.html'):
                return (2, snapshot.size_bytes, rel_path)
            return (3, snapshot.size_bytes, rel_path)
        if name.startswith('test_'):
            return (0, snapshot.size_bytes, rel_path)
        return (1, snapshot.size_bytes, rel_path)

    for snapshot in sorted(snapshots, key=priority):
        try_add(snapshot)

    return selected
