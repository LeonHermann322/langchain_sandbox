"""Generic workflow orchestrator that works with any configuration."""

import ast
from typing import Any

from langgraph.graph import END, StateGraph

from core.types import AgentState, GenericState, WorkflowConfig


class GenericWorkflowOrchestrator:
    """Orchestrator that works with generic state and pluggable steps."""

    def __init__(
        self,
        config: WorkflowConfig,
        step_executor: Any,  # Generic step executor
    ):
        self.config = config
        self.step_executor = step_executor

    @staticmethod
    def _build_route_fn(expression: str):
        """Build a route function for LangGraph conditional edges.

        Supports a constrained expression subset used in workflow JSON:
        comparisons, boolean ops, unary not, len(), state[...] and state.get(...).
        """

        tree = ast.parse(expression, mode="eval")

        def _eval(node: ast.AST, state: AgentState):
            if isinstance(node, ast.BoolOp):
                values = [_eval(v, state) for v in node.values]
                if isinstance(node.op, ast.And):
                    return all(values)
                if isinstance(node.op, ast.Or):
                    return any(values)
                raise ValueError("Unsupported boolean operator")

            if isinstance(node, ast.Compare):
                left = _eval(node.left, state)
                for op, comparator in zip(node.ops, node.comparators):
                    right = _eval(comparator, state)
                    if left is None or right is None:
                        if isinstance(op, ast.Eq):
                            ok = left == right
                        elif isinstance(op, ast.NotEq):
                            ok = left != right
                        else:
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
                            raise ValueError("Unsupported comparison operator")
                    if not ok:
                        return False
                    left = right
                return True

            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "len":
                    if len(node.args) != 1:
                        raise ValueError("len expects one argument")
                    return len(_eval(node.args[0], state))
                if isinstance(node.func, ast.Attribute):
                    fn = _eval(node.func, state)
                    args = [_eval(arg, state) for arg in node.args]
                    return fn(*args)
                raise ValueError("Unsupported function call")

            if isinstance(node, ast.Subscript):
                value = _eval(node.value, state)
                key = _eval(node.slice, state)
                if isinstance(value, dict) and key not in value:
                    return None
                return value[key]

            if isinstance(node, ast.Attribute):
                obj = _eval(node.value, state)
                if node.attr == "get" and isinstance(obj, dict):
                    return lambda key, default=None: obj.get(key, default)
                raise ValueError("Unsupported attribute access")

            if isinstance(node, ast.Name):
                if node.id == "state":
                    return state
                raise ValueError(f"Unsupported name: {node.id}")

            if isinstance(node, ast.Constant):
                return node.value

            if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
                return not _eval(node.operand, state)

            raise ValueError(f"Unsupported expression node: {type(node).__name__}")

        def route(state: AgentState) -> str:
            result = bool(_eval(tree.body, state))
            return "true" if result else "false"

        return route

    def compile(self, checkpointer: Any | None = None) -> Any:
        """Compile workflow into a LangGraph executable."""
        # Use a concrete TypedDict schema so LangGraph persists state between nodes.
        builder = StateGraph(AgentState)

        # Add nodes
        for node in self.config["nodes"]:
            builder.add_node(
                node["id"], lambda state, cfg=node: self._execute_node(cfg, state)
            )

        # Add edges
        for source, target in self.config["edges"]:
            builder.add_edge(source, target)

        # Add conditional edges
        for conditional_edge in self.config["conditional_edges"]:
            mapping = {
                key: (END if value == "END" else value)
                for key, value in conditional_edge["mapping"].items()
            }
            builder.add_conditional_edges(
                conditional_edge["source"],
                self._build_route_fn(conditional_edge["condition"]),
                mapping,
            )

        builder.set_entry_point(self.config["entry_point"])
        if checkpointer is not None:
            return builder.compile(checkpointer=checkpointer)
        return builder.compile()

    def _execute_node(self, node_cfg: dict, state: GenericState) -> dict:
        """Execute a single node."""
        return self.step_executor.execute(node_cfg, state)
