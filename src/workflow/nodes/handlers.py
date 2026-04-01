import json
import re
import time
from typing import Any, Dict
from urllib.parse import urlparse

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

        if node_cfg.get("increment_iterations", True):
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

        # Networked search can fail intermittently; retry briefly before fallback.
        raw_results: Any = []
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):
            try:
                raw_results = self.search_tool.invoke(query)
                break
            except Exception as exc:
                print(
                    f"[!] Search attempt {attempt}/{max_attempts} failed for query '{query}': {exc}"
                )
                if attempt < max_attempts:
                    time.sleep(1.5 * attempt)

        if not raw_results:
            print(
                "[!] Search returned no raw results; skipping parse step for this round."
            )
            return {node_cfg["output_key"]: []}

        parse_prompt_template = node_cfg.get(
            "parse_prompt",
            "Extract only ACTUAL job openings from these results into JSON. "
            "Ignore ads and blogs. Required format: {'jobs': [{'title': '...', 'url': '...', 'snippet': '...'}]}\n\n"
            "Results: {raw_results}",
        )
        parse_prompt = parse_prompt_template.format(**state, raw_results=raw_results)
        parsed = self.json_llm.invoke(parse_prompt).content

        jobs: list[dict] = []
        try:
            data = json.loads(parsed) if isinstance(parsed, str) else parsed
            jobs = self._sanitize_jobs(data.get("jobs", []))
        except Exception:
            jobs = []

        return {node_cfg["output_key"]: jobs}

    def _sanitize_jobs(self, jobs: list[dict]) -> list[dict]:
        blocked_domains = {"example.com", "www.example.com"}
        cleaned: list[dict] = []
        seen_urls: set[str] = set()

        for job in jobs:
            url = (job.get("url") or "").strip()
            if not url.startswith("http"):
                continue

            domain = (urlparse(url).hostname or "").lower()
            if domain in blocked_domains:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)
            cleaned.append(job)

        return cleaned


class ScraperNodeHandler:
    def __init__(self, settings: WorkflowSettings):
        self.settings = settings

    def execute(self, node_cfg: NodeConfig, state: AgentState) -> StateUpdate:
        listings = state.get(node_cfg["input_key"], [])
        scraped_listings = []

        for job in listings[: self.settings.scrape_max_listings]:
            url = job.get("url")
            job["page_content"] = self._scrape_url(url)

            scraped_listings.append(job)

        return {node_cfg["output_key"]: scraped_listings}

    def _scrape_url(self, url: str) -> str:
        headers = {"User-Agent": self.settings.scrape_user_agent}
        last_exception: Exception | None = None

        for _ in range(self.settings.scrape_retry_attempts + 1):
            try:
                response = requests.get(
                    url,
                    headers=headers,
                    timeout=self.settings.scrape_timeout_seconds,
                    verify=requests.certs.where(),
                )
                soup = BeautifulSoup(response.text, "html.parser")
                for element in soup(["script", "style"]):
                    element.decompose()
                return soup.get_text(separator=" ", strip=True)[
                    : self.settings.scrape_max_chars
                ]
            except requests.exceptions.SSLError as exc:
                last_exception = exc
                if not self.settings.scrape_allow_insecure_tls_fallback:
                    break
                try:
                    response = requests.get(
                        url,
                        headers=headers,
                        timeout=self.settings.scrape_timeout_seconds,
                        verify=False,
                    )
                    soup = BeautifulSoup(response.text, "html.parser")
                    for element in soup(["script", "style"]):
                        element.decompose()
                    return soup.get_text(separator=" ", strip=True)[
                        : self.settings.scrape_max_chars
                    ]
                except Exception as insecure_exc:
                    last_exception = insecure_exc
            except Exception as exc:
                last_exception = exc

        return f"Scrape error: {last_exception}"


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
