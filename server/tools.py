from __future__ import annotations

from collections.abc import Mapping

from .sandbox import DockerSandbox, SandboxError


class SandboxTools:
    def __init__(self, sandbox: DockerSandbox | None = None) -> None:
        self._sandbox = sandbox or DockerSandbox()

    def run_code(self, language: str, code: str) -> str:
        """Run a single-file code snippet in an ephemeral sandbox container."""
        try:
            return self._sandbox.run_code(language, code).format_for_mcp()
        except SandboxError as exc:
            return f"stderr:\n{exc}\n\nexit_code: 1"

    def run_command(self, command: str) -> str:
        """Run a shell command in an ephemeral sandbox container."""
        try:
            return self._sandbox.run_command(command).format_for_mcp()
        except SandboxError as exc:
            return f"stderr:\n{exc}\n\nexit_code: 1"

    def run_file(self, language: str, files: Mapping[str, str]) -> str:
        """Run a multi-file project in an ephemeral sandbox container."""
        try:
            return self._sandbox.run_project(language, files).format_for_mcp()
        except SandboxError as exc:
            return f"stderr:\n{exc}\n\nexit_code: 1"
