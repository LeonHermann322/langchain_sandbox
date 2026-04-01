import sys
import importlib
from pathlib import Path


SRC_PATH = Path(__file__).resolve().parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

workflow_app = importlib.import_module("workflow.application.app")
workflow_resume = importlib.import_module("workflow.services.resume")

JobMatchingWorkflow = workflow_app.JobMatchingWorkflow
run_main = workflow_app.run_main
ResumeExtractor = workflow_resume.ResumeExtractor


GenericWorkflow = JobMatchingWorkflow


def doc_ocr(file_path: str, job_location: str) -> str:
    return ResumeExtractor().extract(file_path, job_location)


if __name__ == "__main__":
    run_main()
