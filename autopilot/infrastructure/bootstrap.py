"""Dependency injection bootstrap module.

Wires all application dependencies using constructor injection and returns
a configured Application object ready for CLI consumption.
"""

from dataclasses import dataclass

from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.graph_builder import GraphBuilder
from autopilot.application.orchestrator.retry_policy import RetryPolicy
from autopilot.application.registries.agent_registry import AgentRegistry
from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.application.use_cases.config_command import ConfigCommand
from autopilot.application.use_cases.resume_command import ResumeCommand
from autopilot.application.use_cases.work_command import WorkCommand
from autopilot.domain.entities.config import Config
from autopilot.infrastructure.adapters.json_serializer import JSONSerializer
from autopilot.infrastructure.adapters.structured_logger import StructuredLogger
from autopilot.infrastructure.adapters.yaml_config_loader import YAMLConfigLoader
from autopilot.infrastructure.agents.code_executor import CodeExecutorAgent
from autopilot.infrastructure.agents.context_builder import ContextBuilderAgent
from autopilot.infrastructure.agents.documentation import DocumentationAgent
from autopilot.infrastructure.agents.planner import PlannerAgent
from autopilot.infrastructure.agents.publisher import PublisherAgent
from autopilot.infrastructure.agents.reviewer import ReviewerAgent
from autopilot.infrastructure.agents.tester import TesterAgent
from autopilot.infrastructure.tools.filesystem_tool import FilesystemTool
from autopilot.infrastructure.tools.git_tool import GitTool
from autopilot.infrastructure.tools.github_tool import GitHubTool
from autopilot.infrastructure.tools.jira_tool import JiraTool
from autopilot.infrastructure.tools.obsidian_tool import ObsidianTool
from autopilot.infrastructure.tools.opencode_tool import OpenCodeTool
from autopilot.infrastructure.tools.playwright_tool import PlaywrightTool


@dataclass
class Application:
    """Container for all wired application components.

    Holds references to the orchestration engine, configuration, and
    use case instances ready for CLI consumption.
    """

    engine: OrchestrationEngine
    config: Config
    work_command: WorkCommand
    resume_command: ResumeCommand
    config_command: ConfigCommand


def create_application(config_path: str = "config.yaml") -> Application:
    """Wire all dependencies and return a configured Application.

    Follows the DI wiring pattern:
    1. Load config via YAMLConfigLoader
    2. Create all tool instances
    3. Register tools in ToolRegistry
    4. Create all agent instances with tool_registry injected
    5. Register agents in AgentRegistry
    6. Create StructuredLogger, JSONSerializer, RetryPolicy
    7. Create OrchestrationEngine with all deps
    8. Create GraphBuilder with engine
    9. Create use cases (WorkCommand, ResumeCommand, ConfigCommand)
    10. Return Application with all components

    Args:
        config_path: Path to the YAML configuration file. Defaults to "config.yaml".

    Returns:
        A fully configured Application instance ready for CLI consumption.
    """
    # 1. Load config
    config_loader = YAMLConfigLoader()
    config = config_loader.load(config_path)

    # 2. Create tools
    jira_tool = JiraTool()
    git_tool = GitTool()
    github_tool = GitHubTool()
    obsidian_tool = ObsidianTool()
    playwright_tool = PlaywrightTool()
    opencode_tool = OpenCodeTool()
    filesystem_tool = FilesystemTool()

    # 3. Register tools
    tool_registry = ToolRegistry()
    for tool in [
        jira_tool,
        git_tool,
        github_tool,
        obsidian_tool,
        playwright_tool,
        opencode_tool,
        filesystem_tool,
    ]:
        tool_registry.register(tool)

    # 4. Create agents (inject tools via constructor)
    planner = PlannerAgent(tool_registry=tool_registry)
    context_builder = ContextBuilderAgent(tool_registry=tool_registry)
    code_executor = CodeExecutorAgent(tool_registry=tool_registry)
    reviewer = ReviewerAgent(tool_registry=tool_registry)
    tester = TesterAgent(tool_registry=tool_registry)
    publisher = PublisherAgent(tool_registry=tool_registry)
    documentation = DocumentationAgent(tool_registry=tool_registry)

    # 5. Register agents
    agent_registry = AgentRegistry()
    for agent in [
        planner,
        context_builder,
        code_executor,
        reviewer,
        tester,
        publisher,
        documentation,
    ]:
        agent_registry.register(agent)

    # 6. Create infrastructure services
    logger = StructuredLogger(
        verbosity=config.verbosity,
        log_dir=config.workspace_location,
    )
    serializer = JSONSerializer(storage_path=config.workspace_location)
    retry_policy = RetryPolicy(
        max_retries=config.max_retries,
        base_delay=config.base_delay,
        backoff_multiplier=config.backoff_multiplier,
    )

    # 7. Create orchestration engine
    engine = OrchestrationEngine(
        agent_registry=agent_registry,
        serializer=serializer,
        logger=logger,
        retry_policy=retry_policy,
        config=config,
    )

    # 8. Create graph builder
    graph_builder = GraphBuilder(engine=engine)

    # 9. Create use cases
    work_command = WorkCommand(
        engine=engine,
        graph_builder=graph_builder,
        config=config,
        serializer=serializer,
    )
    resume_command = ResumeCommand(
        engine=engine,
        graph_builder=graph_builder,
        serializer=serializer,
        config=config,
    )
    config_command = ConfigCommand(config=config)

    # 10. Return configured application
    return Application(
        engine=engine,
        config=config,
        work_command=work_command,
        resume_command=resume_command,
        config_command=config_command,
    )
