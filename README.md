# langchain_sandbox

## Overview

This project runs an iterative job discovery workflow powered by LangGraph and LLM-based decision nodes.
It can:

1. Extract candidate profile context from a resume (OCR).
2. Generate search queries.
3. Search and scrape job postings.
4. Validate matches against candidate criteria.
5. Persist step logs and final verified results.

## Package Architecture

The workflow code is now organized in a hierarchical package under `src/workflow`.

### `src/workflow/application`

Application composition and entry flow.

- `app.py`: `JobMatchingWorkflow` orchestration wiring, runtime dependencies, and `run_main()`.

### `src/workflow/core`

Shared core contracts and configuration.

- `types.py`: typed workflow state and config contracts.
- `settings.py`: runtime settings + environment variable loading.
- `conditions.py`: safe condition evaluation for graph branching.

### `src/workflow/engine`

Graph engine assembly and execution.

- `orchestrator.py`: LangGraph compile and node execution loop integration.

### `src/workflow/nodes`

Node execution handlers.

- `handlers.py`: LLM node handling, search parsing, scraping logic, and dispatch.

### `src/workflow/services`

Infrastructure-style services.

- `io.py`: config load, step logging, final result persistence.
- `resume.py`: OCR extraction service for resume text.

### Compatibility Entrypoint

- `workflow.py`: backward-compatible wrapper that imports the modular package and runs `run_main()`.

## Run

Run the workflow from the repository root:

```bash
python workflow.py
```

Outputs are written to:

- `workflow_logs/` for step-by-step state snapshots.
- `results/` for final verified job lists.

## Configuration via Environment Variables

You can override defaults from `WorkflowSettings` with environment variables:

- `WORKFLOW_MODEL_NAME`
- `WORKFLOW_MODEL_TEMPERATURE`
- `WORKFLOW_SEARCH_RESULTS`
- `WORKFLOW_SCRAPE_USER_AGENT`
- `WORKFLOW_SCRAPE_TIMEOUT`
- `WORKFLOW_SCRAPE_MAX_CHARS`
- `WORKFLOW_SCRAPE_MAX_LISTINGS`
- `WORKFLOW_LOG_DIR`
- `WORKFLOW_RESULTS_DIR`
- `WORKFLOW_TESSERACT_CMD`
- `WORKFLOW_POPPLER_PATH`