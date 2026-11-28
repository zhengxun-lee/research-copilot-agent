from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """Abstract base for all agent tools.

    Subclasses must set ``name``, ``description``, and ``parameters`` as class
    or instance attributes, and implement :meth:`run`.
    """

    cost_per_call = None  # Declare a conservative charge in the same currency as LLM prices.
    side_effects: bool = True
    idempotent: bool = False
    name: str = ""
    description: str = ""
    parameters: Dict[str, Any] = {}

    def get_spec(self) -> Dict[str, Any]:
        """Return the OpenAI function-calling tool specification."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    def run(self, **kwargs) -> str:
        """Execute the tool with the given keyword arguments and return a result string."""
        pass