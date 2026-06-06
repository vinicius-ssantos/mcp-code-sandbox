from __future__ import annotations

import io
import logging
import tarfile
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

TIMEOUT_SECONDS = 30
MEMORY_LIMIT = "256m"
CPU_PERIOD = 100_000
CPU_QUOTA = 50_000
TMPFS = {"/tmp": "rw,size=64m,mode=1777"}
LOGGER = logging.getLogger("mcp_code_sandbox.sandbox")

IMAGES = {
    "python": "mcp-sandbox-python:local",
    "node": "mcp-sandbox-node:local",
    "java": "mcp-sandbox-java:local",
    "bash": "mcp-sandbox-python:local",
}

FILE_NAMES = {
    "python": "main.py",
    "node": "main.js",
    "java": "Main.java",
    "bash": "script.sh",
}

RUN_COMMANDS = {
    "python": ["python", "/workspace/main.py"],
    "node": ["node", "/workspace/main.js"],
    "java": [
        "bash",
        "-lc",
        "mkdir -p /tmp/classes && "
        "find /workspace -name '*.java' -print0 | xargs -0 javac -d /tmp/classes && "
        "java -cp /tmp/classes Main",
    ],
    "bash": ["bash", "/workspace/script.sh"],
}


class SandboxError(Exception):
    """Base error for sandbox execution failures."""


class UnsupportedLanguageError(SandboxError):
    """Raised when a requested language has no configured sandbox image."""


class InvalidProjectFileError(SandboxError):
    """Raised when a project file path is unsafe or invalid."""


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False

    def format_for_mcp(self) -> str:
        parts: list[str] = []
        if self.stdout:
            parts.append(f"stdout:\n{self.stdout.rstrip()}")
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr.rstrip()}")
        parts.append(f"exit_code: {self.exit_code}")
        if self.timed_out:
            parts.append("status: timed_out")
        return "\n\n".join(parts)


class DockerSandbox:
    def __init__(self) -> None:
        try:
            import docker
        except ModuleNotFoundError as exc:
            raise SandboxError(
                "Python package 'docker' is not installed. "
                "Install server dependencies with: pip install -r server/requirements.txt"
            ) from exc

        self._docker_exception = docker.errors.DockerException
        self._client = docker.from_env()

    def run_code(self, language: str, code: str) -> ExecutionResult:
        language = normalize_language(language)
        return self.run_project(language, {FILE_NAMES[language]: code})

    def run_command(self, command: str) -> ExecutionResult:
        return self._run_container("bash", ["bash", "-lc", command], {})

    def run_project(
        self,
        language: str,
        files: Mapping[str, str],
        command: list[str] | None = None,
    ) -> ExecutionResult:
        language = normalize_language(language)
        safe_files = validate_project_files(files)
        run_command = command or RUN_COMMANDS[language]
        return self._run_container(language, run_command, safe_files)

    def _run_container(
        self,
        language: str,
        command: list[str],
        files: Mapping[str, str],
    ) -> ExecutionResult:
        image = IMAGES[language]
        container_name = f"mcp-code-sandbox-{language}-{uuid.uuid4().hex}"
        container = None
        workspace_dir = tempfile.TemporaryDirectory(prefix="mcp-code-sandbox-") if files else None
        started_at = time.monotonic()
        try:
            volumes = None
            if workspace_dir is not None:
                materialize_workspace(Path(workspace_dir.name), files)
                volumes = {workspace_dir.name: {"bind": "/workspace", "mode": "ro"}}

            LOGGER.info(
                "sandbox_execution_start",
                extra={
                    "language": language,
                    "image": image,
                    "container_name": container_name,
                    "file_count": len(files),
                },
            )
            container = self._client.containers.create(
                image=image,
                command=command,
                name=container_name,
                detach=True,
                working_dir="/workspace",
                volumes=volumes,
                network_mode="none",
                read_only=True,
                tmpfs=TMPFS,
                mem_limit=MEMORY_LIMIT,
                memswap_limit=MEMORY_LIMIT,
                cpu_period=CPU_PERIOD,
                cpu_quota=CPU_QUOTA,
                user="sandbox",
            )

            container.start()
            deadline = time.monotonic() + TIMEOUT_SECONDS
            timed_out = False
            exit_code = 124

            while True:
                container.reload()
                state = container.attrs.get("State", {})
                if not state.get("Running"):
                    exit_code = int(state.get("ExitCode") or 0)
                    break
                if time.monotonic() >= deadline:
                    timed_out = True
                    container.kill()
                    exit_code = 124
                    break
                time.sleep(0.1)

            stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
            stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
            LOGGER.info(
                "sandbox_execution_finish",
                extra={
                    "language": language,
                    "image": image,
                    "container_name": container_name,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                    "stdout_bytes": len(stdout.encode("utf-8")),
                    "stderr_bytes": len(stderr.encode("utf-8")),
                },
            )
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
            )
        except self._docker_exception as exc:
            LOGGER.exception(
                "sandbox_execution_error",
                extra={
                    "language": language,
                    "image": image,
                    "container_name": container_name,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                    "error_type": exc.__class__.__name__,
                },
            )
            raise SandboxError(f"Docker sandbox failed: {exc}") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except self._docker_exception:
                    pass
            if workspace_dir is not None:
                workspace_dir.cleanup()


def normalize_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized not in IMAGES:
        allowed = ", ".join(sorted(IMAGES))
        raise UnsupportedLanguageError(f"Unsupported language: {language!r}. Allowed: {allowed}")
    return normalized


def validate_project_files(files: Mapping[str, str]) -> dict[str, str]:
    if not files:
        raise InvalidProjectFileError("At least one file is required")

    safe_files: dict[str, str] = {}
    for raw_path, content in files.items():
        path = PurePosixPath(raw_path.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.name:
            raise InvalidProjectFileError(f"Unsafe file path: {raw_path!r}")
        safe_files[str(path)] = content
    return safe_files


def build_tar(files: Mapping[str, str]) -> bytes:
    buffer = io.BytesIO()
    added_dirs: set[str] = set()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path, content in files.items():
            parent = PurePosixPath(path).parent
            parents = []
            while str(parent) not in ("", "."):
                parents.append(str(parent))
                parent = parent.parent
            for directory in reversed(parents):
                if directory in added_dirs:
                    continue
                info = tarfile.TarInfo(directory)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                tar.addfile(info)
                added_dirs.add(directory)

            encoded = content.encode("utf-8")
            info = tarfile.TarInfo(path)
            info.size = len(encoded)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(encoded))
    buffer.seek(0)
    return buffer.read()


def materialize_workspace(root: Path, files: Mapping[str, str]) -> None:
    for relative_path, content in files.items():
        destination = root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
