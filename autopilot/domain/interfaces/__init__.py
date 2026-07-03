"""Domain interface contracts."""

from autopilot.domain.interfaces.agent_interface import AgentInterface
from autopilot.domain.interfaces.config_loader import ConfigLoaderInterface
from autopilot.domain.interfaces.serializer import SerializerInterface
from autopilot.domain.interfaces.tool_interface import ToolInterface, ToolResult

__all__ = [
    "AgentInterface",
    "ConfigLoaderInterface",
    "SerializerInterface",
    "ToolInterface",
    "ToolResult",
]
