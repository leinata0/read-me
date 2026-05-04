from pathlib import Path
import shutil
import uuid

import pytest

from app.analyzer import validate_path


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
