import json
import operator
import time
import random
import re
from typing import List, TypedDict, Annotated, Dict, Any, Callable

from langchain_community.tools import DuckDuckGoSearchResults
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, END
from pytesseract import pytesseract
from pdf2image import convert_from_path

# --- Configuration & State ---


class AgentState(TypedDict):
    specifications: str
    current_search_query: str
    job_listings: List[dict]
    valid_results: Annotated[List[dict], operator.add]
    critique: str
    iterations: int


# Global LLM instance
llm = ChatOllama(model="llama3.1", temperature=0)
json_llm = llm.bind(format="json")
search_tool = DuckDuckGoSearchResults()


# --- Node Implementation Registry ---
# This class contains the logic that the JSON refers to
class NodeImplementations:
    @staticmethod
    def query_optimizer(state: AgentState, params: Dict):
        prompt = f"""Target: {state['specifications']}
        Feedback: {state.get('critique', 'None')}
        Create a search query (max {params.get('max_words', 7)} words). No booleans. Single line output."""

        response = llm.invoke(prompt).content.strip().replace('"', "")
        # Basic sanitization
        query = re.sub(r'[()"`]', "", response)
        print(f"   [Optimizer] Query: {query}")
        return {"current_search_query": query}

    @staticmethod
    def search_and_parse(state: AgentState, params: Dict):
        query = state["current_search_query"]
        raw_results = ""
        try:
            raw_results = search_tool.invoke(query)
        except Exception as e:
            print(f"   [Searcher] Error: {e}")

        parsing_prompt = f"Extract jobs into JSON format (keys: title, url, snippet) from: {raw_results}"
        try:
            response = json_llm.invoke(parsing_prompt)
            data = (
                json.loads(response.content)
                if isinstance(response.content, str)
                else response.content
            )
            return {"job_listings": data.get("jobs", [])}
        except:
            return {"job_listings": []}

    @staticmethod
    def batch_validator(state: AgentState, params: Dict):
        jobs_formatted = json.dumps(state["job_listings"])
        prompt = f"""Criteria: {state['specifications']}
        Jobs: {jobs_formatted}
        Return JSON with 'passed_ids' (indices) and 'feedback'."""

        try:
            res = json_llm.invoke(prompt)
            data = (
                json.loads(res.content) if isinstance(res.content, str) else res.content
            )
            passed_ids = data.get("passed_ids", [])
            valid = [
                state["job_listings"][i]
                for i in passed_ids
                if i < len(state["job_listings"])
            ]

            print(
                f"   [Validator] Found {len(valid)} valid jobs. Feedback: {data.get('feedback')}"
            )
            return {
                "valid_results": valid,
                "critique": data.get("feedback", ""),
                "iterations": state["iterations"] + 1,
                "job_listings": [],  # Clear buffer
            }
        except:
            return {"iterations": state["iterations"] + 1}


# --- Router Functions ---
def check_completion(state: AgentState):
    if len(state["valid_results"]) >= 5 or state["iterations"] >= 3:
        return "end"
    return "continue"


# --- The Workflow Engine ---


class WorkflowEngine:
    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            self.config = json.load(f)
        self.nodes_registry = NodeImplementations()
        self.router_registry = {"check_completion": check_completion}

    def _make_node_func(self, node_cfg: Dict) -> Callable:
        """Wraps registry functions with their JSON parameters."""
        func_name = node_cfg["function"]
        params = node_cfg.get("params", {})
        target_func = getattr(self.nodes_registry, func_name)

        def node_wrapper(state: AgentState):
            return target_func(state, params)

        return node_wrapper

    def build(self):
        workflow = StateGraph(AgentState)

        # 1. Add Nodes
        for node_cfg in self.config["nodes"]:
            workflow.add_node(node_cfg["id"], self._make_node_func(node_cfg))

        # 2. Add Static Edges
        for source, target in self.config["edges"]:
            workflow.add_edge(source, target)

        # 3. Add Conditional Edges
        for c_edge in self.config["conditional_edges"]:
            condition_func = self.router_registry[c_edge["condition_function"]]
            # Map "END" string to the actual constant
            mapping = {
                k: (END if v == "END" else v) for k, v in c_edge["mapping"].items()
            }

            workflow.add_conditional_edges(c_edge["source"], condition_func, mapping)

        workflow.set_entry_point(self.config["entry_point"])
        return workflow.compile()


# --- OCR Helper (Standalone) ---


def perform_ocr(file_path, location):
    # (Existing OCR logic from your code here...)
    # Simplified for brevity:
    print(f"Processing resume for location: {location}...")
    return f"Junior AI Developer roles in {location} with Python and LLM skills."


# --- Execution ---

if __name__ == "__main__":
    # 1. Setup Input
    RESUME_PATH = "C:/Users/lherm/Downloads/LeonHermannResume_clean.pdf"
    LOCATION = "Berlin"

    specs = perform_ocr(RESUME_PATH, LOCATION)

    # 2. Build Graph from JSON
    # Assuming the JSON above is saved as 'workflow_config.json'
    engine = WorkflowEngine("D:/langchain_sandbox/workflow.json")
    app = engine.build()

    # 3. Run
    initial_state = {
        "specifications": specs,
        "job_listings": [],
        "valid_results": [],
        "critique": "None",
        "iterations": 0,
    }

    final_state = app.invoke(initial_state)

    print("\n--- FINAL RESULTS ---")
    for job in final_state["valid_results"]:
        print(f"Title: {job['title']} | URL: {job['url']}")
