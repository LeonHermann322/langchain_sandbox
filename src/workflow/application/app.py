from typing import Any

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_ollama import ChatOllama

from ..core.conditions import SafeConditionEvaluator
from ..core.settings import WorkflowSettings
from ..core.types import AgentState
from ..engine.orchestrator import WorkflowOrchestrator
from ..nodes.handlers import (
    LLMNodeHandler,
    NodeExecutor,
    ScraperNodeHandler,
    SearchNodeHandler,
)
from ..services.io import WorkflowIO
from ..services.resume import ResumeExtractor


class JobMatchingWorkflow:
    def __init__(
        self,
        config_path: str,
        settings: WorkflowSettings | None = None,
        llm: Any | None = None,
        search_tool: Any | None = None,
    ):
        self.settings = settings or WorkflowSettings.from_env()
        self.io = WorkflowIO(self.settings)
        self.config = self.io.load_config(config_path)

        self.llm = llm or ChatOllama(
            model=self.settings.model_name,
            temperature=self.settings.model_temperature,
        )
        self.json_llm = self.llm.bind(format="json")
        self.search_tool = search_tool or DuckDuckGoSearchResults(
            num_results=self.settings.search_results_count
        )

        llm_handler = LLMNodeHandler(self.llm, self.json_llm)
        search_handler = SearchNodeHandler(self.search_tool, self.json_llm)
        scraper_handler = ScraperNodeHandler(self.settings)
        node_executor = NodeExecutor(llm_handler, search_handler, scraper_handler)

        self.orchestrator = WorkflowOrchestrator(
            config=self.config,
            node_executor=node_executor,
            evaluator=SafeConditionEvaluator(),
            workflow_io=self.io,
        )

    def compile(self):
        return self.orchestrator.compile()

    def run(self, initial_state: AgentState) -> AgentState:
        app = self.compile()
        return app.invoke(initial_state)


def run_main() -> None:
    resume_path = "C:/Users/lherm/Downloads/LeonHermannResume_clean.pdf"
    location = "Berlin"

    settings = WorkflowSettings.from_env()
    specs = ResumeExtractor(settings).extract(resume_path, location)
    workflow = JobMatchingWorkflow("workflow.json", settings=settings)

    results = workflow.run(
        {
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
        }
    )

    final_file = workflow.io.save_final_results(location, results)

    print("\nWorkflow Finished.")
    print(f"Total Verified Jobs Found: {len(results['valid_results'])}")
    print(f"Final results saved to: {final_file}")
