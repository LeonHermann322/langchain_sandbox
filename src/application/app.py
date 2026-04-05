"""Application entry point - configures and runs generic workflow."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from core.settings import WorkflowSettings
from core.types import GenericState
from application.world_native_graph import WorldBuildingNativeWorkflow
from services.io import WorkflowIO
from workflow import GenericWorkflow


def create_initial_job_search_state(
    resume_path: str,
    location: str,
    settings: WorkflowSettings | None = None,
) -> GenericState:
    """
    Create initial state for job search workflow.

    This function demonstrates how to set up a workflow-specific initial state.
    The state structure is defined by the workflow.json, not hardcoded here.
    """
    settings = settings or WorkflowSettings.from_env()
    from services.resume import ResumeExtractor

    # Extract specifications from resume
    specs = ResumeExtractor(settings).extract(resume_path, location)

    # Build initial state - should match the state schema in workflow.json
    # All fields here should be configurable via workflow.json
    return {
        "specifications": specs,
        "current_search_query": "",
        "job_listings": [],
        "job_listings_with_content": [],
        "valid_results": [],
        "critique": "None",
        "search_quality_ok": True,
        "search_quality_feedback": "No search-quality feedback yet.",
        "link_validation_feedback": "No link validation feedback yet.",
        "resume_fit_feedback": "No resume-fit feedback yet.",
        "specificity_feedback": "No page-specificity feedback yet.",
        "link_valid_ids": [],
        "resume_fit_ids": [],
        "specific_offer_ids": [],
        "iterations": 0,
        "location": location,
    }


def run_job_search_workflow(
    config_path: str = "workflow.json",
    resume_path: str = "C:/Users/lherm/Downloads/LeonHermannResume_clean.pdf",
    location: str = "Berlin",
) -> GenericState:
    """
    Run job search workflow.

    The workflow behavior is determined entirely by the JSON configuration,
    not by code. This function just orchestrates the setup and execution.
    """
    settings = WorkflowSettings.from_env()

    # Create generic workflow from configuration
    workflow = GenericWorkflow(config_path, settings=settings)

    # Create initial state
    initial_state = create_initial_job_search_state(resume_path, location, settings)

    # Run workflow
    results = workflow.run(initial_state)

    # Save results
    final_file = workflow.io.save_final_results(location, results)

    print("\nWorkflow Finished.")
    print(f"Total Verified Jobs Found: {len(results.get('valid_results', []))}")
    print(f"Final results saved to: {final_file}")

    return results


def run_main() -> None:
    """Entry point for CLI execution."""
    resume_path = "C:/Users/lherm/Downloads/LeonHermannResume_clean.pdf"
    location = "Berlin"

    run_job_search_workflow(
        config_path="workflow.json",
        resume_path=resume_path,
        location=location,
    )


def create_initial_world_building_state(world_specification: str) -> GenericState:
    """Create initial state for the world-building workflow."""
    return {
        "world_specification": world_specification,
        "detailed_world": "",
        "world_qa_ok": False,
        "world_qa_feedback": "No QA feedback yet.",
        "desired_character_count": 2,
        "characters": [],
        "character_count": 0,
        "story_arcs": [],
        "current_story_arc": {},
        "mentioned_characters": [],
        "character_creation_plan": "",
        "act1_qa_ok": False,
        "act1_qa_feedback": "No Act 1 QA feedback yet.",
        "story_qa_ok": False,
        "story_qa_feedback": "No story QA feedback yet.",
        "story_arc_count": 0,
        "final_story": "",
        "iterations": 0,
    }


def run_world_building_workflow(
    world_specification: str,
    config_path: str = "workflow_world.json",
    detailed_logs: bool = False,
) -> GenericState:
    """Run world-building workflow using native code-defined LangGraph."""
    settings = WorkflowSettings.from_env()
    workflow = WorldBuildingNativeWorkflow(settings=settings)
    initial_state = create_initial_world_building_state(world_specification)

    if detailed_logs:
        io = WorkflowIO(settings)
        app = workflow.compile()
        thread_id = str(initial_state.get("thread_id") or uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        current_state = dict(initial_state)

        for event in app.stream(initial_state, config=config, stream_mode="updates"):
            if isinstance(event, dict):
                for node_id, updates in event.items():
                    if isinstance(updates, dict):
                        current_state.update(updates)
                        io.log_node_state(
                            int(current_state.get("iterations", 0) or 0),
                            str(node_id),
                            current_state,
                        )
                        io.log_stream_event(
                            thread_id=thread_id,
                            stream_mode="updates",
                            event_type="node_update",
                            payload={
                                "node_id": str(node_id),
                                "iteration": int(
                                    current_state.get("iterations", 0) or 0
                                ),
                                "updates": updates,
                            },
                        )
            else:
                io.log_stream_event(
                    thread_id=thread_id,
                    stream_mode="updates",
                    event_type="stream_event",
                    payload={"event": event},
                )

        results = current_state
    else:
        results = workflow.run(initial_state)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(settings.results_dir) / f"world_building_{timestamp}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=2)

    print("\nWorld-Building Workflow Finished.")
    print(f"Final world approved: {results.get('world_qa_ok', False)}")
    print(f"Characters created: {results.get('character_count', 0)}")
    print(f"Final results saved to: {output_path}")

    return results


def run_world_main() -> None:
    """Example entrypoint for world-building workflow."""
    prompt = (
        "Build a science-fantasy world on a tidally locked ocean planet where "
        "civilizations survive on floating biome-cities, energy is harvested from "
        "bioluminescent storms, and diplomacy between city-states is fragile. "
        "Tone: hopeful but politically tense."
    )
    run_world_building_workflow(prompt, detailed_logs=True)
