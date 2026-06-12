import io
import tarfile
import threading
from unittest.mock import MagicMock

import pytest
import requests.exceptions

import server.sandbox as sb
from server.sandbox import (
    DockerSandbox,
    ExecutionResult,
    InvalidProjectFileError,
    SandboxBusyError,
    UnsupportedLanguageError,
    _env_str,
    build_tar,
    normalize_language,
    truncate_output,
    validate_project_files,
)


def test_env_str_returns_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_MEMORY_LIMIT", raising=False)
    assert _env_str("SANDBOX_MEMORY_LIMIT", "256m") == "256m"


def test_env_str_returns_env_value_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_MEMORY_LIMIT", "512m")
    assert _env_str("SANDBOX_MEMORY_LIMIT", "256m") == "512m"


def test_env_str_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_MEMORY_LIMIT", "  512m  ")
    assert _env_str("SANDBOX_MEMORY_LIMIT", "256m") == "512m"


def test_env_str_falls_back_to_default_for_blank_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SANDBOX_MEMORY_LIMIT", "   ")
    assert _env_str("SANDBOX_MEMORY_LIMIT", "256m") == "256m"


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


def test_execution_result_format_includes_oom_killed_status():
    result = ExecutionResult(stdout="", stderr="", exit_code=137, oom_killed=True)

    formatted = result.format_for_mcp()
    assert "exit_code: 137" in formatted
    assert "status: oom_killed" in formatted


def test_execution_result_oom_and_timeout_flags_are_independent():
    # Both flags can appear simultaneously (edge case, but the format must be stable).
    result = ExecutionResult(stdout="", stderr="", exit_code=137, timed_out=True, oom_killed=True)
    formatted = result.format_for_mcp()
    assert "status: timed_out" in formatted
    assert "status: oom_killed" in formatted


def _make_sandbox_with_mock_client() -> tuple[DockerSandbox, MagicMock]:
    sandbox = object.__new__(DockerSandbox)
    mock_client = MagicMock()
    sandbox._client = mock_client
    sandbox._docker_exception = Exception
    sandbox._semaphore = threading.BoundedSemaphore(4)
    return sandbox, mock_client


def test_gc_removes_orphaned_containers_and_volumes():
    sandbox, mock_client = _make_sandbox_with_mock_client()
    mock_container = MagicMock()
    mock_container.short_id = "abc123"
    mock_volume = MagicMock()
    mock_volume.name = "mcp-code-sandbox-workspace-xyz"
    mock_client.containers.list.return_value = [mock_container]
    mock_client.volumes.list.return_value = [mock_volume]

    sandbox._gc_orphaned_resources()

    mock_client.containers.list.assert_called_once_with(
        all=True, filters={"label": "managed-by=mcp-code-sandbox"}
    )
    mock_client.volumes.list.assert_called_once_with(
        filters={"label": "managed-by=mcp-code-sandbox"}
    )
    mock_container.remove.assert_called_once_with(force=True)
    mock_volume.remove.assert_called_once_with(force=True)


def test_gc_continues_after_individual_remove_failure():
    sandbox, mock_client = _make_sandbox_with_mock_client()
    bad = MagicMock()
    bad.short_id = "bad"
    bad.remove.side_effect = Exception("busy")
    good = MagicMock()
    good.short_id = "good"
    mock_client.containers.list.return_value = [bad, good]
    mock_client.volumes.list.return_value = []

    sandbox._gc_orphaned_resources()  # must not raise

    bad.remove.assert_called_once_with(force=True)
    good.remove.assert_called_once_with(force=True)


def test_gc_labels_are_applied_to_containers_create():
    """containers.create must include _MANAGED_BY_LABEL so GC can find orphans."""
    sandbox, mock_client = _make_sandbox_with_mock_client()
    mock_container = MagicMock()
    mock_container.wait.return_value = {"StatusCode": 0}
    mock_container.attrs = {"State": {"OOMKilled": False}}
    mock_container.logs.return_value = iter([])
    mock_client.containers.create.return_value = mock_container

    sandbox._run_container_locked("python", ["python", "/workspace/main.py"], {})

    create_kwargs = mock_client.containers.create.call_args.kwargs
    assert create_kwargs.get("labels") == {"managed-by": "mcp-code-sandbox"}


def test_kill_race_condition_does_not_raise_when_container_already_stopped():
    """If kill() fails because the container stopped just before the call,
    the execution should complete normally with the container's real exit code."""
    sandbox, mock_client = _make_sandbox_with_mock_client()
    mock_container = MagicMock()
    mock_container.wait.side_effect = requests.exceptions.ReadTimeout()
    mock_container.kill.side_effect = Exception("container not running")
    mock_container.attrs = {"State": {"ExitCode": 0, "OOMKilled": False}}
    mock_container.logs.return_value = iter([])
    mock_client.containers.create.return_value = mock_container

    result = sandbox._run_container_locked("python", ["python", "/workspace/main.py"], {})

    assert result.timed_out is False
    assert result.exit_code == 0
