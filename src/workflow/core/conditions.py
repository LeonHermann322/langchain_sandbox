import ast
from typing import Any

from .types import AgentState


class UnsafeExpressionError(ValueError):
    pass


class SafeConditionEvaluator:
    def build_condition(self, expression: str):
        tree = ast.parse(expression, mode="eval")

        def condition_func(state: AgentState) -> str:
            result = self._eval(tree.body, state)
            return "true" if result else "false"

        return condition_func

    def _eval(self, node: ast.AST, state: AgentState) -> Any:
        if isinstance(node, ast.BoolOp):
            values = [self._eval(v, state) for v in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
            raise UnsafeExpressionError("Unsupported boolean operator")

        if isinstance(node, ast.Compare):
            left = self._eval(node.left, state)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, state)
                # Treat None as a default value (False-y for comparisons)
                if left is None or right is None:
                    # None is treated as "falsy" for comparisons
                    if isinstance(op, ast.Eq):
                        ok = left == right
                    elif isinstance(op, ast.NotEq):
                        ok = left != right
                    else:
                        # For inequalities with None, treat as False
                        return False
                else:
                    if isinstance(op, ast.Lt):
                        ok = left < right
                    elif isinstance(op, ast.LtE):
                        ok = left <= right
                    elif isinstance(op, ast.Gt):
                        ok = left > right
                    elif isinstance(op, ast.GtE):
                        ok = left >= right
                    elif isinstance(op, ast.Eq):
                        ok = left == right
                    elif isinstance(op, ast.NotEq):
                        ok = left != right
                    else:
                        raise UnsafeExpressionError("Unsupported comparison operator")
                if not ok:
                    return False
                left = right
            return True

        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "len":
                if len(node.args) != 1:
                    raise UnsafeExpressionError("len expects one argument")
                return len(self._eval(node.args[0], state))
            raise UnsafeExpressionError("Only len() calls are allowed")

        if isinstance(node, ast.Subscript):
            value = self._eval(node.value, state)
            key = self._eval(node.slice, state)
            # Handle missing keys gracefully
            if isinstance(value, dict) and key not in value:
                return None
            return value[key]

        if isinstance(node, ast.Attribute):
            # Support dict.get() method
            obj = self._eval(node.value, state)
            if node.attr == "get" and isinstance(obj, dict):
                # Return a callable that supports .get(key, default)
                def dict_get(key, default=None):
                    return obj.get(key, default)

                return dict_get
            raise UnsafeExpressionError(f"Attribute access not allowed: {node.attr}")

        if isinstance(node, ast.Name):
            if node.id == "state":
                return state
            raise UnsafeExpressionError(f"Name is not allowed: {node.id}")

        if isinstance(node, ast.Constant):
            return node.value

        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not self._eval(node.operand, state)

        raise UnsafeExpressionError(f"Unsupported expression: {type(node).__name__}")
