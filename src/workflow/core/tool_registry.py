"""Tool registry and built-in tool implementations."""

from typing import Any, Dict

from langchain_community.tools import DuckDuckGoSearchResults
import requests
from bs4 import BeautifulSoup

from .interfaces import Tool
from .settings import WorkflowSettings


class WebSearchTool(Tool):
    """Web search tool using DuckDuckGo."""

    def __init__(self, num_results: int = 20):
        self.num_results = num_results
        self._tool = DuckDuckGoSearchResults(num_results=num_results)

    @property
    def name(self) -> str:
        return "web_search"

    def invoke(self, query: str) -> str:
        """Execute web search and return results."""
        return self._tool.invoke(query)


class WebScraperTool(Tool):
    """Web scraper tool for extracting content from URLs."""

    def __init__(self, settings: WorkflowSettings):
        self.settings = settings

    @property
    def name(self) -> str:
        return "web_scraper"

    def invoke(self, url: str) -> str:
        """Scrape content from a URL."""
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


class ToolRegistry:
    """Registry for managing available tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def invoke(self, tool_name: str, *args, **kwargs) -> Any:
        """Invoke a tool directly."""
        tool = self.get(tool_name)
        if not tool:
            raise ValueError(f"Tool '{tool_name}' not found")
        return tool.invoke(*args, **kwargs)

    @staticmethod
    def create_default(settings: WorkflowSettings) -> "ToolRegistry":
        """Create a registry with built-in tools."""
        registry = ToolRegistry()
        registry.register(WebSearchTool(num_results=settings.search_results_count))
        registry.register(WebScraperTool(settings))
        return registry
