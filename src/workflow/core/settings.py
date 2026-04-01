import os
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkflowSettings:
    model_name: str = "llama3.1"
    model_temperature: float = 0
    search_results_count: int = 20
    scrape_user_agent: str = "Mozilla/5.0"
    scrape_timeout_seconds: int = 8
    scrape_max_chars: int = 2500
    scrape_max_listings: int = 7
    log_dir: str = "workflow_logs"
    results_dir: str = "results"
    tesseract_cmd: str = r"E:/Tesseract/tesseract.exe"
    poppler_path: str = r"E:/Poppler/poppler-25.12.0/Library/bin"

    @classmethod
    def from_env(cls) -> "WorkflowSettings":
        return cls(
            model_name=os.getenv("WORKFLOW_MODEL_NAME", cls.model_name),
            model_temperature=float(
                os.getenv("WORKFLOW_MODEL_TEMPERATURE", cls.model_temperature)
            ),
            search_results_count=int(
                os.getenv("WORKFLOW_SEARCH_RESULTS", cls.search_results_count)
            ),
            scrape_user_agent=os.getenv(
                "WORKFLOW_SCRAPE_USER_AGENT", cls.scrape_user_agent
            ),
            scrape_timeout_seconds=int(
                os.getenv("WORKFLOW_SCRAPE_TIMEOUT", cls.scrape_timeout_seconds)
            ),
            scrape_max_chars=int(
                os.getenv("WORKFLOW_SCRAPE_MAX_CHARS", cls.scrape_max_chars)
            ),
            scrape_max_listings=int(
                os.getenv("WORKFLOW_SCRAPE_MAX_LISTINGS", cls.scrape_max_listings)
            ),
            log_dir=os.getenv("WORKFLOW_LOG_DIR", cls.log_dir),
            results_dir=os.getenv("WORKFLOW_RESULTS_DIR", cls.results_dir),
            tesseract_cmd=os.getenv("WORKFLOW_TESSERACT_CMD", cls.tesseract_cmd),
            poppler_path=os.getenv("WORKFLOW_POPPLER_PATH", cls.poppler_path),
        )
