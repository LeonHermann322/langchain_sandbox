"""Generic interfaces for tools and workflow steps."""

from abc import ABC, abstractmethod
from typing import Any, Dict


class Tool(ABC):
    """Base interface for workflow tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name of the tool."""
        pass

    @abstractmethod
    def invoke(self, *args, **kwargs) -> Any:
        """Execute the tool with given arguments.

        Returns:
            Typically a string or structured data depending on the tool.
        """
        pass


class Step(ABC):
    """Base interface for workflow steps."""

    @abstractmethod
    def execute(
        self, node_cfg: Dict[str, Any], state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute this step.

        Args:
            node_cfg: Node configuration from workflow.json
            state: Current workflow state (generic dict)

        Returns:
            Dictionary of state updates
        """
        pass


class StateSchema:
    """Defines the expected structure of workflow state."""

    def __init__(self, fields: Dict[str, type]):
        """
        Args:
            fields: Mapping of field names to their types (for validation/hints)
        """
        self.fields = fields

    def validate(self, state: Dict[str, Any]) -> bool:
        """Validate state conforms to schema."""
        return all(key in state for key in self.fields)
