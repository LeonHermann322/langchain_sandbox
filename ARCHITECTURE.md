# Workflow Architecture - Decoupled Design

## Overview

The workflow system has been refactored to decouple from the job application use case. The application logic is now entirely configurable via JSON, allowing the same workflow engine to be used for any sequential process.

## Key Architectural Concepts

### 1. Generic State System
- **Before**: `AgentState` was a hardcoded TypedDict with job-specific fields
- **After**: `GenericState` is a simple `Dict[str, Any]`
- **Schema Definition**: Workflow `state_schema` in JSON defines expected fields (for validation/documentation)
- **Benefit**: Works with any workflow, any field names, any data types

### 2. Tool Registry (Configurable Tools)
- **Location**: `core/tool_registry.py`
- **Concept**: Tools are pluggable components that can be referenced by name
- **Built-in Tools**:
  - `web_search`: Web search via DuckDuckGo
  - `web_scraper`: Scrapes web page content
- **Usage in Config**: Nodes reference tools by name:
  ```json
  {
    "id": "searcher",
    "type": "tool",
    "tool": "web_search",
    "input_key": "current_search_query",
    "output_key": "job_listings"
  }
  ```

### 3. Step Interface & Generic Steps
- **Location**: `core/interfaces.py`, `nodes/generic_steps.py`
- **Core Steps**:
  - `LLMStep`: Execute LLM prompts with state templating
  - `ToolStep`: Call registered tools with flexible input/output mapping
  - `LLMToolStep`: Combine tool execution with LLM post-processing

- **Example LLM Step**:
  ```json
  {
    "id": "query_generator",
    "type": "llm_json",
    "prompt": "Generate a search query based on {specifications}",
    "output_mapping": {
      "query": "current_search_query"
    }
  }
  ```

### 4. Step Executor (Dynamic Instantiation)
- **Location**: `workflow.py`
- **Concept**: `DynamicStepExecutor` creates step instances on-demand with dependencies
- **Benefit**: Each step type knows how to handle its specific requirements (tool registry, settings, LLM, etc.)

### 5. Generic Orchestrator
- **Location**: `engine/generic_orchestrator.py`
- **Replaces**: Old `WorkflowOrchestrator` (kept for backward compatibility)
- **Improvements**:
  - Works with generic state (no TypedDict required)
  - Separated concerns: orchestration vs step execution

## Workflow Configuration Structure

### New JSON Schema

```json
{
  "description": "Workflow description",
  "state_schema": {
    "field_name": "type_hint"
  },
  "entry_point": "first_node_id",
  "nodes": [
    {
      "id": "unique_node_id",
      "type": "llm|llm_json|tool|llm_tool",
      "tool": "tool_name",              // for tool/llm_tool types
      "prompt": "Template with {vars}",  // for llm types
      "parse_prompt": "...",             // for llm_tool type
      "input_key": "state_field_name",
      "output_key": "state_field_name",
      "output_mapping": { "json_key": "state_key" },  // for llm_json
      "increment_iterations": true,
      "retry_attempts": 3
    }
  ],
  "edges": [["source_node", "target_node"]],
  "conditional_edges": [
    {
      "source": "node_id",
      "condition": "state['field'] == value",
      "mapping": {
        "true": "next_node",
        "false": "other_node"
      }
    }
  ]
}
```

## Job Application Use Case Example

The job search workflow is now a **pure JSON configuration** with no code dependencies:

- **Initial State Setup**: `application/app.py` provides `create_initial_job_search_state()`
- **Workflow Definition**: `workflow.json` defines all steps, prompts, and logic
- **Entry Point**: `run_job_search_workflow()` executes the workflow

### Running Job Search
```python
from src.workflow.application.app import run_job_search_workflow

results = run_job_search_workflow(
    config_path="workflow.json",
    resume_path="path/to/resume.pdf",
    location="Berlin"
)
```

## How to Create a New Workflow

### Step 1: Define Initial State
```python
def create_initial_state(**kwargs) -> GenericState:
    return {
        "input_data": kwargs.get("input"),
        "results": [],
        # ... other fields needed
    }
```

### Step 2: Create Workflow JSON
```json
{
  "state_schema": { /* fields */ },
  "entry_point": "first_step",
  "nodes": [
    {
      "id": "first_step",
      "type": "tool",
      "tool": "web_search",
      "input_key": "search_query",
      "output_key": "search_results"
    },
    {
      "id": "analyze",
      "type": "llm_json",
      "prompt": "Analyze {search_results}",
      "output_mapping": { "analysis": "analysis" }
    }
  ],
  "edges": [["first_step", "analyze"]],
  "conditional_edges": []
}
```

### Step 3: Run Workflow
```python
from src.workflow.workflow import GenericWorkflow

workflow = GenericWorkflow("my_workflow.json")
results = workflow.run(initial_state)
```

## Adding Custom Tools

```python
from src.workflow.core.interfaces import Tool

class MyCustomTool(Tool):
    @property
    def name(self) -> str:
        return "my_custom_tool"
    
    def invoke(self, input_data: str) -> Any:
        # Process input
        return result

# Register
tool_registry = workflow.tool_registry
tool_registry.register(MyCustomTool())
```

## Removed Job-Specific Code

The following job-specific logic has been **removed from code** and is now **configured in JSON**:

1. ✅ Search query generation prompts → `workflow.json` node prompts
2. ✅ Job validation logic → LLM steps in `workflow.json`
3. ✅ Search quality assessment → LLM step configured via prompt
4. ✅ Resume fit evaluation → LLM step with candidate specs
5. ✅ Link validation → LLM step
6. ✅ Page specificity checking → LLM step  
7. ✅ Feedback aggregation → LLM step
8. ✅ Iteration logic → Conditional edges in `workflow.json`

## Migration Path for Existing Code

**Old Way (Hardcoded)**:
```python
workflow = JobMatchingWorkflow("workflow.json")
```

**New Way (Flexible)**:
```python
workflow = GenericWorkflow("workflow.json")
workflow.run(initial_state)
```

The old `JobMatchingWorkflow` is deprecated but can still be used for backward compatibility.

## Configuration Examples

### Example 1: Data Processing Pipeline
```json
{
  "entry_point": "load_data",
  "nodes": [
    { "id": "load_data", "type": "tool", "tool": "file_reader", ... },
    { "id": "transform", "type": "llm_json", "prompt": "Transform: {data}", ... },
    { "id": "validate", "type": "tool", "tool": "validator", ... }
  ],
  "edges": [["load_data", "transform"], ["transform", "validate"]]
}
```

### Example 2: Web Content Analysis
```json
{
  "entry_point": "search",
  "nodes": [
    { "id": "search", "type": "tool", "tool": "web_search", ... },
    { "id": "scrape", "type": "tool", "tool": "web_scraper", ... },
    { "id": "analyze", "type": "llm_json", "prompt": "Summarize: {content}", ... }
  ]
}
```

## Testing & Debugging

### Enable Logging
All node executions are logged to `workflow_logs/` directory:
```
step_{iteration}_{node_id}_{timestamp}.json
```

### State Validation
Check `state_schema` in workflow.json for expected fields:
```python
workflow.orchestrator.state_schema
```

### Custom Debugging
Modify prompt templates in workflow.json to add intermediate logging via LLM steps.

## Performance Considerations

- **Tool Execution**: Retry logic configurable per node (`retry_attempts`)
- **Batch Operations**: Web scraper handles batch processing of items
- **Settings**: Global settings in `core/settings.py` (timeouts, max results, etc.)

## API Reference

## GenericWorkflow

```python
class GenericWorkflow:
    def __init__(
        self,
        config_path: str,
        settings: WorkflowSettings | None = None,
        llm: Any | None = None,
        tool_registry: ToolRegistry | None = None,
        step_factory: Callable[[str], Any] | None = None,
    )
    
    def compile(self) -> Any
    def run(self, initial_state: GenericState) -> GenericState
```

## Tool Interface

```python
class Tool(ABC):
    @property
    def name(self) -> str: ...
    
    def invoke(self, *args, **kwargs) -> Any: ...
```

## Step Interface

```python
class Step(ABC):
    def execute(
        self,
        node_cfg: Dict[str, Any],
        state: Dict[str, Any]
    ) -> Dict[str, Any]: ...
```
