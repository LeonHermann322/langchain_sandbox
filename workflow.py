import json
import operator
import re
import os
from datetime import datetime
from typing import List, TypedDict, Annotated, Dict, Any
from langchain_ollama import ChatOllama
from langchain_community.tools import DuckDuckGoSearchResults
from langgraph.graph import StateGraph, END
from pdf2image import convert_from_path
import pytesseract
import requests
from bs4 import BeautifulSoup

pytesseract.pytesseract.tesseract_cmd = r"E:/Tesseract/tesseract.exe"


# --- Standard State ---
class AgentState(TypedDict):
    specifications: str
    current_search_query: str
    job_listings: List[dict]
    job_listings_with_content: List[dict]
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

        # Setup Logging Directories
        self.log_dir = "workflow_logs"
        self.results_dir = "results"  # Added results directory
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.results_dir, exist_ok=True)

    def _execute_node(self, node_cfg: Dict, state: AgentState):
        print(f"[*] Agent Running: {node_cfg['id']}")

        node_type = node_cfg["type"]
        updates = {}

        # 1. Handle LLM Nodes
        if node_type in ["llm", "llm_json"]:
            prompt = node_cfg["prompt"].format(**state)
            model = self.json_llm if node_type == "llm_json" else self.llm
            response = model.invoke(prompt).content

            if node_type == "llm_json":
                try:
                    data = (
                        json.loads(response) if isinstance(response, str) else response
                    )
                except json.JSONDecodeError:
                    print(f"[!] Error: LLM returned invalid JSON: {response}")
                    data = {}

                if "output_mapping" in node_cfg:
                    for json_key, state_key in node_cfg["output_mapping"].items():
                        val = data.get(json_key)

                        if state_key == "valid_results":
                            if val is None:
                                val = []

                            # Determine source (scraped vs raw)
                            source_list = state.get(
                                "job_listings_with_content",
                                state.get("job_listings", []),
                            )

                            if not isinstance(val, list):
                                val = []

                            valid_items = []
                            for i in val:
                                try:
                                    idx = int(i)
                                    if idx < len(source_list):
                                        valid_items.append(source_list[idx])
                                except (ValueError, TypeError):
                                    continue
                            updates[state_key] = valid_items
                        else:
                            updates[state_key] = (
                                val if val is not None else "No critique provided."
                            )

                updates["iterations"] = state["iterations"] + 1
            else:
                updates[node_cfg["output_key"]] = response.strip().replace('"', "")

        # 2. Handle Search Tool
        elif node_type == "search_tool":
            query = re.sub(r'[()"`]', "", state[node_cfg["input_key"]])
            raw_results = self.search_tool.invoke(query)
            parse_prompt = (
                f"Extract only ACTUAL job openings from these results into JSON. "
                f"Ignore ads and blogs. Required format: {{'jobs': [{{'title': '...', 'url': '...', 'snippet': '...'}}]}}\n\n"
                f"Results: {raw_results}"
            )
            parsed = self.json_llm.invoke(parse_prompt).content
            try:
                data = json.loads(parsed) if isinstance(parsed, str) else parsed
                jobs = [
                    j
                    for j in data.get("jobs", [])
                    if j.get("url") and "http" in j.get("url")
                ]
            except:
                jobs = []
            updates[node_cfg["output_key"]] = jobs

        # 3. Handle Scraper
        elif node_type == "web_scraper":
            listings = state.get(node_cfg["input_key"], [])
            scraped_listings = []
            for job in listings[:7]:
                url = job.get("url")
                try:
                    headers = {"User-Agent": "Mozilla/5.0"}
                    resp = requests.get(url, headers=headers, timeout=8)
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for s in soup(["script", "style"]):
                        s.decompose()
                    job["page_content"] = soup.get_text(separator=" ", strip=True)[
                        :2500
                    ]
                    scraped_listings.append(job)
                except Exception as e:
                    job["page_content"] = f"Scrape error: {str(e)}"
                    scraped_listings.append(job)
            updates[node_cfg["output_key"]] = scraped_listings

        # --- LOGGING TO FILE ---
        full_current_state = {**state, **updates}
        timestamp = datetime.now().strftime("%H-%M-%S_%f")
        log_filename = f"step_{state['iterations']}_{node_cfg['id']}_{timestamp}.json"
        with open(os.path.join(self.log_dir, log_filename), "w") as f:
            json.dump(full_current_state, f, indent=4)

        return updates

    def _build_condition(self, condition_cfg: Dict):
        def condition_func(state: AgentState):
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
    resume_text = ""
    try:
        pages = convert_from_path(
            file_path, dpi=300, poppler_path=r"E:/Poppler/poppler-25.12.0/Library/bin"
        )
        for page_image in pages:
            resume_text += pytesseract.image_to_string(page_image, lang="eng") + "\n"
    except Exception:
        return f"Junior AI Engineer in {job_location}"
    resume_text = resume_text.strip()
    if not resume_text or len(resume_text) < 100:
        return f"Junior AI Engineer in {job_location}"
    print(f"✅ OCR Completed ({len(resume_text)} chars)")
    return f"Junior AI roles in {job_location} for a candidate with these skills: {resume_text[:1000]}"


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
            "job_listings_with_content": [],
            "valid_results": [],
            "critique": "None",
            "iterations": 0,
        }
    )

    # --- FINAL RESULTS LOGGING ---
    results_dir = "results"
    os.makedirs(results_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    final_file = os.path.join(results_dir, f"verified_jobs_{timestamp}.json")

    final_output = {
        "search_metadata": {
            "location": LOCATION,
            "total_iterations": results["iterations"],
            "jobs_found_count": len(results["valid_results"]),
        },
        "verified_listings": results["valid_results"],
    }

    with open(final_file, "w") as f:
        json.dump(final_output, f, indent=4)

    print(f"\nWorkflow Finished.")
    print(f"Total Verified Jobs Found: {len(results['valid_results'])}")
    print(f"Final results saved to: {final_file}")
