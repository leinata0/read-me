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

    with pytest.raises(ValueError, match="读取内容过大"):
        traverse_project(project_dir)
