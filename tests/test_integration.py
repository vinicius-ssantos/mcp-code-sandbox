"""Integration tests — require a live Docker daemon and sandbox images.

Run with:  pytest tests/test_integration.py -v -m integration
Build images first: docker compose --profile build build
"""

import pytest

import server.sandbox as sb
from server.sandbox import DockerSandbox


@pytest.fixture(scope="module")
def sandbox() -> DockerSandbox:
    return DockerSandbox()


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestPython:
    def test_stdout(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("python", "print('hello from python')")
        assert result.exit_code == 0
        assert "hello from python" in result.stdout

    def test_stderr_captured(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("python", "import sys; sys.stderr.write('err\\n')")
        assert result.exit_code == 0
        assert "err" in result.stderr

    def test_nonzero_exit(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("python", "raise SystemExit(42)")
        assert result.exit_code == 42

    def test_case_insensitive_language(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("Python", "print('ok')")
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Node.js
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestNode:
    def test_stdout(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("node", "console.log('hello from node')")
        assert result.exit_code == 0
        assert "hello from node" in result.stdout

    def test_stderr_captured(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("node", "console.error('node err')")
        assert "node err" in result.stderr

    def test_nonzero_exit(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("node", "process.exit(3)")
        assert result.exit_code == 3


# ---------------------------------------------------------------------------
# Bash
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestBash:
    def test_stdout(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("bash", "echo 'hello from bash'")
        assert result.exit_code == 0
        assert "hello from bash" in result.stdout

    def test_nonzero_exit(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("bash", "exit 7")
        assert result.exit_code == 7


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestJava:
    def test_stdout(self, sandbox: DockerSandbox) -> None:
        code = (
            "public class Main {\n"
            "    public static void main(String[] args) {\n"
            '        System.out.println("hello from java");\n'
            "    }\n"
            "}\n"
        )
        result = sandbox.run_code("java", code)
        assert result.exit_code == 0
        assert "hello from java" in result.stdout

    def test_compilation_error(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_code("java", "this is not valid java")
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# run_command
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunCommand:
    def test_echo(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_command("echo 'command ok'")
        assert result.exit_code == 0
        assert "command ok" in result.stdout

    def test_pipeline(self, sandbox: DockerSandbox) -> None:
        result = sandbox.run_command("echo 'foo bar' | tr ' ' '\\n' | sort")
        assert result.exit_code == 0
        assert "bar" in result.stdout
        assert "foo" in result.stdout


# ---------------------------------------------------------------------------
# run_project (multi-file)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestRunProject:
    def test_multifile_python(self, sandbox: DockerSandbox) -> None:
        files = {
            "main.py": "from lib.greet import greet\nprint(greet('world'))\n",
            "lib/__init__.py": "",
            "lib/greet.py": "def greet(name: str) -> str:\n    return f'hello {name}'\n",
        }
        result = sandbox.run_project("python", files)
        assert result.exit_code == 0
        assert "hello world" in result.stdout

    def test_multifile_node(self, sandbox: DockerSandbox) -> None:
        files = {
            "main.js": "const { greet } = require('./lib/greet');\nconsole.log(greet('world'));\n",
            "lib/greet.js": (
                "function greet(name) { return `hello ${name}`; }\nmodule.exports = { greet };\n"
            ),
        }
        result = sandbox.run_project("node", files)
        assert result.exit_code == 0
        assert "hello world" in result.stdout


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_timeout_returns_124(sandbox: DockerSandbox, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sb, "TIMEOUT_SECONDS", 2)
    result = sandbox.run_code("python", "import time; time.sleep(30)")
    assert result.timed_out is True
    assert result.exit_code == 124


# ---------------------------------------------------------------------------
# Security constraints
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestSecurityConstraints:
    def test_no_network_access(self, sandbox: DockerSandbox) -> None:
        code = (
            "import urllib.request\n"
            "try:\n"
            "    urllib.request.urlopen('http://example.com', timeout=2)\n"
            "    print('network ok')\n"
            "except Exception as e:\n"
            "    print(f'no network: {type(e).__name__}')\n"
        )
        result = sandbox.run_code("python", code)
        assert result.exit_code == 0
        assert "no network" in result.stdout

    def test_cannot_write_outside_tmp(self, sandbox: DockerSandbox) -> None:
        code = (
            "try:\n"
            "    open('/etc/pwned', 'w').write('x')\n"
            "    print('wrote')\n"
            "except OSError as e:\n"
            "    print(f'blocked: {e.errno}')\n"
        )
        result = sandbox.run_code("python", code)
        assert result.exit_code == 0
        assert "blocked" in result.stdout

    def test_can_write_to_tmp(self, sandbox: DockerSandbox) -> None:
        code = (
            "open('/tmp/test.txt', 'w').write('persisted')\nprint(open('/tmp/test.txt').read())\n"
        )
        result = sandbox.run_code("python", code)
        assert result.exit_code == 0
        assert "persisted" in result.stdout

    def test_containers_are_isolated(self, sandbox: DockerSandbox) -> None:
        sandbox.run_code("python", "open('/tmp/secret.txt', 'w').write('secret')")
        result = sandbox.run_code(
            "python",
            "import os; print('exists' if os.path.exists('/tmp/secret.txt') else 'clean')",
        )
        assert result.exit_code == 0
        assert "clean" in result.stdout
