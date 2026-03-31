import json
import operator
import re
from typing import List, TypedDict, Annotated, Dict, Any
from langchain_ollama import ChatOllama
from langchain_community.tools import DuckDuckGoSearchResults
from langgraph.graph import StateGraph, END
from pdf2image import convert_from_path
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"E:/Tesseract/tesseract.exe"


# --- Standard State ---
class AgentState(TypedDict):
    specifications: str
    current_search_query: str
    job_listings: List[dict]
    valid_results: Annotated[List[dict], operator.add]
    critique: str
    iterations: int


class GenericWorkflow:
    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            self.config = json.load(f)
        self.llm = ChatOllama(model="llama3.1", temperature=0)
        self.json_llm = self.llm.bind(format="json")
        self.search_tool = DuckDuckGoSearchResults()

    def _execute_node(self, node_cfg: Dict, state: AgentState):
        print(f"--- Executing Node: {node_cfg['id']} ---")
        node_type = node_cfg["type"]

        # 1. Handle LLM Nodes (Text or JSON)
        if node_type in ["llm", "llm_json"]:
            prompt = node_cfg["prompt"].format(**state)
            model = self.json_llm if node_type == "llm_json" else self.llm
            response = model.invoke(prompt).content

            if node_type == "llm_json":
                data = json.loads(response) if isinstance(response, str) else response
                # Map specific JSON keys to State keys
                updates = {}
                if "output_mapping" in node_cfg:
                    for json_key, state_key in node_cfg["output_mapping"].items():
                        val = data.get(json_key)
                        # Special handling: if mapping to valid_results, filter the job_listings
                        if state_key == "valid_results":
                            updates[state_key] = [
                                state["job_listings"][i]
                                for i in val
                                if i < len(state["job_listings"])
                            ]
                        else:
                            updates[state_key] = val
                updates["iterations"] = state["iterations"] + 1
                return updates
            else:
                return {node_cfg["output_key"]: response.strip().replace('"', "")}

        # 2. Handle Search Tool
        if node_type == "search_tool":
            query = state[node_cfg["input_key"]]
            # Simple clean-up of query
            query = re.sub(r'[()"`]', "", query)
            raw_results = self.search_tool.invoke(query)

            # Auto-parse search results to a list of dicts (Internal Mini-LLM call for structure)
            parse_prompt = f"Convert this text to a JSON list of jobs (title, url, snippet): {raw_results}"
            parsed = self.json_llm.invoke(parse_prompt).content
            jobs = (
                json.loads(parsed).get("jobs", [])
                if isinstance(parsed, str)
                else parsed.get("jobs", [])
            )
            return {node_cfg["output_key"]: jobs}

    def _build_condition(self, condition_cfg: Dict):
        def condition_func(state: AgentState):
            # Evaluate the string condition from JSON safely
            result = eval(condition_cfg["condition"], {"state": state, "len": len})
            return "true" if result else "false"

        return condition_func

    def compile(self):
        builder = StateGraph(AgentState)

        for n in self.config["nodes"]:
            builder.add_node(
                n["id"], lambda state, cfg=n: self._execute_node(cfg, state)
            )

        for source, target in self.config["edges"]:
            builder.add_edge(source, target)

        for ce in self.config["conditional_edges"]:
            mapping = {k: (END if v == "END" else v) for k, v in ce["mapping"].items()}
            builder.add_conditional_edges(
                ce["source"], self._build_condition(ce), mapping
            )

        builder.set_entry_point(self.config["entry_point"])
        return builder.compile()


def doc_ocr(file_path: str, job_location: str) -> str:
    # 1. Convert each PDF page to an image, then OCR it
    resume_text = ""
    try:
        # poppler_path is required on Windows — install via:
        # https://github.com/oschwartz10612/poppler-windows/releases
        # then set the path below:
        pages = convert_from_path(
            file_path,
            dpi=300,  # Higher DPI = better OCR accuracy
            poppler_path=r"E:/Poppler/poppler-25.12.0/Library/bin",  # ← adjust to your install path
        )

        for i, page_image in enumerate(pages):
            page_text = pytesseract.image_to_string(page_image, lang="eng")
            resume_text += page_text + "\n"

    except Exception as e:
        print(f"   ERROR during OCR: {e}")
        return "Junior AI Engineer or Junior Machine Learning Engineer roles in Berlin or Remote."

    # 2. Guard: confirm we got meaningful content
    resume_text = resume_text.strip()
    if not resume_text or len(resume_text) < 100:
        print(f"   ERROR: OCR extracted too little text ({len(resume_text)} chars).")
        return "Junior AI Engineer or Junior Machine Learning Engineer roles in Berlin or Remote."

    print(f"   ✅ OCR extracted {len(resume_text)} characters from resume.")


if __name__ == "__main__":
    RESUME_PATH = "C:/Users/lherm/Downloads/LeonHermannResume_clean.pdf"
    LOCATION = "Berlin"

    specs = doc_ocr(RESUME_PATH, LOCATION)
    workflow = GenericWorkflow("workflow.json")
    app = workflow.compile()

    results = app.invoke(
        {
            "specifications": specs,
            "job_listings": [],
            "valid_results": [],
            "critique": "None",
            "iterations": 0,
        }
    )

    print(f"\nFound {len(results['valid_results'])} jobs.")
    for j in results["valid_results"]:
        print(f"- {j['title']} ({j['url']})")
