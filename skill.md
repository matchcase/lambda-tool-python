# λ-Tool: Safe Code Generation for Programmatic Tool Calling

<skill>
name: lambda-tool
description: Guide for generating λ-Tool code for safe Programmatic Tool Calling (PTC). λ-Tool is a typed language that LLMs generate instead of Python to prevent runtime errors in tool compositions.
user-invocable: true
</skill>

## What is λ-Tool?

λ-Tool is a **target language for LLM code generation**. Instead of generating Python for PTC, you generate λ-Tool code. The type checker then verifies your code is safe BEFORE execution.

**You are the intended user.** λ-Tool is designed for LLMs to generate, not humans to write.

---

## Why Not Python?

In Anthropic's PTC, you write Python like this:

```python
# From PTC docs: batch processing with loops
regions = ["West", "East", "Central", "North", "South"]
results = {}
for region in regions:
    data = await query_database(f"<sql for {region}>")
    results[region] = sum(row["revenue"] for row in data)
```

This has runtime failure modes:
| Problem | What Happens |
|---------|--------------|
| `row["revenue"]` but field is `total_revenue` | `KeyError` at runtime |
| `query_database` fails | Unhandled exception crashes program |
| Retry a write after partial failure | Data corruption (double-write) |
| `while True:` with bad exit condition | Infinite loop, timeout |

λ-Tool makes these **compile-time type errors** instead.

---

## λ-Tool Syntax

### Tool Declarations
```
tool query_database: String -{Read}-> {revenue: Int, region: String};
tool send_email: {to: String, body: String} -{Write}-> Unit;
tool fetch_logs: String -{Network}-> List String;
```

Format: `tool <name>: <InputType> -{Effects}-> <OutputType>;`

Effects: `Read`, `Write`, `Network`, `Pure`

### Types
```
Unit, Bool, Int, String           // primitives
{field1: T1, field2: T2}          // record (row type)
[T]                               // list
Result<Ok, Err>                   // fallible result
!T                                // linear (use exactly once)
T1 -{Effects}-> T2                // function
```

### Comments
```
// line comment
(* block comment *)
```
**IMPORTANT**: Comments use `//` or `(* *)`. Do NOT use `--` for comments.

### Expressions
```
// Records
{name = "Alice", age = 30}
record.field

// Functions
fn x: Type => body
f arg

// Let bindings
let x = expr in body

// Tool execution (ALWAYS returns Result)
exec tool <name> <arg>          // for Unit-typed tools, pass (): exec tool foo ()

// Result handling (MANDATORY — Ok branch MUST come before Err branch)
match result {
  Ok(x) => ...,
  Err(e) => ...
}
// WRONG order (will not parse):
// match result { Err(e) => ..., Ok(x) => ... }

// Iteration (NO while, NO recursion)
map f list
fold f init list
filter pred list
traverse f list   // effectful map, short-circuits on error
```

---

## Translating PTC Patterns

### Pattern 1: Batch Processing (from PTC docs)

**Python:**
```python
regions = ["West", "East", "Central"]
results = {}
for region in regions:
    data = await query_database(f"SELECT revenue FROM sales WHERE region='{region}'")
    results[region] = sum(row["revenue"] for row in data)
```

**λ-Tool:**
```
tool query: String -{Read}-> {revenue: Int};

let regions = ["West", "East", "Central"] in
traverse (fn r: String => exec tool query r) regions
```

- `traverse` replaces the `for` loop
- Row type `{revenue: Int}` guarantees field exists
- Returns `Result<[{revenue: Int}], String>` - error handling is mandatory

### Pattern 2: Data Filtering (from PTC docs)

**Python:**
```python
logs = await fetch_logs(server_id)
errors = [log for log in logs if "ERROR" in log]
```

**λ-Tool:**
```
tool fetch_logs: String -{Network}-> List String;

match exec tool fetch_logs server_id {
  Ok(logs) => filter (fn log: String => true) logs,
  Err(e) => []: String
}
```

Note: `[]: String` creates an empty `List String`. The type annotation is the **element type**, not `List String`.

- Must `match` the Result - can't just iterate over a potentially-failed call

### Pattern 3: Early Termination (from PTC docs)

**Python:**
```python
endpoints = ["us-east", "eu-west", "apac"]
for endpoint in endpoints:
    status = await check_health(endpoint)
    if status == "healthy":
        print(f"Found healthy endpoint: {endpoint}")
        break
```

**λ-Tool:**
```
tool check_health: String -{Network}-> {status: String};

let endpoints = ["us-east", "eu-west", "apac"] in
fold (fn acc: Result<String, String> => fn ep: String =>
  match acc {
    Ok(found) => Ok(found),  // already found, skip
    Err(_) =>
      match exec tool check_health ep {
        Ok(r) => if r.status == "healthy" then Ok(ep) else Err("continue"),
        Err(e) => Err(e)
      }
  }
) (Err "none") endpoints
```

### Pattern 4: Conditional Tool Selection (from PTC docs)

**Python:**
```python
file_info = await get_file_info(path)
if file_info["size"] < 10000:
    content = await read_full_file(path)
else:
    content = await read_file_summary(path)
```

**λ-Tool:**
```
tool get_file_info: String -{Read}-> {size: Int};
tool read_full: String -{Read}-> String;
tool read_summary: String -{Read}-> String;

match exec tool get_file_info path {
  Ok(info) =>
    if info.size < 10000
    then exec tool read_full path
    else exec tool read_summary path,
  Err(e) => Err(e)
}
```

---

## The Four Guarantees

When you generate valid λ-Tool code, these are guaranteed:

| Guarantee | Mechanism | What It Prevents |
|-----------|-----------|------------------|
| No missing fields | Row types | `KeyError` / field access on wrong schema |
| No unhandled errors | Mandatory `match` on Result | Silent failures, crashes |
| No unsafe retry | Linear types (`!WriteToken`) | Double-writes, data corruption |
| Termination | No `while`, no recursion | Infinite loops |

---

## Common Mistakes to Avoid

### Wrong: Accessing Result without matching
```
let data = exec tool query "..." in
map (fn r => r.name) data.rows   // TYPE ERROR: data is Result, not record
```

### Right: Match first
```
match exec tool query "..." {
  Ok(data) => map (fn r: {name: String} => r.name) data.rows,
  Err(e) => []: String
}
```

### Wrong: Using while loop
```
while has_more_pages {  // SYNTAX ERROR: no while in λ-Tool
  ...
}
```

### Right: Use bounded fold
```
let page_nums = [1, 2, 3, 4, 5] in  // explicit bound
fold (fn acc => fn page => ...) [] page_nums
```

### Wrong: Reusing write token
```
let token = get_token() in
exec tool write {data = "a", token = token};
exec tool write {data = "b", token = token}  // TYPE ERROR: token consumed
```

### Right: One token per write
```
let token1 = get_token() in
let token2 = get_token() in
exec tool write {data = "a", token = token1};
exec tool write {data = "b", token = token2}
```

---

## Type Error Messages

| Error | Meaning | Fix |
|-------|---------|-----|
| `MissingField "x"` | Field `x` not in row type | Check tool declaration, use correct field name |
| `TypeMismatch: Result vs {..}` | Used Result without matching | Add `match ... { Ok => ..., Err => ... }` |
| `LinearAlreadyUsed "token"` | Reused linear variable | Get a fresh token for each write |
| `UnboundVariable "x"` | Variable not in scope | Check spelling, ensure `let` binding exists |

---

## Summary

1. **Declare tools** with their input/output types and effects
2. **Use `traverse`** instead of `for` loops over tool calls
3. **Always `match`** Results - you cannot ignore errors
4. **Use `fold`** with explicit bounds instead of `while`
5. **Linear tokens** for writes - one token, one write

Generate λ-Tool code. The type checker will verify it's safe.

---

## Integration: Using λ-Tool as a PTC Replacement

λ-Tool replaces the Python sandbox in Anthropic's Programmatic Tool Calling.
Instead of Claude generating unrestricted Python, it generates λ-Tool code
that is type-checked before execution.

### Python Package

```python
from lambda_tool import LambdaTool

lt = LambdaTool()

# Type check only (fast, no execution)
result = lt.typecheck(code)
# result.type = "String", result.effects = ["Read"]

# Type check + execute with real tool implementations
result = lt.run(code, executors={
    "query_database": lambda arg: db.execute(arg),
    "send_email": lambda arg: email.send(**arg),
})
# result.value = "Alice"
```

### PTC Adapter Pattern

In a real agent, the flow is:

1. Describe available tools to Claude (via system prompt or tool definitions)
2. Ask Claude to generate λ-Tool code (invoke this skill)
3. Type check the generated code — reject if unsafe
4. Execute with real tool implementations

```python
import anthropic
from lambda_tool import LambdaTool, LambdaToolError

client = anthropic.Anthropic()
lt = LambdaTool()

# Step 1-2: Claude generates λ-Tool code
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": task}],
    # Use the lambda-tool skill or system prompt to guide generation
)
ltool_code = extract_code(response)

# Step 3-4: Type check and execute safely
try:
    result = lt.run(ltool_code, executors={
        "query": lambda arg: real_db_query(arg),
        "send_email": lambda arg: real_email_send(arg),
    })
except LambdaToolError as e:
    # Type error or runtime error — code was unsafe, reject it
    handle_error(e)
```

### Tool Declaration Mapping

Anthropic tool definitions map directly to λ-Tool tool declarations:

| Anthropic Tool Definition | λ-Tool Declaration |
|---|---|
| `{"name": "query", "input_schema": {"type": "object", "properties": {"sql": {"type": "string"}}}}` | `tool query: String -{Read}-> {rows: List {id: Int}};` |

The key difference: λ-Tool declarations include the **output type**, which
Anthropic tool definitions don't. This is what enables row type checking —
the type checker knows what fields the result will have.

### CLI Protocol

For non-Python hosts, the CLI supports a JSON callback protocol:

```bash
lambda_tool --json --interactive program.ltool
```

When a tool is called, the CLI writes to stdout:
```json
{"tool_call": {"tool": "query", "argument": "SELECT * FROM users"}}
```

The host responds on stdin:
```json
{"tool_result": {"ok": {"rows": [{"id": 1, "name": "Alice"}]}}}
```

This enables integration from any language (TypeScript, Go, Rust, etc.).
