from .io import WorkflowIO

__all__ = ["WorkflowIO", "ResumeExtractor"]


def __getattr__(name):
    if name == "ResumeExtractor":
        from .resume import ResumeExtractor

        return ResumeExtractor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
