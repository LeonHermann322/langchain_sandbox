# Workflow Configuration Guide

## Quick Start: Job Search Example

The job search workflow is now **configuration-only**. All logic is in `workflow.json`:

```python
# Just configure and run
from src.workflow.application.app import run_job_search_workflow

results = run_job_search_workflow(
    config_path="workflow.json",
    resume_path="path/to/resume.pdf",
    location="Berlin"
)
```

## Node Types Reference

### 1. LLM Node (`type: "llm"`)
Execute LLM with prompt templating, returns raw text.

```json
{
  "id": "summarize",
  "type": "llm",
  "prompt": "Summarize this job posting: {job_content}",
  "output_key": "summary"
}
```

### 2. LLM JSON Node (`type: "llm_json"`)
Execute LLM expecting JSON output, parsed and mapped to state.

```json
{
  "id": "generate_query",
  "type": "llm_json",
  "prompt": "Generate a search query for {candidate_profile}",
  "output_mapping": {
    "query": "search_query",
    "refinement_tips": "tips"
  },
  "increment_iterations": true
}
```

### 3. Tool Node (`type: "tool"`)
Call a registered tool (e.g., web search, web scraper).

```json
{
  "id": "search",
  "type": "tool",
  "tool": "web_search",
  "input_key": "query",
  "output_key": "results",
  "retry_attempts": 3
}
```

### 4. LLM + Tool Node (`type: "llm_tool"`)
Execute tool, then use LLM to parse/process results.

```json
{
  "id": "search_and_parse",
  "type": "llm_tool",
  "tool": "web_search",
  "input_key": "query",
  "output_key": "parsed_results",
  "parse_prompt": "Extract job listings from: {raw_results}. Format as JSON with title, url, snippet.",
  "retry_attempts": 3
}
```

## State Schema

Define expected state fields for documentation and validation:

```json
{
  "state_schema": {
    "search_query": "str",
    "results": "list",
    "analyzed": "bool",
    "iteration": "int"
  }
}
```

## Conditional Routing

Branch execution based on state values:

```json
{
  "conditional_edges": [
    {
      "source": "search_quality_guard",
      "condition": "state['quality_score'] > 0.7",
      "mapping": {
        "true": "scrape_results",
        "false": "retry_search"
      }
    },
    {
      "source": "check_results",
      "condition": "len(state['results']) >= 5 or state['iterations'] >= 10",
      "mapping": {
        "true": "END",
        "false": "refine_search"
      }
    }
  ]
}
```

### Condition Syntax
- Comparison: `==, !=, <, <=, >, >=`
- Boolean logic: `and, or`
- State access: `state['field_name']`
- Python expressions: `len(...)`, function calls

Examples:
- `state['quality'] > 5 and state['attempts'] < 10`
- `len(state['items']) == 0`
- `state['flag'] == True`

## Prompt Templating

Prompts are formatted with current state using `{}` syntax:

```json
{
  "prompt": "Candidate profile: {specifications}\n\nPrevious feedback: {critique}\n\nGenerate better search query."
}
```

All state fields are available for substitution. Missing fields become empty string.

## Built-in Tools

### `web_search`
Search the web using DuckDuckGo.

```json
{
  "type": "tool",
  "tool": "web_search",
  "input_key": "query_text",
  "output_key": "search_results"
}
```

### `web_scraper`
Scrape content from URLs. Supports batch processing of items with URLs.

**Single URL**:
```json
{
  "type": "tool",
  "tool": "web_scraper",
  "input_key": "url",
  "output_key": "page_content"
}
```

**Batch scraping** (list of items with `url` field):
```json
{
  "id": "scraper",
  "type": "tool",
  "tool": "web_scraper",
  "input_key": "job_listings",
  "output_key": "job_listings_with_content"
}
```

Each item gets a `page_content` field added.

## Job Search Workflow Configuration

The complete job matching workflow is defined in `workflow.json`:

1. **query_generator**: Generate search query based on candidate and feedback
2. **searcher**: Execute web search with LLM parsing
3. **search_quality_guard**: Assess search quality
4. **scraper**: Scrape job posting pages
5. **link_validator**: Validate links and openness
6. **resume_fit_validator**: Check resume fit
7. **specificity_validator**: Ensure specific job openings (not listing pages)
8. **feedback_aggregator**: Compile feedback for next iteration

### Loop Mechanics

- **Iteration Counter**: `increment_iterations: true` on `specificity_validator`
- **Continue Condition**: Less than 5 valid results AND less than 12 iterations
- **Success**: Found 5+ valid job postings

### Customization Examples

#### Change Job Focus
Modify `query_generator` prompt:
```json
{
  "id": "query_generator",
  "type": "llm_json",
  "prompt": "Focus on DATA SCIENCE roles in {location}...",
  "output_mapping": { "query": "current_search_query" }
}
```

#### Add Location to Search
Update initial state in `app.py`:
```python
initial_state = {
    "location": "Berlin",
    "specifications": specs,
    ...
}
```

Reference in prompt:
```json
"prompt": "Search for {job_title} roles in {location}"
```

#### Change Iteration Limit
Modify conditional_edges:
```json
{
  "source": "feedback_aggregator",
  "condition": "len(state['valid_results']) < 3 and state['iterations'] < 20",
  "mapping": { "true": "query_generator", "false": "END" }
}
```

#### Add New Validation Step
1. Add node to workflow.json:
```json
{
  "id": "salary_check",
  "type": "llm_json",
  "prompt": "Check if salary mentioned in: {job_listings_with_content}",
  "output_mapping": { "salary_results": "salary_validated" }
}
```

2. Add edge routing:
```json
{ "from": "scraper", "to": "salary_check" }
```

## Advanced Configuration

### Custom Step Types

Define custom step in code:

```python
from src.workflow.core.interfaces import Step

class CustomStep(Step):
    def execute(self, node_cfg, state):
        # Custom logic
        return {"output": result}
```

Reference in workflow:
```json
{ "id": "custom", "type": "custom_type" }
```

### Custom Tools

```python
class PDFReaderTool(Tool):
    @property
    def name(self) -> str:
        return "pdf_reader"
    
    def invoke(self, pdf_path: str) -> str:
        # Extract PDF content
        return content

# Use in workflow
tool_registry.register(PDFReaderTool())
```

Then in workflow.json:
```json
{ "type": "tool", "tool": "pdf_reader", "input_key": "resume_path" }
```

## Troubleshooting

### Node State Not Updating
- Check `output_key` matches where you expect data
- Verify `input_key` exists in state
- Use `output_mapping` for LLM JSON nodes

### LLM Returns Invalid JSON
- Add error handling via conditional edges
- Check `parse_prompt` format expectations
- Format examples in prompt: `{"field": "value"}`

### Tool Returns Empty Results
- Check `input_key` actually contains data
- Verify retry_attempts is set
- Check logs in `workflow_logs/` directory

### Infinite Loop
- Verify condition in conditional_edges with `false` path
- Check `iterations` counter exists in state
- Use `increment_iterations: true` to track loops

## Files Reference

| File | Purpose |
|------|---------|
| `workflow.json` | Workflow definition (use cases) |
| `src/workflow/workflow.py` | Generic workflow engine |
| `src/workflow/core/interfaces.py` | Tool/Step abstractions |
| `src/workflow/core/tool_registry.py` | Tool management |
| `src/workflow/nodes/generic_steps.py` | Step implementations |
| `src/workflow/application/app.py` | Job search entry point |
| `ARCHITECTURE.md` | Detailed architecture docs |

## Migration from Old Code

**Old approach** (hardcoded):
```python
from src.workflow.application.app import JobMatchingWorkflow
workflow = JobMatchingWorkflow("workflow.json")
```

**New approach** (configurable):
```python
from src.workflow.application.app import run_job_search_workflow
results = run_job_search_workflow("workflow.json", resume_path, location)
```

Both work, but the new approach is cleaner and more flexible.
