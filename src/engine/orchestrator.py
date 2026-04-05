"""Legacy orchestrator compatibility shim.

Use GenericWorkflowOrchestrator directly in new code.
"""

from .generic_orchestrator import GenericWorkflowOrchestrator as WorkflowOrchestrator

__all__ = ["WorkflowOrchestrator"]
