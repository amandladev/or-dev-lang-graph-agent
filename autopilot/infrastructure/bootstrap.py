"""Dependency injection bootstrap module.

Wires all application dependencies using constructor injection and returns
a configured Application object ready for CLI consumption.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from autopilot.application.conflicts import ConflictDetector
from autopilot.application.knowledge.experience_builder import ExperienceBuilder
from autopilot.application.orchestrator.engine import OrchestrationEngine
from autopilot.application.orchestrator.graph_builder import GraphBuilder
from autopilot.application.orchestrator.retry_policy import RetryPolicy
from autopilot.application.registries.agent_registry import AgentRegistry
from autopilot.application.registries.tool_registry import ToolRegistry
from autopilot.application.use_cases.config_command import ConfigCommand
from autopilot.application.use_cases.resume_command import ResumeCommand
from autopilot.application.use_cases.work_command import WorkCommand
from autopilot.domain.entities.config import Config
from autopilot.domain.entities.run_record import RunRecord
from autopilot.infrastructure.adapters.console_approval_gate import ConsoleApprovalGate
from autopilot.infrastructure.adapters.json_serializer import JSONSerializer
from autopilot.infrastructure.adapters.structured_logger import StructuredLogger
from autopilot.infrastructure.adapters.workflow_rules import WorkflowRulesProvider
from autopilot.infrastructure.adapters.yaml_config_loader import YAMLConfigLoader
from autopilot.infrastructure.agents.code_executor import CodeExecutorAgent
from autopilot.infrastructure.agents.context_builder import ContextBuilderAgent
from autopilot.infrastructure.agents.documentation import DocumentationAgent
from autopilot.infrastructure.agents.planner import PlannerAgent
from autopilot.infrastructure.agents.publisher import PublisherAgent
from autopilot.infrastructure.agents.reviewer import ReviewerAgent
from autopilot.infrastructure.agents.tester import TesterAgent
from autopilot.infrastructure.knowledge.json_knowledge_engine import JsonKnowledgeEngine
from autopilot.infrastructure.persistence.ledger import Ledger
from autopilot.infrastructure.persistence.ledger_committer import LedgerCommitter
from autopilot.infrastructure.persistence.git_worktree_manager import GitWorktreeManager
from autopilot.infrastructure.persistence.run_record_store import RunRecordStore
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
    knowledge_engine: JsonKnowledgeEngine
    experience_builder: ExperienceBuilder
    run_record_store: RunRecordStore
    ledger: Ledger
    ledger_committer: LedgerCommitter
    workspace_manager: GitWorktreeManager
    conflict_detector: ConflictDetector

    def run(self, ticket_id: str, mode: str = "live", approve: bool = False) -> RunRecord:
        """Run one ticket through the isolated workflow."""
        return self.work_command.execute(ticket_id, mode=mode, approve=approve)

    def run_many(
        self,
        ticket_ids: list[str],
        mode: str = "live",
        approve: bool = False,
        max_workers: int | None = None,
    ) -> dict[str, RunRecord]:
        """Run multiple tickets concurrently."""
        return self.work_command.execute_many(
            ticket_ids, mode=mode, approve=approve, max_workers=max_workers
        )

    def analyze_plans(self, plans: dict[str, dict[str, Any]]) -> dict[str, Any]:
        """Analyze planned file/module overlap before scheduling tickets."""
        return self.conflict_detector.analyze(plans)


def create_application(config_path: str = "auto") -> Application:
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
    config_loader = YAMLConfigLoader()
    config = config_loader.load(config_path)

    jira_tool = JiraTool()
    git_tool = GitTool()
    github_tool = GitHubTool()
    obsidian_tool = ObsidianTool(vault_path=config.vault_location)
    playwright_tool = PlaywrightTool()
    opencode_tool = OpenCodeTool(
        model=config.llm_model if "/" in config.llm_model else "",
        timeout=config.timeout_seconds,
        stream_output=config.verbosity == "verbose",
    )
    filesystem_tool = FilesystemTool()

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

    knowledge_dir = os.path.join(config.workspace_location, "knowledge")
    knowledge_engine = JsonKnowledgeEngine(storage_dir=knowledge_dir)
    experience_builder = ExperienceBuilder()

    # 4.1. Create infrastructure services used by agents
    logger = StructuredLogger(
        verbosity=config.verbosity,
        log_dir=config.workspace_location,
    )

    rules_provider = WorkflowRulesProvider(tool_registry)
    planner = PlannerAgent(tool_registry=tool_registry, knowledge_engine=knowledge_engine)
    context_builder = ContextBuilderAgent(tool_registry=tool_registry)
    code_executor = CodeExecutorAgent(tool_registry=tool_registry, logger=logger)
    # ReviewerAgent is registered for forward-compatibility with the future
    # review workflow (see ReviewCommand / `autopilot review`), but it is a
    # stub (execute() raises NotImplementedError) and has no node in any
    # graph built by GraphBuilder yet — see build_review_graph().
    reviewer = ReviewerAgent(tool_registry=tool_registry)
    tester = TesterAgent(tool_registry=tool_registry)
    publisher = PublisherAgent(tool_registry=tool_registry, rules_provider=rules_provider)
    documentation = DocumentationAgent(tool_registry=tool_registry)

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

    serializer = JSONSerializer(storage_path=config.workspace_location)
    retry_policy = RetryPolicy(
        max_retries=config.max_retries,
        base_delay=config.base_delay,
        backoff_multiplier=config.backoff_multiplier,
    )
    approval_gate = ConsoleApprovalGate(config=config)

    # 6.1. Create persistence services
    run_record_store = RunRecordStore(workspace=config.workspace_location)
    ledger = Ledger(ledger_path=os.path.join(config.workspace_location, "ledger.json"))
    ledger_committer = LedgerCommitter(workspace=config.workspace_location)
    worktree_root = config.worktree_root or str(
        Path(config.workspace_location).expanduser().resolve().parent / ".autopilot-worktrees"
    )
    workspace_manager = GitWorktreeManager(
        repository=config.workspace_location,
        worktree_root=worktree_root,
        rules_provider=rules_provider.load,
        logger=logger,
    )

    engine = OrchestrationEngine(
        agent_registry=agent_registry,
        serializer=serializer,
        logger=logger,
        retry_policy=retry_policy,
        config=config,
        run_record_store=run_record_store,
    )

    graph_builder = GraphBuilder(engine=engine, approval_gate=approval_gate)

    work_command = WorkCommand(
        engine=engine,
        graph_builder=graph_builder,
        config=config,
        serializer=serializer,
        approval_gate=approval_gate,
        workspace_manager=workspace_manager,
        ticket_loader=context_builder.fetch_ticket,
    )
    resume_command = ResumeCommand(
        engine=engine,
        graph_builder=graph_builder,
        serializer=serializer,
        config=config,
        workspace_manager=workspace_manager,
    )
    config_command = ConfigCommand(config=config)

    return Application(
        engine=engine,
        config=config,
        work_command=work_command,
        resume_command=resume_command,
        config_command=config_command,
        knowledge_engine=knowledge_engine,
        experience_builder=experience_builder,
        run_record_store=run_record_store,
        ledger=ledger,
        ledger_committer=ledger_committer,
        workspace_manager=workspace_manager,
        conflict_detector=ConflictDetector(),
    )
