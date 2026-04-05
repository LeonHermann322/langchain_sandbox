"""Generic workflow orchestration - decoupled from use cases."""

import uuid
import importlib
from typing import Any, Callable, Dict

from langchain_ollama import ChatOllama

try:
    from langgraph.checkpoint.memory import MemorySaver
except Exception:  # pragma: no cover - version compatibility fallback
    MemorySaver = None

from core.settings import WorkflowSettings
from core.tool_registry import ToolRegistry
from core.types import GenericState, WorkflowConfig
from engine.generic_orchestrator import GenericWorkflowOrchestrator
from nodes.generic_steps import (
    LLMStep,
    LLMToolStep,
    ToolStep,
)
from services.io import WorkflowIO


class GenericWorkflow:
    """Generic workflow engine - can be configured for any use case via JSON."""

    def __init__(
        self,
        config_path: str,
        settings: WorkflowSettings | None = None,
        llm: Any | None = None,
        tool_registry: ToolRegistry | None = None,
        step_factory: Callable[[], Dict[str, Any]] | None = None,
    ):
        """
        Initialize generic workflow.

        Args:
            config_path: Path to workflow.json
            settings: Workflow settings
            llm: Language model instance
            tool_registry: Registry of available tools
            step_factory: Optional factory returning custom step builders by type
        """
        self.settings = settings or WorkflowSettings.from_env()
        self.io = WorkflowIO(self.settings)
        self.config: WorkflowConfig = self.io.load_config(config_path)

        # Initialize LLM
        self.llm = llm or ChatOllama(
            model=self.settings.model_name,
            temperature=self.settings.model_temperature,
        )
        self.json_llm = self.llm.bind(format="json")

        # Initialize tools
        self.tool_registry = tool_registry or ToolRegistry.create_default(self.settings)

        # Allow optional custom step builders keyed by node type.
        custom_step_builders = step_factory() if step_factory else {}

        # Create step executor
        step_executor = self._create_step_executor(custom_step_builders)

        # Initialize orchestrator
        self.orchestrator = GenericWorkflowOrchestrator(
            config=self.config,
            step_executor=step_executor,
        )
        self._app = None
        self._checkpointer = self._create_checkpointer()

    def _create_checkpointer(self):
        """Create a checkpointer from settings with safe fallback to memory."""
        backend = (self.settings.checkpoint_backend or "memory").lower()

        if backend == "sqlite":
            try:
                sqlite_mod = importlib.import_module("langgraph.checkpoint.sqlite")
                SqliteSaver = getattr(sqlite_mod, "SqliteSaver")
            except Exception:
                SqliteSaver = None

            if not SqliteSaver:
                print("[!] SqliteSaver unavailable, falling back to MemorySaver.")
            else:
                sqlite_path = self.settings.checkpoint_sqlite_path
                try:
                    if hasattr(SqliteSaver, "from_conn_string"):
                        return SqliteSaver.from_conn_string(sqlite_path)
                    import sqlite3

                    conn = sqlite3.connect(sqlite_path, check_same_thread=False)
                    return SqliteSaver(conn)
                except Exception as exc:
                    print(f"[!] Failed to initialize sqlite checkpointer: {exc}")
                    print("[!] Falling back to MemorySaver.")

        if MemorySaver:
            return MemorySaver()

        return None

    def _create_step_executor(
        self, custom_step_builders: Dict[str, Any]
    ) -> "DynamicStepExecutor":
        """Create a step executor that dynamically instantiates steps."""
        return DynamicStepExecutor(
            llm=self.llm,
            json_llm=self.json_llm,
            tool_registry=self.tool_registry,
            settings=self.settings,
            custom_step_builders=custom_step_builders,
        )

    def compile(self) -> Any:
        """Compile workflow into executable graph."""
        if self._app is None:
            self._app = self.orchestrator.compile(checkpointer=self._checkpointer)
        return self._app

    def run(
        self, initial_state: GenericState, thread_id: str | None = None
    ) -> GenericState:
        """Execute workflow with canonical LangGraph invoke semantics."""
        return self.run_invoke(initial_state, thread_id=thread_id)

    def run_invoke(
        self, initial_state: GenericState, thread_id: str | None = None
    ) -> GenericState:
        """Execute workflow via direct invoke without stream-side logging."""
        app = self.compile()
        if thread_id is None:
            thread_id = str(initial_state.get("thread_id") or uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        return app.invoke(initial_state, config=config)

    def run_stream(
        self,
        initial_state: GenericState,
        thread_id: str | None = None,
        stream_mode: str = "updates",
        with_logging: bool = False,
    ):
        """Execute workflow and yield LangGraph stream events.

        This enables native observability without adding custom logging behavior
        to node execution logic.
        """
        app = self.compile()
        current_state = dict(initial_state)
        if thread_id is None:
            thread_id = str(initial_state.get("thread_id") or uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        for event in app.stream(initial_state, config=config, stream_mode=stream_mode):
            if stream_mode == "updates" and isinstance(event, dict):
                # Expected shape: {node_id: {partial_state_updates}}
                for node_id, updates in event.items():
                    if isinstance(updates, dict):
                        current_state.update(updates)
                        if with_logging:
                            iteration = current_state.get("iterations", 0)
                            self.io.log_node_state(
                                iteration, str(node_id), current_state
                            )
                        if with_logging and self.settings.stream_log_events:
                            self.io.log_stream_event(
                                thread_id=thread_id,
                                stream_mode=stream_mode,
                                event_type="node_update",
                                payload={
                                    "node_id": str(node_id),
                                    "iteration": current_state.get("iterations", 0),
                                    "updates": updates,
                                },
                            )
                    yield node_id, updates
            else:
                if with_logging and self.settings.stream_log_events:
                    self.io.log_stream_event(
                        thread_id=thread_id,
                        stream_mode=stream_mode,
                        event_type="stream_event",
                        payload={"event": event},
                    )
                yield event


class DynamicStepExecutor:
    """Executor that dynamically creates step instances based on configuration."""

    def __init__(
        self,
        llm: Any,
        json_llm: Any,
        tool_registry: ToolRegistry,
        settings: WorkflowSettings | None = None,
        custom_step_builders: Dict[str, Any] | None = None,
    ):
        self.llm = llm
        self.json_llm = json_llm
        self.tool_registry = tool_registry
        self.settings = settings
        self.custom_step_builders = custom_step_builders or {}
        self._step_instances: Dict[str, Any] = {}

    def execute(self, node_cfg: Dict[str, Any], state: GenericState) -> Dict[str, Any]:
        """Execute a step node."""
        step_type = node_cfg.get("type")
        if not step_type:
            raise ValueError(f"Node {node_cfg.get('id')} missing 'type'")

        # Get or create step instance
        step = self._get_or_create_step(step_type)

        # Execute step
        return step.execute(node_cfg, state)

    def _get_or_create_step(self, step_type: str) -> Any:
        """Get cached step instance or create new one."""
        if step_type not in self._step_instances:
            if step_type in self.custom_step_builders:
                builder = self.custom_step_builders[step_type]
                self._step_instances[step_type] = builder()
                return self._step_instances[step_type]

            # Instantiate step with appropriate dependencies
            if step_type in ["llm", "llm_json"]:
                self._step_instances[step_type] = LLMStep(self.llm, self.json_llm)
            elif step_type in ["tool", "search_tool", "web_scraper"]:
                self._step_instances[step_type] = ToolStep(
                    self.tool_registry, self.settings
                )
            elif step_type == "llm_tool":
                self._step_instances[step_type] = LLMToolStep(
                    self.json_llm, self.tool_registry
                )
            else:
                raise ValueError(f"Unknown step type: {step_type}")

        return self._step_instances[step_type]
