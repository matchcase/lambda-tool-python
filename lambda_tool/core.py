"""Core lambda-Tool wrapper: subprocess-based interface to the OCaml CLI."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable


class LambdaToolError(Exception):
    """Raised when lambda-Tool reports errors."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass
class TypeCheckResult:
    """Result of type checking a lambda-Tool program."""

    type: str
    effects: list[str]


@dataclass
class RunResult:
    """Result of executing a lambda-Tool program."""

    value: Any
    type: str
    effects: list[str]


# Type alias for tool executors: take a decoded argument, return a result
ToolExecutor = Callable[[Any], Any]


def _find_binary() -> str:
    """Find the lambda_tool binary on PATH or in common locations."""
    import os

    # Check PATH
    path = shutil.which("lambda_tool")
    if path:
        return path
    # Check dune build output relative to this package
    pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(pkg_dir, "..", "lambda-tool", "_build", "install", "default", "bin", "lambda_tool"),
        os.path.join(pkg_dir, "..", "lambda-tool", "_build", "default", "bin", "main.exe"),
    ]
    for candidate in candidates:
        candidate = os.path.normpath(candidate)
        if os.path.isfile(candidate):
            return candidate
    # Check common opam location
    opam_bin = os.path.expanduser("~/.opam/default/bin/lambda_tool")
    if os.path.isfile(opam_bin):
        return opam_bin
    raise FileNotFoundError(
        "lambda_tool binary not found. Build with: cd lambda-tool && opam install . --deps-only && dune build && dune install"
    )


def _value_to_python(value: Any) -> Any:
    """Convert a lambda-Tool JSON value to a Python value."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, list):
        return [_value_to_python(v) for v in value]
    if isinstance(value, dict):
        # Check for Ok/Err wrappers
        if "Ok" in value and len(value) == 1:
            return ("Ok", _value_to_python(value["Ok"]))
        if "Err" in value and len(value) == 1:
            return ("Err", _value_to_python(value["Err"]))
        return {k: _value_to_python(v) for k, v in value.items()}
    return value


def _python_to_json(value: Any) -> Any:
    """Convert a Python value to JSON-serializable form for lambda-Tool."""
    if value is None:
        return None
    if isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple)):
        return [_python_to_json(v) for v in value]
    if isinstance(value, dict):
        return {k: _python_to_json(v) for k, v in value.items()}
    return str(value)


def _parse_cli_output(proc: subprocess.CompletedProcess) -> dict:
    """Parse JSON output from the CLI, raising on failures."""
    if not proc.stdout.strip():
        stderr = proc.stderr.strip() if proc.stderr else ""
        msg = f"lambda_tool exited with code {proc.returncode}"
        if stderr:
            msg += f": {stderr}"
        raise LambdaToolError([msg])
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise LambdaToolError(
            [f"Failed to parse lambda_tool output: {e}"]
        ) from e


class LambdaTool:
    """Wrapper around the lambda-Tool CLI binary.

    Provides type checking and execution of lambda-Tool programs,
    with support for real tool implementations via the interactive
    callback protocol.
    """

    def __init__(self, binary: str | None = None):
        """Initialize with optional path to lambda_tool binary."""
        self.binary = binary or _find_binary()

    def typecheck(self, source: str) -> TypeCheckResult:
        """Type check a lambda-Tool program.

        Args:
            source: lambda-Tool source code.

        Returns:
            TypeCheckResult with type and effects.

        Raises:
            LambdaToolError: If the program has type errors.
        """
        proc = subprocess.run(
            [self.binary, "--json", "--typecheck"],
            input=source,
            capture_output=True,
            text=True,
        )
        result = _parse_cli_output(proc)
        if not result.get("ok"):
            raise LambdaToolError(result.get("errors", ["Unknown error"]))
        return TypeCheckResult(type=result["type"], effects=result["effects"])

    def run(
        self,
        source: str,
        executors: dict[str, ToolExecutor] | None = None,
    ) -> RunResult:
        """Type check and execute a lambda-Tool program.

        Args:
            source: lambda-Tool source code.
            executors: Map of tool name to Python callable. Each callable
                receives the tool argument (decoded from JSON) and should
                return a JSON-serializable result. Raise an exception to
                signal a tool error.

        Returns:
            RunResult with value, type, and effects.

        Raises:
            LambdaToolError: If the program has type or runtime errors.
        """
        if executors is None:
            # No executors: run with default (placeholder) executor
            proc = subprocess.run(
                [self.binary, "--json"],
                input=source,
                capture_output=True,
                text=True,
            )
            result = _parse_cli_output(proc)
            if not result.get("ok"):
                raise LambdaToolError(result.get("errors", ["Unknown error"]))
            return RunResult(
                value=_value_to_python(result["value"]),
                type=result["type"],
                effects=result["effects"],
            )

        return self._run_interactive(source, executors)

    def _run_interactive(
        self,
        source: str,
        executors: dict[str, ToolExecutor],
    ) -> RunResult:
        """Run with interactive tool callbacks via temp file + stdin/stdout."""
        import os
        import tempfile

        fd, tmppath = tempfile.mkstemp(suffix=".ltool")
        try:
            with os.fdopen(fd, "w") as f:
                f.write(source)

            proc = subprocess.Popen(
                [self.binary, "--json", "--interactive", tmppath],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                assert proc.stdin is not None
                assert proc.stdout is not None

                while True:
                    line = proc.stdout.readline()
                    if not line:
                        break

                    try:
                        msg = json.loads(line.strip())
                    except json.JSONDecodeError:
                        continue  # skip non-JSON lines (e.g. warnings)

                    if "tool_call" in msg:
                        tool_call = msg["tool_call"]
                        tool_name = tool_call["tool"]
                        argument = _value_to_python(tool_call["argument"])

                        executor = executors.get(tool_name)
                        if executor is None:
                            response = {
                                "tool_result": {
                                    "error": f"no executor for tool '{tool_name}'"
                                }
                            }
                        else:
                            try:
                                result = executor(argument)
                                response = {
                                    "tool_result": {
                                        "ok": _python_to_json(result)
                                    }
                                }
                            except Exception as e:
                                response = {
                                    "tool_result": {"error": str(e)}
                                }

                        try:
                            proc.stdin.write(json.dumps(response) + "\n")
                            proc.stdin.flush()
                        except BrokenPipeError:
                            stderr = proc.stderr.read() if proc.stderr else ""
                            raise LambdaToolError(
                                [f"lambda_tool process died: {stderr}"]
                            )

                    elif "ok" in msg:
                        proc.wait()
                        if not msg["ok"]:
                            raise LambdaToolError(
                                msg.get("errors", ["Unknown error"])
                            )
                        return RunResult(
                            value=_value_to_python(msg["value"]),
                            type=msg["type"],
                            effects=msg["effects"],
                        )

                # Process ended without a result
                proc.wait()
                stderr = proc.stderr.read() if proc.stderr else ""
                raise LambdaToolError(
                    [f"lambda_tool process exited without result: {stderr}"]
                )
            finally:
                proc.kill()
                proc.wait()
        finally:
            os.unlink(tmppath)
