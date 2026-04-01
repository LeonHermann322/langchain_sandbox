import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..core.settings import WorkflowSettings
from ..core.types import WorkflowConfig


class WorkflowIO:
    def __init__(self, settings: WorkflowSettings):
        self.settings = settings
        os.makedirs(self.settings.log_dir, exist_ok=True)
        os.makedirs(self.settings.results_dir, exist_ok=True)

    def load_config(self, config_path: str) -> WorkflowConfig:
        with open(config_path, "r", encoding="utf-8") as handle:
            return json.load(handle)

    def log_node_state(
        self, iteration: int, node_id: str, state: Dict[str, Any]
    ) -> str:
        timestamp = datetime.now().strftime("%H-%M-%S_%f")
        log_filename = f"step_{iteration}_{node_id}_{timestamp}.json"
        full_path = Path(self.settings.log_dir) / log_filename
        with open(full_path, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=4)
        return str(full_path)

    def save_final_results(self, location: str, results: Dict[str, Any]) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = (
            Path(self.settings.results_dir) / f"verified_jobs_{timestamp}.json"
        )
        final_output = {
            "search_metadata": {
                "location": location,
                "total_iterations": results["iterations"],
                "jobs_found_count": len(results["valid_results"]),
            },
            "verified_listings": results["valid_results"],
        }
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(final_output, handle, indent=4)
        return str(output_path)
