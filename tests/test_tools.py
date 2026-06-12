import asyncio
from unittest.mock import MagicMock

import pytest

from server.main import ApiKeyTokenVerifier
from server.sandbox import ExecutionResult, SandboxError
from server.tools import SandboxTools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_sandbox() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def tools(mock_sandbox: MagicMock) -> SandboxTools:
    return SandboxTools(sandbox=mock_sandbox)


def _ok(stdout: str = "ok\n") -> ExecutionResult:
    return ExecutionResult(stdout=stdout, stderr="", exit_code=0)


# ---------------------------------------------------------------------------
# SandboxTools.run_code
# ---------------------------------------------------------------------------


class TestRunCode:
    def test_delegates_to_sandbox(self, tools: SandboxTools, mock_sandbox: MagicMock) -> None:
        mock_sandbox.run_code.return_value = _ok("2\n")
        result = tools.run_code("python", "print(1+1)")
        mock_sandbox.run_code.assert_called_once_with(
            "python", "print(1+1)", env=None, output_files=None
        )
        assert "2" in result["stdout"]
        assert result["exit_code"] == 0

    def test_sandbox_error_returns_exit_1(
        self, tools: SandboxTools, mock_sandbox: MagicMock
    ) -> None:
        mock_sandbox.run_code.side_effect = SandboxError("Docker exploded")
        result = tools.run_code("python", "code")
        assert result["exit_code"] == 1
        assert "Docker exploded" in result["stderr"]


# ---------------------------------------------------------------------------
# SandboxTools.run_command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_delegates_to_sandbox(self, tools: SandboxTools, mock_sandbox: MagicMock) -> None:
        mock_sandbox.run_command.return_value = _ok("hello\n")
        result = tools.run_command("echo hello")
        mock_sandbox.run_command.assert_called_once_with("echo hello", env=None, output_files=None)
        assert "hello" in result["stdout"]

    def test_sandbox_error_returns_exit_1(
        self, tools: SandboxTools, mock_sandbox: MagicMock
    ) -> None:
        mock_sandbox.run_command.side_effect = SandboxError("failed")
        result = tools.run_command("bad")
        assert result["exit_code"] == 1


# ---------------------------------------------------------------------------
# SandboxTools.run_file
# ---------------------------------------------------------------------------


class TestRunFile:
    def test_delegates_to_sandbox(self, tools: SandboxTools, mock_sandbox: MagicMock) -> None:
        files = {"main.py": "print('hi')"}
        mock_sandbox.run_project.return_value = _ok("hi\n")
        result = tools.run_file("python", files)
        mock_sandbox.run_project.assert_called_once_with(
            "python", files, env=None, output_files=None
        )
        assert "hi" in result["stdout"]

    def test_sandbox_error_returns_exit_1(
        self, tools: SandboxTools, mock_sandbox: MagicMock
    ) -> None:
        mock_sandbox.run_project.side_effect = SandboxError("oops")
        result = tools.run_file("python", {"main.py": "x"})
        assert result["exit_code"] == 1


# ---------------------------------------------------------------------------
# ApiKeyTokenVerifier
# ---------------------------------------------------------------------------


class TestApiKeyTokenVerifier:
    def test_correct_key_returns_access_token(self) -> None:
        verifier = ApiKeyTokenVerifier("secret-key")
        token = asyncio.run(verifier.verify_token("secret-key"))
        assert token is not None
        assert "sandbox:run" in token.scopes

    def test_wrong_key_returns_none(self) -> None:
        verifier = ApiKeyTokenVerifier("secret-key")
        token = asyncio.run(verifier.verify_token("wrong-key"))
        assert token is None

    def test_empty_token_returns_none(self) -> None:
        verifier = ApiKeyTokenVerifier("secret-key")
        token = asyncio.run(verifier.verify_token(""))
        assert token is None

    def test_non_ascii_token_returns_none_instead_of_raising(self) -> None:
        verifier = ApiKeyTokenVerifier("secret-key")
        token = asyncio.run(verifier.verify_token("chavé-inválida"))
        assert token is None
