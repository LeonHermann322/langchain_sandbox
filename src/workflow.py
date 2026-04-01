"""Generic workflow orchestration - decoupled from use cases."""

from typing import Any, Callable, Dict

from langchain_ollama import ChatOllama

from core.conditions import SafeConditionEvaluator
from core.settings import WorkflowSettings
from core.tool_registry import ToolRegistry
from core.types import GenericState, WorkflowConfig
from engine.generic_orchestrator import GenericWorkflowOrchestrator
from nodes.generic_steps import (
    LLMStep,
    LLMToolStep,
    StepExecutor,
    StepRegistry,
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
        step_factory: Callable[[str], Any] | None = None,
    ):
        """
        Initialize generic workflow.

        Args:
            config_path: Path to workflow.json
            settings: Workflow settings
            llm: Language model instance
            tool_registry: Registry of available tools
            step_factory: Optional factory function to create custom steps
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

        # Initialize steps registry
        self.step_registry = StepRegistry()
        self._register_default_steps()

        # Allow custom step registration
        if step_factory:
            self._register_custom_steps(step_factory)

        # Create step executor
        step_executor = self._create_step_executor()

        # Initialize orchestrator
        self.orchestrator = GenericWorkflowOrchestrator(
            config=self.config,
            step_executor=step_executor,
            evaluator=SafeConditionEvaluator(),
            workflow_io=self.io,
            state_schema=self.config.get("state_schema", {}),
        )

    def _register_default_steps(self) -> None:
        """Register built-in step types."""
        self.step_registry.register("llm", LLMStep)
        self.step_registry.register("llm_json", LLMStep)
        self.step_registry.register("tool", ToolStep)
        self.step_registry.register("llm_tool", LLMToolStep)
        # Backward compatibility: old type names
        self.step_registry.register("search_tool", ToolStep)
        self.step_registry.register("web_scraper", ToolStep)

    def _register_custom_steps(self, step_factory: Callable) -> None:
        """Register custom steps via factory function."""
        custom_steps = step_factory()
        for step_type, step_class in custom_steps.items():
            self.step_registry.register(step_type, step_class)

    def _create_step_executor(self) -> "DynamicStepExecutor":
        """Create a step executor that dynamically instantiates steps."""
        return DynamicStepExecutor(
            step_registry=self.step_registry,
            llm=self.llm,
            json_llm=self.json_llm,
            tool_registry=self.tool_registry,
            settings=self.settings,
        )

    def compile(self) -> Any:
        """Compile workflow into executable graph."""
        return self.orchestrator.compile()

    def run(self, initial_state: GenericState) -> GenericState:
        """Execute workflow with given initial state."""
        app = self.compile()
        return app.invoke(initial_state)


class DynamicStepExecutor:
    """Executor that dynamically creates step instances based on configuration."""

    def __init__(
        self,
        step_registry: StepRegistry,
        llm: Any,
        json_llm: Any,
        tool_registry: ToolRegistry,
        settings: WorkflowSettings | None = None,
    ):
        self.step_registry = step_registry
        self.llm = llm
        self.json_llm = json_llm
        self.tool_registry = tool_registry
        self.settings = settings
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
