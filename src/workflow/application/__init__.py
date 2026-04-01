"""Application module - lazy loading to avoid unnecessary dependencies."""

__all__ = [
    "run_main",
    "run_job_search_workflow",
    "create_initial_job_search_state",
    "run_world_main",
    "run_world_building_workflow",
    "create_initial_world_building_state",
]


def __getattr__(name):
    if name in __all__:
        from .app import (
            run_job_search_workflow,
            run_main,
            create_initial_job_search_state,
            run_world_main,
            run_world_building_workflow,
            create_initial_world_building_state,
        )

        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
