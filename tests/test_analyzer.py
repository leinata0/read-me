from pathlib import Path
import shutil
import uuid

import pytest

from app.analyzer import MAX_PROJECT_BYTES, MAX_PROJECT_FILES, traverse_project, validate_path


def test_validate_path_accepts_project_directory():
    resolved = validate_path(str(Path.cwd()))
    assert resolved == Path.cwd().resolve()


def test_validate_path_rejects_sensitive_directory():
    home = Path.home()
    sensitive_dir = home / "Downloads" if (home / "Downloads").exists() else home

    with pytest.raises(ValueError, match="personal or sensitive directory"):
        validate_path(str(sensitive_dir))


def test_validate_path_rejects_non_project_directory():
    temp_dir = Path.cwd() / ".pytest-temp" / f"empty-{uuid.uuid4().hex}"
    temp_dir.mkdir(parents=True)
    try:
        with pytest.raises(ValueError, match="contains source code or project files"):
            validate_path(str(temp_dir))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def test_traverse_project_rejects_too_many_files(tmp_path: Path):
    project_dir = tmp_path / "many-files"
    project_dir.mkdir()
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    for i in range(MAX_PROJECT_FILES + 1):
        (project_dir / f"file_{i}.py").write_text("print('x')\n", encoding="utf-8")

    with pytest.raises(ValueError, match="可读文件过多"):
        traverse_project(project_dir)


def test_traverse_project_rejects_too_many_bytes(tmp_path: Path):
    project_dir = tmp_path / "many-bytes"
    project_dir.mkdir()
    (project_dir / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    payload = "x" * (MAX_PROJECT_BYTES + 1024)
    (project_dir / "big.py").write_text(payload, encoding="utf-8")




def test_split_analysis_groups_assigns_files_by_role():
    from app.analyzer import split_analysis_groups
    from app.models import FileSnapshot

    snapshots = [
        FileSnapshot(path="/tmp/pyproject.toml", relative_path="pyproject.toml", language="toml", content="x", size_bytes=1, is_config=True),
        FileSnapshot(path="/tmp/app/main.py", relative_path="app/main.py", language="python", content="x", size_bytes=1, is_config=False),
        FileSnapshot(path="/tmp/app/static/app.js", relative_path="app/static/app.js", language="javascript", content="x", size_bytes=1, is_config=False),
        FileSnapshot(path="/tmp/tests/test_api.py", relative_path="tests/test_api.py", language="python", content="x", size_bytes=1, is_config=False),
    ]

    groups = split_analysis_groups(snapshots)

    assert [item.relative_path for item in groups["config"]] == ["pyproject.toml"]
    assert [item.relative_path for item in groups["backend"]] == ["app/main.py"]
    assert [item.relative_path for item in groups["frontend"]] == ["app/static/app.js"]
    assert [item.relative_path for item in groups["tests"]] == ["tests/test_api.py"]



def test_should_use_concurrent_analysis_for_large_inputs():
    from app.analyzer import should_use_concurrent_analysis
    from app.models import FileSnapshot

    snapshots = [
        FileSnapshot(
            path=f"/tmp/file_{i}.py",
            relative_path=f"app/file_{i}.py",
            language="python",
            content="x" * 2000,
            size_bytes=2000,
            is_config=False,
        )
        for i in range(12)
    ]

    assert should_use_concurrent_analysis(snapshots) is True



def test_should_use_concurrent_analysis_skips_small_inputs():
    from app.analyzer import should_use_concurrent_analysis
    from app.models import FileSnapshot

    snapshots = [
        FileSnapshot(
            path="/tmp/app/main.py",
            relative_path="app/main.py",
            language="python",
            content="print('x')",
            size_bytes=10,
            is_config=False,
        )
    ]

    assert should_use_concurrent_analysis(snapshots) is False
