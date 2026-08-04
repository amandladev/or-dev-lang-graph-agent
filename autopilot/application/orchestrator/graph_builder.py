"""Graph builder for constructing LangGraph workflow graphs."""

from langgraph.graph import END, START, StateGraph

from autopilot.application.orchestrator.engine import GraphState

# Ordered list of nodes in the work workflow graph.
WORK_GRAPH_NODES = [
    "context_builder",
    "planner",
    "code_executor",
    "tester",
    "publisher",
    "documentation",
]

# Mapping from node names to agent registry names.
NODE_AGENT_MAP = {
    "context_builder": "Context_Builder",
    "planner": "Planner",
    "code_executor": "Code_Executor",
    "tester": "Tester",
    "publisher": "Publisher",
    "documentation": "Documentation_Agent",
}


class GraphBuilder:
    """Builds LangGraph workflow graphs for different execution modes."""

    def __init__(self, engine) -> None:
        """Initialize GraphBuilder with an OrchestrationEngine reference.

        Args:
            engine: The OrchestrationEngine instance used to create agent node functions.
        """
        self._engine = engine

    def build_work_graph(self):
        """Build the work workflow graph.

        The work graph defines the standard execution flow:
        Context_Builder → Planner → Code_Executor → Tester → Publisher → Documentation_Agent

        After the Tester node, a conditional edge routes to:
        - "publisher" if tests pass (no errors)
        - "code_executor" if the last error is retryable (retry loop)
        - END if the error is non-retryable or retries exhausted (pause)

        Returns:
            A compiled LangGraph StateGraph ready for execution.
        """
        graph = StateGraph(GraphState)

        # Add all nodes
        for node_name, agent_name in NODE_AGENT_MAP.items():
            graph.add_node(node_name, self._engine.create_agent_node(agent_name))

        # Add linear edges
        graph.add_edge(START, "context_builder")
        graph.add_edge("context_builder", "planner")
        graph.add_edge("planner", "code_executor")
        graph.add_edge("code_executor", "tester")

        # Conditional edge after tester: route based on test results
        graph.add_conditional_edges(
            "tester",
            self._route_after_test,
            {"pass": "publisher", "retry": "code_executor", "pause": END},
        )

        graph.add_edge("publisher", "documentation")
        graph.add_edge("documentation", END)

        return graph.compile()

    def build_review_graph(self):
        """Build the review workflow graph.

        Not implemented yet: there is no "review" node in NODE_AGENT_MAP,
        and ReviewerAgent.execute() is itself a stub. `autopilot review`
        (ReviewCommand) surfaces this as a clear NotImplementedError rather
        than silently no-op'ing.

        Raises:
            NotImplementedError: Review graph is not implemented in the MVP.
        """
        raise NotImplementedError("Review graph not implemented in MVP")

    def build_resume_graph(self, resume_from: str):
        """Build a graph that starts execution from a specific node.

        This is used for resuming paused or failed workflows. The graph
        is identical to the work graph except START points to the specified
        resume node instead of always starting at context_builder.

        Args:
            resume_from: The node name to resume execution from.
                Must be one of the valid node names in WORK_GRAPH_NODES.

        Returns:
            A compiled LangGraph StateGraph starting from the specified node.

        Raises:
            ValueError: If resume_from is not a valid node name.
        """
        if resume_from not in WORK_GRAPH_NODES:
            raise ValueError(
                f"Invalid resume node: '{resume_from}'. "
                f"Must be one of: {WORK_GRAPH_NODES}"
            )

        graph = StateGraph(GraphState)

        # Add all nodes (same as work graph)
        for node_name, agent_name in NODE_AGENT_MAP.items():
            graph.add_node(node_name, self._engine.create_agent_node(agent_name))

        # START points to the resume node
        graph.add_edge(START, resume_from)

        # Add edges for nodes from resume_from onward
        resume_index = WORK_GRAPH_NODES.index(resume_from)
        remaining_nodes = WORK_GRAPH_NODES[resume_index:]

        for i, node_name in enumerate(remaining_nodes):
            if node_name == "tester":
                # Conditional edge after tester (same as work graph)
                graph.add_conditional_edges(
                    "tester",
                    self._route_after_test,
                    {"pass": "publisher", "retry": "code_executor", "pause": END},
                )
            elif node_name == "documentation":
                graph.add_edge("documentation", END)
            else:
                # Add edge to next node if not the last
                next_index = i + 1
                if next_index < len(remaining_nodes):
                    next_node = remaining_nodes[next_index]
                    graph.add_edge(node_name, next_node)

        return graph.compile()

    def _route_after_test(self, state: dict) -> str:
        """Conditional routing after the tester node.

        Determines the next node based on the errors field in state:
        - No errors: tests passed, proceed to publisher
        - Last error is retryable: retry code_executor
        - Last error is non-retryable or retries exhausted: pause (END)

        Args:
            state: The current graph state dictionary.

        Returns:
            One of "pass", "retry", or "pause" routing keys.
        """
        errors = state.get("errors", [])
        if not errors:
            return "pass"

        # Check the most recent error for retry eligibility
        last_error = errors[-1]
        error_type = last_error.get("error_type", "")

        if error_type == "retryable":
            return "retry"

        return "pause"
