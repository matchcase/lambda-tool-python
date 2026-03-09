"""lambda-tool: Safe LLM tool composition via a prescriptive type system.

This package wraps the lambda-Tool CLI binary, providing a Pythonic API
for type checking and executing lambda-Tool programs with real tool
implementations.

Typical usage as a PTC (Programmatic Tool Calling) adapter:

    from lambda_tool import LambdaTool

    lt = LambdaTool()

    # Type check only
    result = lt.typecheck(code)

    # Execute with real tool implementations
    result = lt.run(code, executors={
        "query": lambda arg: db.execute(arg),
        "send_email": lambda arg: email.send(**arg),
    })
"""

from lambda_tool.core import (
    LambdaTool,
    TypeCheckResult,
    RunResult,
    LambdaToolError,
    ToolExecutor,
)

__version__ = "0.1.0"
__all__ = [
    "LambdaTool",
    "TypeCheckResult",
    "RunResult",
    "LambdaToolError",
    "ToolExecutor",
]
