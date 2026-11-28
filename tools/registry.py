from typing import Dict, List
from tools.base import BaseTool
from tools.calculator import CalculatorTool
from tools.knowledge import KnowledgeSearchTool
from tools.summarizer import SummarizerTool


class ToolRegistry:
    """In-memory registry of :class:`BaseTool` instances available to the agent."""

    def __init__(self):
        self.tools: Dict[str, BaseTool] = {}
        self._register_default_tools()

    def _register_default_tools(self):
        self.register(CalculatorTool())
        self.register(KnowledgeSearchTool())
        self.register(SummarizerTool())

    def register(self, tool: BaseTool):
        self.tools[tool.name] = tool

    def get_tool_specs(self) -> List[dict]:
        return [tool.get_spec() for tool in self.tools.values()]

    def execute(self, tool_name: str, arguments: dict) -> str:
        try:
            return self.execute_strict(tool_name, arguments)
        except Exception as e:
            return f"Error while executing tool '{tool_name}': {str(e)}"

    def execute_strict(self, tool_name: str, arguments: dict) -> str:
        """Runtime entry point: expose failures for events and recovery."""
        tool = self.tools.get(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found.")
        runner = getattr(tool, 'run_strict', tool.run)
        result = runner(**arguments)
        if isinstance(result, str) and result.startswith('Error'):
            from agent.recovery import RuntimeFailure, ErrorKind
            raise RuntimeFailure(ErrorKind.ARGUMENTS, result)
        return result

    def execute_with_context(self, tool_name, arguments, idempotency_key):
        """Side-effect adapters may implement run_idempotent(key, **arguments).

        The downstream service must enforce the key; the registry cannot undo I/O.
        """
        tool = self.tools.get(tool_name)
        runner = getattr(tool, 'run_idempotent', None)
        if runner is not None:
            return runner(idempotency_key=idempotency_key, **arguments)
        return self.execute_strict(tool_name, arguments)
