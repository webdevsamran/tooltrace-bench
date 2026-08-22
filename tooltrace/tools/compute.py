"""Calculator tool: safe arithmetic evaluation via the ast module.

No eval(); only numeric literals and a fixed operator set are accepted.
"""

from __future__ import annotations

import ast
import operator

from tooltrace.core.registry import tool_registry
from tooltrace.tools.base import Tool, ToolContext, ToolResult

_BIN_OPS: dict[type[ast.operator], object] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}

_UNARY_OPS: dict[type[ast.unaryop], object] = {
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value  # type: ignore[return-value]
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        op = _BIN_OPS[type(node.op)]
        return op(left, right)  # type: ignore[operator,no-any-return]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        operand = _eval_node(node.operand)
        op = _UNARY_OPS[type(node.op)]
        return op(operand)  # type: ignore[operator,no-any-return]
    raise ValueError(f"unsupported expression element: {type(node).__name__}")


@tool_registry.register("calculator")
class CalculatorTool(Tool):
    name: str = "calculator"
    description = "Evaluate an arithmetic expression safely (no eval)."

    def run(self, args: dict[str, object], ctx: ToolContext) -> ToolResult:
        expression = args.get("expression")
        if not isinstance(expression, str) or not expression.strip():
            return ToolResult(ok=False, error="expression must be a non-empty string")
        try:
            tree = ast.parse(expression, mode="eval")
            value = _eval_node(tree)
        except (ValueError, ZeroDivisionError, SyntaxError, OverflowError) as exc:
            return ToolResult(ok=False, error=f"invalid expression: {exc}")
        result = int(value) if isinstance(value, float) and value.is_integer() else value
        return ToolResult(ok=True, output=str(result), data={"value": result})
