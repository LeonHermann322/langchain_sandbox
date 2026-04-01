from typing import Any

from langgraph.graph import END, StateGraph

from ..core.conditions import SafeConditionEvaluator
from ..core.types import AgentState, WorkflowConfig
from ..nodes.handlers import NodeExecutor
from ..services.io import WorkflowIO


class WorkflowOrchestrator:
    def __init__(
        self,
        config: WorkflowConfig,
        node_executor: NodeExecutor,
        evaluator: SafeConditionEvaluator,
        workflow_io: WorkflowIO,
    ):
        self.config = config
        self.node_executor = node_executor
        self.evaluator = evaluator
        self.workflow_io = workflow_io

    def compile(self) -> Any:
        builder = StateGraph(AgentState)

        for node in self.config["nodes"]:
            builder.add_node(
                node["id"], lambda state, cfg=node: self._execute_node(cfg, state)
            )

        for source, target in self.config["edges"]:
            builder.add_edge(source, target)

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

    def _execute_node(self, node_cfg: dict, state: AgentState) -> dict:
        updates = self.node_executor.execute(node_cfg, state)
        full_current_state = {**state, **updates}
        self.workflow_io.log_node_state(
            state["iterations"], node_cfg["id"], full_current_state
        )
        return updates
