import io
import tarfile

import pytest

from server.sandbox import (
    ExecutionResult,
    InvalidProjectFileError,
    UnsupportedLanguageError,
    build_tar,
    normalize_language,
    validate_project_files,
)


def test_normalize_language_accepts_supported_language_case_insensitive():
    assert normalize_language(" Python ") == "python"


def test_normalize_language_rejects_unknown_language():
    with pytest.raises(UnsupportedLanguageError):
        normalize_language("ruby")


def test_validate_project_files_rejects_parent_traversal():
    with pytest.raises(InvalidProjectFileError):
        validate_project_files({"../secret.txt": "nope"})


def test_validate_project_files_rejects_absolute_path():
    with pytest.raises(InvalidProjectFileError):
        validate_project_files({"/etc/passwd": "nope"})


def test_build_tar_includes_nested_files():
    archive = build_tar({"lib/util.py": "def greet(): return 'hi'\n"})

    with tarfile.open(fileobj=io.BytesIO(archive), mode="r") as tar:
        names = tar.getnames()
        assert "lib" in names
        assert "lib/util.py" in names
        extracted = tar.extractfile("lib/util.py")
        assert extracted is not None
        assert extracted.read().decode() == "def greet(): return 'hi'\n"


def test_execution_result_format_includes_timeout_status():
    result = ExecutionResult(stdout="ok\n", stderr="", exit_code=124, timed_out=True)

    assert result.format_for_mcp() == "stdout:\nok\n\nexit_code: 124\n\nstatus: timed_out"
