from __future__ import annotations

from collections.abc import Callable, Mapping

from .sandbox import DockerSandbox, ExecutionResult, SandboxError


class SandboxTools:
    def __init__(self, sandbox: DockerSandbox | None = None) -> None:
        self._sandbox = sandbox or DockerSandbox()

    def _run(self, fn: Callable[[], ExecutionResult]) -> str:
        try:
            return fn().format_for_mcp()
        except SandboxError as exc:
            return f"stderr:\n{exc}\n\nexit_code: 1"

    def run_code(self, language: str, code: str) -> str:
        """Run a single-file code snippet in an ephemeral sandbox container."""
        return self._run(lambda: self._sandbox.run_code(language, code))

    def run_command(self, command: str) -> str:
        """Run a shell command in an ephemeral sandbox container."""
        return self._run(lambda: self._sandbox.run_command(command))

    def run_file(self, language: str, files: Mapping[str, str]) -> str:
        """Run a multi-file project in an ephemeral sandbox container."""
        return self._run(lambda: self._sandbox.run_project(language, files))
