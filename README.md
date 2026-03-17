# lambda-tool-python

[![License: LGPL-3.0-or-later](https://img.shields.io/badge/License-LGPL--3.0--or--later-blue.svg)](LICENSE)
[![Python >= 3.10](https://img.shields.io/badge/Python-%3E%3D%203.10-3776ab.svg)](https://python.org)
[![Version: 0.1.0](https://img.shields.io/badge/version-0.1.0-green.svg)](https://github.com/matchcase/lambda-tool-python/releases)

Python bindings for [λ-Tool](https://github.com/matchcase/lambda-tool): safe LLM tool composition with type checking.

λ-Tool is a typed intermediate representation that LLMs generate instead of Python for tool composition. The type checker verifies code is safe before execution -- no missing fields, no unhandled errors, no infinite loops.

## Prerequisites

- Python 3.10+
- The `lambda_tool` CLI binary ([build from source](https://github.com/matchcase/lambda-tool))

```bash
# Build the OCaml CLI
cd lambda-tool
opam install . --deps-only && eval $(opam env)
dune build && dune install
```

## Install

```bash
pip install lambda-tool-python
```

The package auto-discovers the `lambda_tool` binary from PATH, dune build output, or opam install locations.

## Quick Start

```python
from lambda_tool import LambdaTool, LambdaToolError

lt = LambdaTool()

# Type check a program
result = lt.typecheck("let x = 1 + 2 in x")
print(result.type)     # "Int"
print(result.effects)  # []

# Execute with real tool implementations
result = lt.run("""
tool query: String -{Read}-> {rows: List {id: Int, name: String}};

let get_name = fn row: {id: Int, name: String} => row.name in
match exec tool query "SELECT * FROM users" {
  Ok(result) => map get_name result.rows,
  Err(e) => []: String
}
""", executors={
    "query": lambda arg: {"rows": [{"id": 1, "name": "Alice"}]},
})

print(result.value)    # ["Alice"]
print(result.type)     # "List String"
print(result.effects)  # ["Read"]
```

## Error Handling

Type errors are caught before execution:

```python
try:
    lt.typecheck("let x = 1 + true in x")
except LambdaToolError as e:
    print(e.errors)  # ["Type mismatch at line 1, col 9: expected Bool, got Int"]
```

Runtime tool errors are caught and converted to `Err` values:

```python
def flaky_tool(arg):
    raise ConnectionError("network down")

result = lt.run("""
tool fetch: String -{Network}-> String;
match exec tool fetch "url" {
  Ok(data) => data,
  Err(e) => "fallback"
}
""", executors={"fetch": flaky_tool})

print(result.value)  # "fallback"
```

## API Reference

### `LambdaTool(binary=None)`

Create a wrapper instance. Pass `binary` to override auto-discovery of the `lambda_tool` CLI.

### `lt.typecheck(source) -> TypeCheckResult`

Type check without executing. Returns `TypeCheckResult` with:
- `.type` (str) -- the inferred type
- `.effects` (list[str]) -- the required effects (`"Read"`, `"Write"`, `"Network"`)

Raises `LambdaToolError` on parse or type errors.

### `lt.run(source, executors=None) -> RunResult`

Type check and execute. Returns `RunResult` with:
- `.value` -- the program's return value (decoded to Python)
- `.type` (str) -- the inferred type
- `.effects` (list[str]) -- the required effects

Raises `LambdaToolError` on parse, type, or runtime errors.

### Executor Format

Each executor is a Python callable `(arg) -> result`:

|            | Description                                                                                    |
|------------|------------------------------------------------------------------------------------------------|
| **Input**  | Decoded tool argument: `dict` for records, `str`/`int`/`bool` for primitives, `list` for lists |
| **Output** | Any JSON-serializable value (`dict`, `list`, `str`, `int`, `bool`, `None`)                     |
| **Errors** | Raise any exception to signal a tool error (caught and converted to `Err`)                     |

### Value Decoding

| λ-Tool                  | Python                  |
|-------------------------|-------------------------|
| `42`, `true`, `"hello"` | `42`, `True`, `"hello"` |
| `{name = "Alice"}`      | `{"name": "Alice"}`     |
| `[1, 2, 3]`             | `[1, 2, 3]`             |
| `Ok(v)`                 | `("Ok", v)`             |
| `Err(e)`                | `("Err", e)`            |
| `()`                    | `None`                  |

## Testing

```bash
pytest tests/ -v
```

17 tests covering type checking, execution, interactive tool callbacks, traverse, conditionals, and edge cases.

## Related Projects

- [lambda-tool](https://github.com/matchcase/lambda-tool): The core OCaml implementation (type checker, interpreter, CLI)
- [minilambda](https://github.com/matchcase/minilambda): Minimal agent demo using Claude + λ-Tool

## License

LGPL-3.0-or-later. Check [LICENSE](LICENSE) for details.
© Sarthak Shah (matchcase), 2026.
