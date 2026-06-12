from __future__ import annotations

from collections.abc import Callable, Mapping

from .sandbox import DockerSandbox, ExecutionResult, SandboxError


class SandboxTools:
    def __init__(self, sandbox: DockerSandbox | None = None) -> None:
        self._sandbox = sandbox or DockerSandbox()

    def _run(self, fn: Callable[[], ExecutionResult]) -> dict[str, object]:
        try:
            return fn().to_dict()
        except SandboxError as exc:
            return {
                "stdout": "",
                "stderr": str(exc),
                "exit_code": 1,
                "timed_out": False,
                "oom_killed": False,
                "output_truncated": False,
                "duration_ms": 0,
                "output_files": {},
            }

    def run_code(
        self,
        language: str,
        code: str,
        *,
        env: dict[str, str] | None = None,
        output_files: list[str] | None = None,
    ) -> dict[str, object]:
        """Run a single-file code snippet in an ephemeral sandbox container."""
        return self._run(
            lambda: self._sandbox.run_code(language, code, env=env, output_files=output_files)
        )

    def run_command(
        self,
        command: str,
        *,
        env: dict[str, str] | None = None,
        output_files: list[str] | None = None,
    ) -> dict[str, object]:
        """Run a shell command in an ephemeral sandbox container."""
        return self._run(
            lambda: self._sandbox.run_command(command, env=env, output_files=output_files)
        )

    def run_file(
        self,
        language: str,
        files: Mapping[str, str],
        *,
        env: dict[str, str] | None = None,
        output_files: list[str] | None = None,
    ) -> dict[str, object]:
        """Run a multi-file project in an ephemeral sandbox container."""
        return self._run(
            lambda: self._sandbox.run_project(language, files, env=env, output_files=output_files)
        )
