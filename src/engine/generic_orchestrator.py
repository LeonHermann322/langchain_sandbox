"""Generic workflow orchestrator that works with any configuration."""

from typing import Any, Dict

from langgraph.graph import END, StateGraph

from core.conditions import SafeConditionEvaluator
from core.types import AgentState, GenericState, WorkflowConfig
from services.io import WorkflowIO


class GenericWorkflowOrchestrator:
    """Orchestrator that works with generic state and pluggable steps."""

    def __init__(
        self,
        config: WorkflowConfig,
        step_executor: Any,  # Generic step executor
        evaluator: SafeConditionEvaluator,
        workflow_io: WorkflowIO,
        state_schema: Dict[str, Any] | None = None,
    ):
        self.config = config
        self.step_executor = step_executor
        self.evaluator = evaluator
        self.workflow_io = workflow_io
        self.state_schema = state_schema or {}

    def compile(self) -> Any:
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
                self.evaluator.build_condition(conditional_edge["condition"]),
                mapping,
            )

        builder.set_entry_point(self.config["entry_point"])
        return builder.compile()

    def _execute_node(self, node_cfg: dict, state: GenericState) -> dict:
        """Execute a single node and log results."""
        updates = self.step_executor.execute(node_cfg, state)

        # Preserve critical state fields that should never be lost
        # (iterations, valid_results, etc.)
        critical_fields = {"iterations", "valid_results"}
        for field in critical_fields:
            if field in state and field not in updates:
                updates[field] = state[field]

        full_current_state = {**state, **updates}

        # Log if iteration tracking is enabled
        iteration = full_current_state.get("iterations", 0)
        self.workflow_io.log_node_state(iteration, node_cfg["id"], full_current_state)

        return updates
