import json
import re
from typing import Any, Dict

import requests
from bs4 import BeautifulSoup

from ..core.settings import WorkflowSettings
from ..core.types import AgentState, NodeConfig, StateUpdate


class LLMNodeHandler:
    def __init__(self, llm: Any, json_llm: Any):
        self.llm = llm
        self.json_llm = json_llm

    def execute(self, node_cfg: NodeConfig, state: AgentState) -> StateUpdate:
        prompt = node_cfg["prompt"].format(**state)
        node_type = node_cfg["type"]
        model = self.json_llm if node_type == "llm_json" else self.llm
        response = model.invoke(prompt).content

        if node_type == "llm":
            return {node_cfg["output_key"]: response.strip().replace('"', "")}

        updates: StateUpdate = {}
        try:
            data = json.loads(response) if isinstance(response, str) else response
        except json.JSONDecodeError:
            print(f"[!] Error: LLM returned invalid JSON: {response}")
            data = {}

        for json_key, state_key in node_cfg.get("output_mapping", {}).items():
            value = data.get(json_key)
            if state_key == "valid_results":
                updates[state_key] = self._extract_valid_items(value, state)
            else:
                updates[state_key] = (
                    value if value is not None else "No critique provided."
                )

        updates["iterations"] = state["iterations"] + 1
        return updates

    def _extract_valid_items(self, value: Any, state: AgentState) -> list[dict]:
        source_list = state.get(
            "job_listings_with_content", state.get("job_listings", [])
        )
        if value is None or not isinstance(value, list):
            return []

        valid_items: list[dict] = []
        for item in value:
            try:
                idx = int(item)
            except (TypeError, ValueError):
                continue
            if 0 <= idx < len(source_list):
                valid_items.append(source_list[idx])
        return valid_items


class SearchNodeHandler:
    def __init__(self, search_tool: Any, json_llm: Any):
        self.search_tool = search_tool
        self.json_llm = json_llm

    def execute(self, node_cfg: NodeConfig, state: AgentState) -> StateUpdate:
        query = re.sub(r'[()"`]', "", state[node_cfg["input_key"]])
        raw_results = self.search_tool.invoke(query)
        parse_prompt = (
            "Extract only ACTUAL job openings from these results into JSON. "
            "Ignore ads and blogs. Required format: {'jobs': [{'title': '...', 'url': '...', 'snippet': '...'}]}\n\n"
            f"Results: {raw_results}"
        )
        parsed = self.json_llm.invoke(parse_prompt).content

        jobs: list[dict] = []
        try:
            data = json.loads(parsed) if isinstance(parsed, str) else parsed
            jobs = [
                job
                for job in data.get("jobs", [])
                if job.get("url") and "http" in job.get("url")
            ]
        except Exception:
            jobs = []

        return {node_cfg["output_key"]: jobs}


class ScraperNodeHandler:
    def __init__(self, settings: WorkflowSettings):
        self.settings = settings

    def execute(self, node_cfg: NodeConfig, state: AgentState) -> StateUpdate:
        listings = state.get(node_cfg["input_key"], [])
        scraped_listings = []

        for job in listings[: self.settings.scrape_max_listings]:
            url = job.get("url")
            try:
                response = requests.get(
                    url,
                    headers={"User-Agent": self.settings.scrape_user_agent},
                    timeout=self.settings.scrape_timeout_seconds,
                )
                soup = BeautifulSoup(response.text, "html.parser")
                for element in soup(["script", "style"]):
                    element.decompose()
                job["page_content"] = soup.get_text(separator=" ", strip=True)[
                    : self.settings.scrape_max_chars
                ]
            except Exception as exc:
                job["page_content"] = f"Scrape error: {exc}"

            scraped_listings.append(job)

        return {node_cfg["output_key"]: scraped_listings}


class NodeExecutor:
    def __init__(
        self,
        llm_handler: LLMNodeHandler,
        search_handler: SearchNodeHandler,
        scraper_handler: ScraperNodeHandler,
    ):
        self.llm_handler = llm_handler
        self.search_handler = search_handler
        self.scraper_handler = scraper_handler

    def execute(self, node_cfg: NodeConfig, state: AgentState) -> StateUpdate:
        print(f"[*] Agent Running: {node_cfg['id']}")
        node_type = node_cfg["type"]

        if node_type in ["llm", "llm_json"]:
            return self.llm_handler.execute(node_cfg, state)
        if node_type == "search_tool":
            return self.search_handler.execute(node_cfg, state)
        if node_type == "web_scraper":
            return self.scraper_handler.execute(node_cfg, state)

        raise ValueError(f"Unsupported node type: {node_type}")
