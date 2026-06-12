from __future__ import annotations

import base64
import io
import logging
import os
import re
import tarfile
import threading
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

import requests.exceptions

from .metrics import execution_duration_seconds, executions_total, output_bytes_total


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return value


def _env_str(name: str, default: str) -> str:
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else default


# Docker resource limits — configurable via env vars.
# Do NOT raise these defaults without updating the security rationale in ADR 0004.
TIMEOUT_SECONDS = _env_int("SANDBOX_TIMEOUT_SECONDS", 30)
MEMORY_LIMIT = _env_str("SANDBOX_MEMORY_LIMIT", "256m")
CPU_PERIOD = _env_int("SANDBOX_CPU_PERIOD", 100_000)
CPU_QUOTA = _env_int("SANDBOX_CPU_QUOTA", 50_000)
PIDS_LIMIT = _env_int("SANDBOX_PIDS_LIMIT", 128)
TMPFS = {"/tmp": "rw,size=64m,mode=1777"}
# Caps on data crossing the host/sandbox boundary. See ADR 0004 before raising.
MAX_OUTPUT_BYTES = _env_int("SANDBOX_MAX_OUTPUT_BYTES", 1_048_576)
MAX_PROJECT_FILES = _env_int("SANDBOX_MAX_PROJECT_FILES", 64)
MAX_PROJECT_BYTES = _env_int("SANDBOX_MAX_PROJECT_BYTES", 8_388_608)
MAX_CONCURRENT_EXECUTIONS = _env_int("SANDBOX_MAX_CONCURRENT", 4)
EXECUTION_QUEUE_TIMEOUT_SECONDS = _env_int("SANDBOX_QUEUE_TIMEOUT_SECONDS", 30)
MAX_ENV_VARS = _env_int("SANDBOX_MAX_ENV_VARS", 32)
MAX_OUTPUT_FILES = _env_int("SANDBOX_MAX_OUTPUT_FILES", 16)
LOGGER = logging.getLogger("mcp_code_sandbox.sandbox")

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_ENV_KEY_LEN = 128
_MAX_ENV_VAL_LEN = 4096
# Label applied to every container and volume so orphans left by a crash can be
# identified and removed on the next server startup.
_MANAGED_BY_LABEL = {"managed-by": "mcp-code-sandbox"}
# Keeps the workspace-init helper alive while put_archive uploads the project.
_HELPER_KEEPALIVE_CMD = ["tail", "-f", "/dev/null"]

IMAGES = {
    "python": "mcp-sandbox-python:local",
    "node": "mcp-sandbox-node:local",
    "java": "mcp-sandbox-java:local",
    "bash": "mcp-sandbox-bash:local",
}

LANGUAGE_VERSIONS = {
    "python": "3.12",
    "node": "20",
    "java": "21 (Eclipse Temurin)",
    "bash": "5",
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


class SandboxBusyError(SandboxError):
    """Raised when the concurrent execution limit is reached."""


@dataclass(frozen=True)
class ExecutionResult:
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool = False
    output_truncated: bool = False
    oom_killed: bool = False
    duration_ms: int = 0
    # Keyed by filename; values are base64-encoded file contents.
    output_files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "oom_killed": self.oom_killed,
            "output_truncated": self.output_truncated,
            "duration_ms": self.duration_ms,
            "output_files": self.output_files,
        }

    def format_for_mcp(self) -> str:
        parts: list[str] = []
        if self.stdout:
            parts.append(f"stdout:\n{self.stdout.rstrip()}")
        if self.stderr:
            parts.append(f"stderr:\n{self.stderr.rstrip()}")
        parts.append(f"exit_code: {self.exit_code}")
        if self.timed_out:
            parts.append("status: timed_out")
        if self.oom_killed:
            parts.append("status: oom_killed")
        if self.output_truncated:
            parts.append("status: output_truncated")
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
        self._semaphore = threading.BoundedSemaphore(MAX_CONCURRENT_EXECUTIONS)
        self._gc_orphaned_resources()

    def ping(self) -> bool:
        """Return True if the Docker daemon is reachable."""
        try:
            self._client.ping()
            return True
        except self._docker_exception:
            return False

    def run_code(
        self,
        language: str,
        code: str,
        *,
        env: dict[str, str] | None = None,
        output_files: list[str] | None = None,
    ) -> ExecutionResult:
        language = normalize_language(language)
        return self.run_project(
            language,
            {FILE_NAMES[language]: code},
            env=env,
            output_files=output_files,
        )

    def run_command(
        self,
        command: str,
        *,
        env: dict[str, str] | None = None,
        output_files: list[str] | None = None,
    ) -> ExecutionResult:
        safe_env = validate_env_vars(env) if env else {}
        safe_output = validate_output_paths(output_files) if output_files else []
        return self._run_container("bash", ["bash", "-lc", command], {}, safe_env, safe_output)

    def run_project(
        self,
        language: str,
        files: Mapping[str, str],
        command: list[str] | None = None,
        *,
        env: dict[str, str] | None = None,
        output_files: list[str] | None = None,
    ) -> ExecutionResult:
        language = normalize_language(language)
        safe_files = validate_project_files(files)
        safe_env = validate_env_vars(env) if env else {}
        safe_output = validate_output_paths(output_files) if output_files else []
        run_command = command or RUN_COMMANDS[language]
        return self._run_container(language, run_command, safe_files, safe_env, safe_output)

    def _run_container(
        self,
        language: str,
        command: list[str],
        files: Mapping[str, str],
        env: dict[str, str],
        output_files: list[str],
    ) -> ExecutionResult:
        if not self._semaphore.acquire(timeout=EXECUTION_QUEUE_TIMEOUT_SECONDS):
            executions_total.labels(language=language, status="busy").inc()
            LOGGER.warning(
                "sandbox_execution_rejected_busy",
                extra={"language": language, "max_concurrent": MAX_CONCURRENT_EXECUTIONS},
            )
            raise SandboxBusyError(
                f"Sandbox is at capacity ({MAX_CONCURRENT_EXECUTIONS} concurrent executions). "
                "Retry shortly."
            )
        try:
            return self._run_container_locked(language, command, files, env, output_files)
        finally:
            self._semaphore.release()

    def _run_container_locked(
        self,
        language: str,
        command: list[str],
        files: Mapping[str, str],
        env: dict[str, str],
        output_files: list[str],
    ) -> ExecutionResult:
        image = IMAGES[language]
        container_name = f"mcp-code-sandbox-{language}-{uuid.uuid4().hex}"
        container = None
        workspace_volume = None
        started_at = time.monotonic()
        try:
            volumes = None
            if files:
                workspace_volume = self._create_workspace_volume(image, files)
                volumes = {workspace_volume.name: {"bind": "/workspace", "mode": "ro"}}

            LOGGER.info(
                "sandbox_execution_start",
                extra={
                    "language": language,
                    "image": image,
                    "container_name": container_name,
                    "file_count": len(files),
                    "env_vars": len(env),
                },
            )
            container = self._client.containers.create(
                image=image,
                command=command,
                name=container_name,
                labels=_MANAGED_BY_LABEL,
                detach=True,
                working_dir="/workspace",
                volumes=volumes,
                environment=env or None,
                network_mode="none",
                read_only=True,
                tmpfs=TMPFS,
                mem_limit=MEMORY_LIMIT,
                memswap_limit=MEMORY_LIMIT,
                cpu_period=CPU_PERIOD,
                cpu_quota=CPU_QUOTA,
                pids_limit=PIDS_LIMIT,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                user="sandbox",
            )

            container.start()
            timed_out = False
            oom_killed = False
            exit_code = 124

            try:
                wait_result = container.wait(timeout=TIMEOUT_SECONDS)
                exit_code = int(wait_result.get("StatusCode") or 0)
            except requests.exceptions.ReadTimeout:
                timed_out = True
                exit_code = 124
                try:
                    container.kill()
                except self._docker_exception:
                    # Container exited between the timeout and our kill call;
                    # treat as normal completion and retrieve the real exit code.
                    container.reload()
                    state = container.attrs.get("State", {})
                    exit_code = int(state.get("ExitCode") or 0)
                    timed_out = False

            # Reload to capture OOMKilled (not present in wait result).
            container.reload()
            oom_killed = bool(container.attrs.get("State", {}).get("OOMKilled"))

            stdout, stdout_truncated = self._read_logs(container, stdout=True, stderr=False)
            stderr, stderr_truncated = self._read_logs(container, stdout=False, stderr=True)
            artifacts = self._read_output_files(container, output_files) if output_files else {}

            duration_ms = int((time.monotonic() - started_at) * 1000)
            status = (
                "timed_out"
                if timed_out
                else "oom_killed"
                if oom_killed
                else "error"
                if exit_code != 0
                else "success"
            )
            executions_total.labels(language=language, status=status).inc()
            execution_duration_seconds.labels(language=language).observe(duration_ms / 1000)
            output_bytes_total.labels(language=language, stream="stdout").inc(len(stdout.encode()))
            output_bytes_total.labels(language=language, stream="stderr").inc(len(stderr.encode()))

            LOGGER.info(
                "sandbox_execution_finish",
                extra={
                    "language": language,
                    "image": image,
                    "container_name": container_name,
                    "exit_code": exit_code,
                    "timed_out": timed_out,
                    "oom_killed": oom_killed,
                    "duration_ms": duration_ms,
                    "stdout_bytes": len(stdout.encode("utf-8")),
                    "stderr_bytes": len(stderr.encode("utf-8")),
                    "output_truncated": stdout_truncated or stderr_truncated,
                    "artifact_count": len(artifacts),
                },
            )
            return ExecutionResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                timed_out=timed_out,
                oom_killed=oom_killed,
                output_truncated=stdout_truncated or stderr_truncated,
                duration_ms=duration_ms,
                output_files=artifacts,
            )
        except self._docker_exception as exc:
            error_id = uuid.uuid4().hex[:12]
            LOGGER.exception(
                "sandbox_execution_error",
                extra={
                    "language": language,
                    "image": image,
                    "container_name": container_name,
                    "duration_ms": int((time.monotonic() - started_at) * 1000),
                    "error_type": exc.__class__.__name__,
                    "error_id": error_id,
                },
            )
            # The daemon error may contain host paths and infra details; log it
            # but return only an opaque correlation id to the MCP client.
            raise SandboxError(f"Docker sandbox failed (error_id={error_id})") from exc
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except self._docker_exception as exc:
                    LOGGER.warning(
                        "sandbox_container_remove_failed",
                        extra={"container_name": container_name, "error": str(exc)},
                    )
            if workspace_volume is not None:
                try:
                    workspace_volume.remove(force=True)
                except self._docker_exception as exc:
                    LOGGER.warning(
                        "sandbox_volume_remove_failed",
                        extra={"volume_name": workspace_volume.name, "error": str(exc)},
                    )

    def _gc_orphaned_resources(self) -> None:
        """Remove containers and volumes left by a previous server crash."""
        label_filter = {"label": "managed-by=mcp-code-sandbox"}
        try:
            orphan_containers = self._client.containers.list(all=True, filters=label_filter)
            for c in orphan_containers:
                try:
                    c.remove(force=True)
                    LOGGER.info("sandbox_gc_container_removed", extra={"id": c.short_id})
                except self._docker_exception as exc:
                    LOGGER.warning(
                        "sandbox_gc_container_failed",
                        extra={"id": c.short_id, "error": str(exc)},
                    )
            orphan_volumes = self._client.volumes.list(filters=label_filter)
            for v in orphan_volumes:
                try:
                    v.remove(force=True)
                    LOGGER.info("sandbox_gc_volume_removed", extra={"name": v.name})
                except self._docker_exception as exc:
                    LOGGER.warning(
                        "sandbox_gc_volume_failed",
                        extra={"name": v.name, "error": str(exc)},
                    )
        except self._docker_exception as exc:
            LOGGER.warning("sandbox_gc_failed", extra={"error": str(exc)})

    def _read_output_files(self, container: Any, paths: list[str]) -> dict[str, str]:
        """Read output files from the container and return them base64-encoded."""
        artifacts: dict[str, str] = {}
        for path in paths:
            try:
                bits, _ = container.get_archive(path)
                buf = io.BytesIO()
                total = 0
                oversized = False
                for chunk in bits:
                    total += len(chunk)
                    if total > MAX_OUTPUT_BYTES:
                        oversized = True
                        LOGGER.warning("sandbox_output_file_too_large", extra={"path": path})
                        break
                    buf.write(chunk)
                if not oversized:
                    buf.seek(0)
                    with tarfile.open(fileobj=buf) as tar:
                        for member in tar.getmembers():
                            if member.isfile():
                                f = tar.extractfile(member)
                                if f:
                                    artifacts[path] = base64.b64encode(f.read()).decode()
            except self._docker_exception:
                LOGGER.debug("sandbox_output_file_missing", extra={"path": path})
        return artifacts

    def _read_logs(self, container: Any, *, stdout: bool, stderr: bool) -> tuple[str, bool]:
        """Read one log stream, stopping early once MAX_OUTPUT_BYTES is exceeded."""
        buffer = bytearray()
        truncated = False
        for chunk in container.logs(stdout=stdout, stderr=stderr, stream=True):
            buffer.extend(chunk)
            if len(buffer) > MAX_OUTPUT_BYTES:
                truncated = True
                break
        text, chunk_truncated = truncate_output(bytes(buffer))
        return text, truncated or chunk_truncated

    def _create_workspace_volume(self, image: str, files: Mapping[str, str]) -> Any:
        volume_name = f"mcp-code-sandbox-workspace-{uuid.uuid4().hex}"
        volume = self._client.volumes.create(name=volume_name, labels=_MANAGED_BY_LABEL)
        helper_name = f"mcp-code-sandbox-volume-init-{uuid.uuid4().hex}"
        helper = None
        try:
            helper = self._client.containers.create(
                image=image,
                command=_HELPER_KEEPALIVE_CMD,
                name=helper_name,
                labels=_MANAGED_BY_LABEL,
                detach=True,
                working_dir="/workspace",
                volumes={volume.name: {"bind": "/workspace", "mode": "rw"}},
                network_mode="none",
                read_only=True,
                tmpfs=TMPFS,
                mem_limit=MEMORY_LIMIT,
                memswap_limit=MEMORY_LIMIT,
                cpu_period=CPU_PERIOD,
                cpu_quota=CPU_QUOTA,
                pids_limit=PIDS_LIMIT,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges"],
                user="sandbox",
            )
            helper.start()
            helper.put_archive("/workspace", build_tar(files))
            return volume
        except self._docker_exception:
            try:
                volume.remove(force=True)
            except self._docker_exception:
                pass
            raise
        finally:
            if helper is not None:
                try:
                    helper.remove(force=True)
                except self._docker_exception as exc:
                    LOGGER.warning(
                        "sandbox_helper_remove_failed",
                        extra={"helper_name": helper_name, "error": str(exc)},
                    )


def list_supported_languages() -> dict[str, str]:
    """Return {language: version} for every configured sandbox image."""
    return dict(LANGUAGE_VERSIONS)


def validate_env_vars(env: dict[str, str]) -> dict[str, str]:
    if len(env) > MAX_ENV_VARS:
        raise InvalidProjectFileError(f"Too many env vars: {len(env)} (limit: {MAX_ENV_VARS})")
    for key, val in env.items():
        if not _ENV_KEY_RE.match(key):
            raise InvalidProjectFileError(
                f"Invalid env var name {key!r}. Must match [A-Za-z_][A-Za-z0-9_]*"
            )
        if len(key) > _MAX_ENV_KEY_LEN:
            raise InvalidProjectFileError(f"Env var name too long: {key!r}")
        if len(val) > _MAX_ENV_VAL_LEN:
            raise InvalidProjectFileError(f"Env var value too long for key {key!r}")
    return dict(env)


def validate_output_paths(paths: list[str]) -> list[str]:
    if len(paths) > MAX_OUTPUT_FILES:
        raise InvalidProjectFileError(
            f"Too many output files: {len(paths)} (limit: {MAX_OUTPUT_FILES})"
        )
    for path in paths:
        p = PurePosixPath(path)
        if ".." in p.parts:
            raise InvalidProjectFileError(f"Unsafe output path: {path!r}")
        if not path.startswith("/tmp/"):
            raise InvalidProjectFileError(f"Output path must be under /tmp/: {path!r}")
    return list(paths)


def normalize_language(language: str) -> str:
    normalized = language.strip().lower()
    if normalized not in IMAGES:
        allowed = ", ".join(sorted(IMAGES))
        raise UnsupportedLanguageError(f"Unsupported language: {language!r}. Allowed: {allowed}")
    return normalized


def truncate_output(data: bytes) -> tuple[str, bool]:
    truncated = len(data) > MAX_OUTPUT_BYTES
    if truncated:
        data = data[:MAX_OUTPUT_BYTES]
    return data.decode("utf-8", errors="replace"), truncated


def validate_project_files(files: Mapping[str, str]) -> dict[str, str]:
    if not files:
        raise InvalidProjectFileError("At least one file is required")
    if len(files) > MAX_PROJECT_FILES:
        raise InvalidProjectFileError(f"Too many files: {len(files)} (limit: {MAX_PROJECT_FILES})")

    safe_files: dict[str, str] = {}
    total_bytes = 0
    for raw_path, content in files.items():
        path = PurePosixPath(raw_path.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or not path.name:
            raise InvalidProjectFileError(f"Unsafe file path: {raw_path!r}")
        total_bytes += len(content.encode("utf-8"))
        if total_bytes > MAX_PROJECT_BYTES:
            raise InvalidProjectFileError(
                f"Project too large: exceeds {MAX_PROJECT_BYTES} bytes total"
            )
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
