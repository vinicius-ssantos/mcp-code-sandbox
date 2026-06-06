# AGENTS.md - mcp-code-sandbox

Guide for AI agents connecting to this MCP server.

## What this server does

Executes code and shell commands inside isolated Docker containers and returns stdout, stderr and exit code. Use it whenever you need to run, test or validate code without touching the host system.

Each call is stateless: the server creates a fresh container, executes the request, returns the result and destroys the container.

## Available tools

### `run_code(language, code)`

Run a self-contained code snippet.

```text
language: python | node | java
code:     source code as a string
```

Example:

```python
run_code("python", "import math\nprint(math.pi)")
```

### `run_command(command)`

Run a shell command in the Python sandbox image.

```text
command: any bash command
```

Example:

```python
run_command("python --version && ls -la /tmp")
```

### `run_file(language, files)`

Run a multi-file project. `files` is a dict mapping relative paths to file contents.

```text
language: python | node | java
files:    {"relative/path.ext": "file content", ...}
```

Example:

```python
run_file("python", {
    "main.py": "from lib.util import greet\nprint(greet('world'))",
    "lib/__init__.py": "",
    "lib/util.py": "def greet(name): return f'Hello, {name}!'",
})
```

For Java, always include `Main.java` with a `Main` class.

## Limits

| Limit | Value |
|---|---|
| Execution timeout | 30 seconds |
| Memory | 256 MB |
| CPU | 0.5 cores |
| Network | None |
| Filesystem | Read-only |
| Writable path | `/tmp`, up to 64 MB |
| State between calls | None |

## What you cannot do

- Access the internet or external services from inside a sandbox container.
- Persist installed packages, files or variables between calls.
- Write outside `/tmp`.
- Access the host filesystem.
- Run privileged operations.

## Installing packages inside a run

Package installation can only affect the current call and only if the package is already available from inside the sandbox environment. The default sandbox containers have no network, so dependency-heavy workflows should use prebuilt sandbox images.

## Reading the output

The tool returns a string with these sections when present:

```text
stdout:
<captured stdout>

stderr:
<captured stderr>

exit_code: <int>

status: timed_out
```

A non-zero `exit_code` means the program failed. Check `stderr` for details.
