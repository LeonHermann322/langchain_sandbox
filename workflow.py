import sys
import argparse
from pathlib import Path

# Add src to path so we can import workflow package
SRC_PATH = Path(__file__).resolve().parent / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def doc_ocr(file_path: str, job_location: str) -> str:
    from services.resume import ResumeExtractor

    return ResumeExtractor().extract(file_path, job_location)


def build_cli() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run workflow modes (jobs or world) from the command line."
    )

    parser.add_argument(
        "--mode",
        choices=["jobs", "world"],
        default="jobs",
        help="Which workflow to run.",
    )

    # Jobs workflow arguments
    parser.add_argument(
        "--resume-path",
        default="C:/Users/lherm/Downloads/LeonHermannResume_clean.pdf",
        help="Path to resume PDF for jobs mode.",
    )
    parser.add_argument(
        "--location",
        default="Berlin",
        help="Location for jobs mode.",
    )
    parser.add_argument(
        "--jobs-config",
        default="workflow.json",
        help="Path to jobs workflow config JSON.",
    )

    # World-building workflow arguments
    parser.add_argument(
        "--world-config",
        default="workflow_world.json",
        help="Path to world-building workflow config JSON.",
    )
    parser.add_argument(
        "--prompt",
        default=None,
        help="World-building specification prompt for world mode.",
    )

    return parser


def main() -> None:
    args = build_cli().parse_args()

    if args.mode == "jobs":
        from application.app import run_job_search_workflow

        run_job_search_workflow(
            config_path=args.jobs_config,
            resume_path=args.resume_path,
            location=args.location,
        )
        return

    # world mode
    from application.app import run_world_building_workflow, run_world_main

    if args.prompt:
        run_world_building_workflow(
            world_specification=args.prompt,
            config_path=args.world_config,
        )
    else:
        run_world_main()


if __name__ == "__main__":
    main()
