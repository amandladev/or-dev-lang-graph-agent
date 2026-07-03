"""Agent registry for discovery and retrieval of registered agents."""

from autopilot.domain.interfaces.agent_interface import AgentInterface


class AgentRegistry:
    """Registry for agent discovery and retrieval."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentInterface] = {}

    def register(self, agent: AgentInterface) -> None:
        """
        Register an agent by its name.

        Raises:
            ValueError: If an agent with the same name is already registered.
        """
        if agent.name in self._agents:
            raise ValueError(f"Agent already registered: {agent.name}")
        self._agents[agent.name] = agent

    def get(self, name: str) -> AgentInterface:
        """
        Retrieve an agent by name.

        Raises:
            KeyError: If no agent with the given name is registered.
        """
        if name not in self._agents:
            raise KeyError(f"Agent not registered: {name}")
        return self._agents[name]

    def list_agents(self) -> list[str]:
        """Return all registered agent names."""
        return list(self._agents.keys())
