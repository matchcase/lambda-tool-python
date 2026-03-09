"""Tests for the lambda-tool Python package."""

import sys
import os

# Add package to path for testing without install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lambda_tool import LambdaTool, LambdaToolError
import pytest


@pytest.fixture
def lt():
    return LambdaTool()


class TestTypecheck:
    def test_simple_expression(self, lt):
        result = lt.typecheck("let x = 1 + 2 in x")
        assert result.type == "Int"
        assert result.effects == []

    def test_record(self, lt):
        result = lt.typecheck('{name = "Alice", age = 30}')
        assert result.type == "{name: String, age: Int}"

    def test_tool_effects(self, lt):
        code = """
        tool query: String -{Read}-> {name: String};
        match exec tool query "test" {
          Ok(r) => r.name,
          Err(e) => "failed"
        }
        """
        result = lt.typecheck(code)
        assert result.type == "String"
        assert "Read" in result.effects

    def test_type_error(self, lt):
        with pytest.raises(LambdaToolError):
            lt.typecheck("let x = 1 + true in x")

    def test_parse_error(self, lt):
        with pytest.raises(LambdaToolError):
            lt.typecheck("@@invalid@@")


class TestRun:
    def test_simple_expression(self, lt):
        result = lt.run("let x = 1 + 2 in x")
        assert result.value == 3
        assert result.type == "Int"

    def test_record(self, lt):
        result = lt.run('{name = "Alice", age = 30}')
        assert result.value == {"name": "Alice", "age": 30}

    def test_list(self, lt):
        result = lt.run("[1, 2, 3]")
        assert result.value == [1, 2, 3]

    def test_map(self, lt):
        result = lt.run("map (fn x: Int => x * 2) [1, 2, 3]")
        assert result.value == [2, 4, 6]


class TestInteractive:
    def test_single_tool_call(self, lt):
        code = """
        tool query: String -{Read}-> {name: String};
        match exec tool query "SELECT name FROM users" {
          Ok(r) => r.name,
          Err(e) => "failed"
        }
        """
        result = lt.run(
            code,
            executors={"query": lambda arg: {"name": "Alice"}},
        )
        assert result.value == "Alice"

    def test_tool_error_handling(self, lt):
        code = """
        tool query: String -{Read}-> {name: String};
        match exec tool query "bad query" {
          Ok(r) => r.name,
          Err(e) => "error occurred"
        }
        """

        def failing_query(arg):
            raise ConnectionError("database offline")

        result = lt.run(code, executors={"query": failing_query})
        assert result.value == "error occurred"

    def test_traverse_multiple_calls(self, lt):
        code = """
        tool check: String -{Network}-> {ok: Bool};
        let hosts = ["a", "b", "c"] in
        match traverse (fn h: String => exec tool check h) hosts {
          Ok(results) => map (fn r: {ok: Bool} => r.ok) results,
          Err(e) => []: Bool
        }
        """
        call_log = []

        def checker(arg):
            call_log.append(arg)
            return {"ok": True}

        result = lt.run(code, executors={"check": checker})
        assert result.value == [True, True, True]
        assert call_log == ["a", "b", "c"]

    def test_conditional_tool_calls(self, lt):
        code = """
        tool get_size: String -{Read}-> {size: Int};
        tool read_full: String -{Read}-> {content: String};
        tool read_summary: String -{Read}-> {content: String};

        match exec tool get_size "file.txt" {
          Ok(info) =>
            if info.size < 100
            then match exec tool read_full "file.txt" {
              Ok(r) => r.content, Err(e) => "error"
            }
            else match exec tool read_summary "file.txt" {
              Ok(r) => r.content, Err(e) => "error"
            },
          Err(e) => "error"
        }
        """
        executors = {
            "get_size": lambda arg: {"size": 50},
            "read_full": lambda arg: {"content": "full content here"},
            "read_summary": lambda arg: {"content": "summary"},
        }
        result = lt.run(code, executors=executors)
        assert result.value == "full content here"


class TestEdgeCases:
    def test_missing_executor(self, lt):
        """Tool call with no matching executor should produce an Err."""
        code = """
        tool missing: String -{Read}-> {data: String};
        match exec tool missing "test" {
          Ok(r) => r.data,
          Err(e) => "no executor"
        }
        """
        result = lt.run(code, executors={})
        assert result.value == "no executor"

    def test_invalid_binary_path(self):
        """Custom binary path that doesn't exist should fail on use."""
        bad_lt = LambdaTool(binary="/nonexistent/lambda_tool")
        with pytest.raises((LambdaToolError, FileNotFoundError, OSError)):
            bad_lt.typecheck("1")

    def test_error_attributes(self, lt):
        """LambdaToolError should have a list of error strings."""
        with pytest.raises(LambdaToolError) as exc_info:
            lt.typecheck("let x = 1 + true in x")
        assert isinstance(exc_info.value.errors, list)
        assert len(exc_info.value.errors) > 0
        assert isinstance(exc_info.value.errors[0], str)

    def test_empty_input(self, lt):
        """Empty input should produce a parse error."""
        with pytest.raises(LambdaToolError):
            lt.typecheck("")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
