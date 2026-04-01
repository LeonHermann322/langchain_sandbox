"""Generic step handlers that work with any workflow configuration."""

import json
import re
import time
from typing import Any, Dict

from core.interfaces import Step
from core.settings import WorkflowSettings
from core.tool_registry import ToolRegistry
from core.types import NodeConfig, StateUpdate, GenericState


class _SafeFormatDict(dict):
    def __missing__(self, key):
        return ""


def _invoke_with_optional_temperature(
    model: Any, prompt: str, temperature: float | None
):
    """Invoke model with optional temperature and provider-safe fallback."""
    if temperature is None:
        return model.invoke(prompt)

    # First try common runtime binding.
    try:
        return model.bind(temperature=temperature).invoke(prompt)
    except TypeError:
        # Ollama-style fallback: temperature passed under options.
        return model.bind(options={"temperature": temperature}).invoke(prompt)


class LLMStep(Step):
    """Generic LLM execution step - handles both regular and JSON LLMs."""

    def __init__(self, llm: Any, json_llm: Any):
        self.llm = llm
        self.json_llm = json_llm

    def execute(self, node_cfg: NodeConfig, state: GenericState) -> StateUpdate:
        """Execute LLM with templated prompt."""
        prompt = node_cfg["prompt"].format_map(_SafeFormatDict(state))
        node_type = node_cfg["type"]
        model = self.json_llm if node_type == "llm_json" else self.llm
        temperature = node_cfg.get("temperature")
        response = _invoke_with_optional_temperature(model, prompt, temperature).content

        if node_type == "llm":
            updates: StateUpdate = {
                node_cfg.get("output_key", "output"): response.strip().replace('"', "")
            }
            if node_cfg.get("increment_iterations", False) and "iterations" in state:
                updates["iterations"] = state["iterations"] + 1
            return updates

        # JSON LLM response
        updates: StateUpdate = {}
        try:
            data = json.loads(response) if isinstance(response, str) else response
        except json.JSONDecodeError:
            print(f"[!] Error: LLM returned invalid JSON: {response}")
            data = {}

        # Map JSON response to state according to output_mapping
        for json_key, state_key in node_cfg.get("output_mapping", {}).items():
            value = data.get(json_key)
            if value is not None:
                updates[state_key] = value
            elif state_key.endswith("_qa_ok"):
                # Missing QA decision should never inherit stale previous value.
                updates[state_key] = False
            elif state_key.endswith("_qa_feedback"):
                # Missing QA feedback should be explicit and visible in logs.
                updates[state_key] = "No QA feedback returned."
            elif state_key in state:
                # Preserve previous value instead of poisoning state with placeholders.
                updates[state_key] = state[state_key]

        # Handle iteration counter if configured
        if node_cfg.get("increment_iterations", False) and "iterations" in state:
            updates["iterations"] = state["iterations"] + 1

        return updates


class ToolStep(Step):
    """Generic tool execution step using the tool registry."""

    def __init__(
        self, tool_registry: ToolRegistry, settings: WorkflowSettings | None = None
    ):
        self.tool_registry = tool_registry
        self.settings = settings

    def execute(self, node_cfg: NodeConfig, state: GenericState) -> StateUpdate:
        """Execute a registered tool with inputs from state."""
        tool_name = node_cfg.get("tool")
        input_key = node_cfg.get("input_key")
        output_key = node_cfg.get("output_key", "output")

        if not tool_name:
            raise ValueError(f"Tool step {node_cfg.get('id')} missing 'tool' parameter")
        if not input_key:
            raise ValueError(
                f"Tool step {node_cfg.get('id')} missing 'input_key' parameter"
            )

        # Get input from state
        tool_input = state.get(input_key)
        if not tool_input:
            print(
                f"[!] Warning: Tool input '{input_key}' not found in state for {node_cfg.get('id')}"
            )
            return {output_key: []}

        # Special handling for batch scraper (web_scraper on list of items)
        if (
            tool_name == "web_scraper"
            and isinstance(tool_input, list)
            and self.settings
        ):
            return self._batch_scrape(tool_input, output_key)

        # Execute tool with retry
        result = None
        max_attempts = node_cfg.get("retry_attempts", 3)
        for attempt in range(1, max_attempts + 1):
            try:
                result = self.tool_registry.invoke(tool_name, tool_input)
                break
            except Exception as exc:
                print(f"[!] Tool attempt {attempt}/{max_attempts} failed: {exc}")
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)

        if result is None:
            return {output_key: []}

        # Apply optional processing (e.g., sanitization, parsing)
        if "processor" in node_cfg:
            result = self._apply_processor(node_cfg["processor"], result, state)

        return {output_key: result}

    def _batch_scrape(self, items: list[dict], output_key: str) -> StateUpdate:
        """Scrape batch of items (e.g., job listings)."""
        scraped_items = []
        max_listings = self.settings.scrape_max_listings if self.settings else 7
        for item in items[:max_listings]:
            url = item.get("url")
            if url:
                try:
                    content = self.tool_registry.invoke("web_scraper", url)
                    item_copy = item.copy()
                    item_copy["page_content"] = content
                    scraped_items.append(item_copy)
                except Exception as exc:
                    print(f"[!] Failed to scrape {url}: {exc}")
                    item_copy = item.copy()
                    item_copy["page_content"] = f"Scrape error: {exc}"
                    scraped_items.append(item_copy)
            else:
                # Item without URL, pass through
                scraped_items.append(item)
        return {output_key: scraped_items}

    def _apply_processor(
        self, processor_type: str, data: Any, state: GenericState
    ) -> Any:
        """Apply post-processing to tool output."""
        if processor_type == "parse_json":
            try:
                return json.loads(data) if isinstance(data, str) else data
            except (json.JSONDecodeError, TypeError):
                return {}
        return data


class LLMToolStep(Step):
    """Step combining LLM and tool - LLM processes tool output."""

    def __init__(self, llm: Any, tool_registry: ToolRegistry):
        self.llm = llm
        self.tool_registry = tool_registry

    def execute(self, node_cfg: NodeConfig, state: GenericState) -> StateUpdate:
        """Execute tool, then process results with LLM."""
        tool_name = node_cfg.get("tool")
        input_key = node_cfg.get("input_key")
        output_key = node_cfg.get("output_key", "output")
        parse_prompt_template = node_cfg.get("parse_prompt")

        if not tool_name or not input_key:
            raise ValueError(f"LLMToolStep {node_cfg.get('id')} missing configuration")

        # Execute tool
        tool_input = state.get(input_key)
        if not tool_input:
            return {output_key: []}

        # Execute tool with retry
        raw_results = None
        for attempt in range(1, 4):
            try:
                raw_results = self.tool_registry.invoke(tool_name, tool_input)
                break
            except Exception as exc:
                print(f"[!] Tool attempt {attempt}/3 failed: {exc}")
                if attempt < 3:
                    time.sleep(1.5 * attempt)

        if not raw_results:
            return {output_key: []}

        # Process with LLM if parse prompt is provided
        if parse_prompt_template:
            parse_prompt = parse_prompt_template.format_map(
                _SafeFormatDict({**state, "raw_results": raw_results})
            )
            temperature = node_cfg.get("temperature")
            parsed = _invoke_with_optional_temperature(
                self.llm, parse_prompt, temperature
            ).content

            try:
                data = json.loads(parsed) if isinstance(parsed, str) else parsed
                if isinstance(data, dict) and "jobs" in data:
                    return {output_key: data.get("jobs", [])}
                return {output_key: data}
            except json.JSONDecodeError:
                print(f"[!] LLM parsing failed: {parsed}")
                return {output_key: []}
        else:
            return {output_key: raw_results}


class StepRegistry:
    """Registry for managing available step types."""

    def __init__(self):
        self._steps: Dict[str, type[Step]] = {}

    def register(self, step_type: str, step_class: type[Step]) -> None:
        """Register a step class."""
        self._steps[step_type] = step_class

    def create(self, step_type: str, *args, **kwargs) -> Step:
        """Create a step instance."""
        step_class = self._steps.get(step_type)
        if not step_class:
            raise ValueError(f"Step type '{step_type}' not registered")
        return step_class(*args, **kwargs)

    def is_registered(self, step_type: str) -> bool:
        """Check if a step type is registered."""
        return step_type in self._steps


class StepExecutor:
    """Generic executor that dispatches to the appropriate step handler."""

    def __init__(self, step_registry: StepRegistry):
        self.step_registry = step_registry

    def execute(self, node_cfg: NodeConfig, state: GenericState) -> StateUpdate:
        """Execute a node with the appropriate step handler."""
        print(f"[*] Step Running: {node_cfg.get('id')} (type: {node_cfg.get('type')})")

        step_type = node_cfg.get("type")
        if not step_type:
            raise ValueError(f"Node {node_cfg.get('id')} missing 'type'")

        if not self.step_registry.is_registered(step_type):
            raise ValueError(f"Unsupported step type: {step_type}")

        # Steps are created as singletons per type during registry initialization
        # or we dynamically create them here - this depends on design choice
        # For now, raise error - steps should be registered during setup
        raise NotImplementedError(
            f"Step type '{step_type}' not configured for executor. "
            "Register steps during orchestrator initialization."
        )
