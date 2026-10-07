"""RLM step 2 - LLM-written *Python search plans*, executed in a locked-down sandbox.

The model writes a tiny program, e.g.
    results = []
    results += search("payment failure outage", document_type="incident", date_from="2025-01-01", top_k=15)
    result = results
Safety: AST allow-list (no imports, attributes, dunders, while-loops, comprehensions, arbitrary calls),
empty builtins, a hard call budget, and a timeout enforced by the caller.
"""
import ast
from typing import Callable

ALLOWED_FUNCS = {"search"}
_ALLOWED_NODES = (
    ast.Module, ast.Assign, ast.AugAssign, ast.Expr, ast.Call, ast.Name, ast.Load, ast.Store, ast.Constant,
    ast.List, ast.Tuple, ast.Dict, ast.keyword, ast.For, ast.Add, ast.BinOp, ast.Subscript, ast.Slice,
)


class PlanRejected(Exception):
    pass


class PlanBudgetExceeded(PlanRejected):
    pass


def validate_plan_code(code: str, max_len: int = 4000) -> ast.Module:
    if len(code) > max_len:
        raise PlanRejected("plan too long")
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise PlanRejected(f"syntax error: {exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise PlanRejected(f"disallowed syntax: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise PlanRejected("underscore names are not allowed")
        if isinstance(node, ast.Constant) and isinstance(node.value, (bytes, complex)):
            raise PlanRejected("disallowed literal")
        if isinstance(node, ast.Call) and not (isinstance(node.func, ast.Name) and node.func.id in ALLOWED_FUNCS):
            raise PlanRejected("only search(...) may be called")
    return tree


def run_plan(code: str, search_fn: Callable[..., list[dict]], max_calls: int) -> list[dict]:
    """Execute a validated plan; returns the chunks the plan produced (deduplicated, order preserved)."""
    tree = validate_plan_code(code)
    calls = 0

    def budgeted_search(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls > max_calls:
            raise PlanBudgetExceeded(f"search budget of {max_calls} calls exceeded")
        return search_fn(*args, **kwargs)

    scope: dict = {}
    exec(compile(tree, "<rlm-plan>", "exec"), {"__builtins__": {}, "search": budgeted_search}, scope)  # noqa: S102
    result = scope.get("result", scope.get("results", []))
    if not isinstance(result, list):
        raise PlanRejected("plan must set `result` to a list")
    seen, out = set(), []
    for item in result:
        if isinstance(item, dict) and "chunk_id" in item and item["chunk_id"] not in seen:
            seen.add(item["chunk_id"])
            out.append(item)
    return out
