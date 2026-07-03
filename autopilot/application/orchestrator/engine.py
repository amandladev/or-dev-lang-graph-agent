"""LangGraph orchestration engine and state schema."""

import time
from typing import Any, Annotated, TypedDict

from autopilot.domain.value_objects.error_record import ErrorRecord, ErrorType
from autopilot.application.orchestrator.retry_policy import RetryPolicy


def append_list(existing: list, new: list) -> list:
    """Reducer: append new items to existing list."""
    return existing + new


def overwrite(existing: Any, new: Any) -> Any:
    """Reducer: replace existing value with new value."""
    return new


class GraphState(TypedDict, total=False):
    """LangGraph state schema with reducers for merge strategy."""

    ticket: Annotated[dict, overwrite]
    context: Annotated[dict, overwrite]
    modified_files: Annotated[list[str], append_list]
    plan: Annotated[dict, overwrite]
    logs: Annotated[list[dict], append_list]
    evidence: Annotated[list[dict], append_list]
    errors: Annotated[list[dict], append_list]
    metrics: Annotated[dict, overwrite]
    metadata: Annotated[dict, overwrite]


class OrchestrationEngine:
    """Builds and executes LangGraph workflows.

    The engine creates node wrapper functions for each agent that handle
    input extraction, execution, retry logic, state persistence, and logging.
    """

    def __init__(
        self,
        agent_registry: Any,
        serializer: Any,
        logger: Any,
        retry_policy: RetryPolicy,
        config: Any,
    ) -> None:
        """Initialize the orchestration engine.

        Args:
            agent_registry: Registry providing agent lookup by name.
            serializer: Serializer for persisting workflow state.
            logger: Structured logger for execution observability.
            retry_policy: Policy for classifying errors and determining retries.
            config: Application configuration.
        """
        self._agent_registry = agent_registry
        self._serializer = serializer
        self._logger = logger
        self._retry_policy = retry_policy
        self._config = config

    def create_agent_node(self, agent_name: str):
        """Create a LangGraph node function for the named agent.

        Returns a callable that:
        1. Extracts only the fields declared in the agent's input_schema from state
        2. Calls agent.execute() with the extracted input and optional memory context
        3. On success: logs completion, persists state, returns output dict
        4. On exception: classifies via retry_policy, retries if retryable up to max_retries
        5. If all retries exhausted or non-retryable: records error, persists last-good state, raises

        Args:
            agent_name: The registered name of the agent to wrap.

        Returns:
            A callable node function compatible with LangGraph state graphs.
        """

        def node(state: dict) -> dict:
            agent = self._agent_registry.get(agent_name)

            # Extract only the fields declared in the agent's input_schema
            input_data = {k: state.get(k) for k in agent.input_schema}

            # Retrieve optional memory context from state metadata
            memory_context = state.get("metadata")

            # Log agent start
            self._logger.log_agent_start(agent_name, "executing")

            start_time = time.time()
            last_exception: Exception | None = None

            # Try execution with retry logic
            for attempt in range(self._retry_policy.max_retries + 1):
                try:
                    output = agent.execute(input_data, memory_context=memory_context)

                    # Success: log completion
                    elapsed_ms = int((time.time() - start_time) * 1000)
                    self._logger.log_agent_completion(
                        agent_name=agent_name,
                        elapsed_ms=elapsed_ms,
                        status="success",
                        input_data=input_data,
                        output_data=output,
                    )

                    # Persist state after successful node completion
                    self._persist_state(state, output)

                    return output

                except Exception as exc:
                    last_exception = exc
                    error_type = self._retry_policy.classify(exc)

                    if error_type == ErrorType.NON_RETRYABLE:
                        # Non-retryable: immediate pause, no retry
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        self._logger.log_agent_completion(
                            agent_name=agent_name,
                            elapsed_ms=elapsed_ms,
                            status="failed",
                        )
                        error_record = ErrorRecord(
                            error_type=ErrorType.NON_RETRYABLE,
                            description=str(exc),
                            agent_name=agent_name,
                            attempt_count=attempt + 1,
                            exception_class=type(exc).__name__,
                        )
                        self._persist_error_state(state, error_record)
                        raise

                    # Retryable: check if we have retries remaining
                    if attempt < self._retry_policy.max_retries:
                        self._logger.log_retry(
                            agent_name=agent_name,
                            attempt=attempt + 1,
                            max_attempts=self._retry_policy.max_retries,
                            error=str(exc),
                        )
                        # Wait with exponential backoff before next attempt
                        delay = self._retry_policy.get_delay(attempt)
                        time.sleep(delay)
                    # else: will fall through to exhaustion handling below

            # All retries exhausted
            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.log_agent_completion(
                agent_name=agent_name,
                elapsed_ms=elapsed_ms,
                status="failed",
            )
            error_record = ErrorRecord(
                error_type=ErrorType.RETRYABLE,
                description=str(last_exception),
                agent_name=agent_name,
                attempt_count=self._retry_policy.max_retries + 1,
                exception_class=type(last_exception).__name__,
            )
            self._persist_error_state(state, error_record)
            raise last_exception  # type: ignore[misc]

        return node

    def execute(self, graph: Any, initial_state: dict) -> dict:
        """Execute a compiled LangGraph graph.

        Args:
            graph: A compiled LangGraph StateGraph ready for invocation.
            initial_state: The initial state dictionary to pass to the graph.

        Returns:
            The final state dictionary after graph execution completes.
        """
        return graph.invoke(initial_state)

    def _persist_state(self, current_state: dict, agent_output: dict) -> None:
        """Persist the merged state after a successful node completion.

        Merges agent output into current state using append semantics for
        list fields and overwrite for scalar fields, then serializes to disk.

        Args:
            current_state: The current graph state before merge.
            agent_output: The output dictionary from the agent.
        """
        merged = self._merge_state(current_state, agent_output)
        self._serialize_state(merged)

    def _persist_error_state(self, current_state: dict, error_record: ErrorRecord) -> None:
        """Persist the last-good state with the error recorded.

        Appends the error to the state's errors list and persists. The failed
        agent's partial output is discarded (only current_state is used).

        Args:
            current_state: The state as it existed before the failed agent ran.
            error_record: The error record to append.
        """
        import dataclasses

        errors = list(current_state.get("errors", []))
        errors.append(dataclasses.asdict(error_record))
        state_with_error = {**current_state, "errors": errors}
        self._serialize_state(state_with_error)

    def _merge_state(self, current_state: dict, agent_output: dict) -> dict:
        """Merge agent output into the current state.

        List fields (modified_files, logs, evidence, errors) use append semantics.
        Scalar/object fields (ticket, context, plan, metrics, metadata) use overwrite.

        Args:
            current_state: The existing graph state.
            agent_output: The new output from the agent.

        Returns:
            The merged state dictionary.
        """
        list_fields = {"modified_files", "logs", "evidence", "errors"}
        merged = dict(current_state)

        for key, value in agent_output.items():
            if key in list_fields and isinstance(value, list):
                existing = merged.get(key, [])
                merged[key] = existing + value
            else:
                merged[key] = value

        return merged

    def _serialize_state(self, state: dict) -> None:
        """Serialize and persist the state dictionary to disk.

        Uses the configured serializer. If the serializer supports dict-based
        persistence, uses it directly. Otherwise converts to the expected format.

        Args:
            state: The state dictionary to persist.
        """
        try:
            from autopilot.domain.entities.workflow_state import WorkflowState

            workflow_state = WorkflowState(
                ticket=state.get("ticket", {}),
                context=state.get("context", {}),
                modified_files=state.get("modified_files", []),
                plan=state.get("plan", {}),
                logs=state.get("logs", []),
                evidence=state.get("evidence", []),
                errors=state.get("errors", []),
                metrics=state.get("metrics", {}),
                metadata=state.get("metadata", {}),
            )
            storage_path = getattr(self._config, "workspace_location", ".")
            filepath = f"{storage_path}/.autopilot_state.json"
            self._serializer.persist(workflow_state, filepath)
        except Exception:
            # State persistence failure should not crash the workflow
            # The logger would record this, but we continue execution
            pass
