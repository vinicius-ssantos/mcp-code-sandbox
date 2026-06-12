import io
import tarfile
import threading
from unittest.mock import MagicMock

import pytest

import server.sandbox as sb
from server.sandbox import (
    DockerSandbox,
    ExecutionResult,
    InvalidProjectFileError,
    SandboxBusyError,
    UnsupportedLanguageError,
    build_tar,
    normalize_language,
    truncate_output,
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


def test_validate_project_files_rejects_too_many_files(monkeypatch):
    monkeypatch.setattr(sb, "MAX_PROJECT_FILES", 2)
    files = {f"f{i}.py": "x" for i in range(3)}
    with pytest.raises(InvalidProjectFileError, match="Too many files"):
        validate_project_files(files)


def test_validate_project_files_rejects_oversized_project(monkeypatch):
    monkeypatch.setattr(sb, "MAX_PROJECT_BYTES", 10)
    with pytest.raises(InvalidProjectFileError, match="too large"):
        validate_project_files({"a.py": "x" * 6, "b.py": "y" * 6})


def test_validate_project_files_accepts_project_within_limits():
    files = validate_project_files({"a.py": "print(1)", "lib/b.py": "x = 2"})
    assert files == {"a.py": "print(1)", "lib/b.py": "x = 2"}


def test_truncate_output_passes_small_output_through():
    text, truncated = truncate_output(b"hello\n")
    assert text == "hello\n"
    assert truncated is False


def test_truncate_output_caps_large_output(monkeypatch):
    monkeypatch.setattr(sb, "MAX_OUTPUT_BYTES", 4)
    text, truncated = truncate_output(b"abcdefgh")
    assert text == "abcd"
    assert truncated is True


def test_execution_result_format_includes_timeout_status():
    result = ExecutionResult(stdout="ok\n", stderr="", exit_code=124, timed_out=True)

    assert result.format_for_mcp() == "stdout:\nok\n\nexit_code: 124\n\nstatus: timed_out"


def test_execution_result_format_includes_truncated_status():
    result = ExecutionResult(stdout="ok\n", stderr="", exit_code=0, output_truncated=True)

    assert result.format_for_mcp() == "stdout:\nok\n\nexit_code: 0\n\nstatus: output_truncated"


def test_run_container_rejects_when_at_capacity(monkeypatch):
    sandbox = object.__new__(DockerSandbox)
    sandbox._client = MagicMock()
    sandbox._docker_exception = Exception
    sandbox._semaphore = threading.BoundedSemaphore(1)
    sandbox._semaphore.acquire()
    monkeypatch.setattr(sb, "EXECUTION_QUEUE_TIMEOUT_SECONDS", 0)

    with pytest.raises(SandboxBusyError):
        sandbox._run_container("python", ["python"], {})

    sandbox._client.containers.create.assert_not_called()
