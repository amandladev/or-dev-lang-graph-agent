"""LangGraph orchestration engine and state schema."""

import re
import time
from typing import Annotated, Any, TypedDict

from autopilot.application.orchestrator.retry_policy import RetryPolicy
from autopilot.domain.entities.run_record import RunRecord
from autopilot.domain.value_objects.error_record import ErrorRecord, ErrorType


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
    workspace: Annotated[dict, overwrite]
    pending_question: Annotated[dict | None, overwrite]


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
        run_record_store: Any | None = None,
    ) -> None:
        """Initialize the orchestration engine.

        Args:
            agent_registry: Registry providing agent lookup by name.
            serializer: Serializer for persisting workflow state.
            logger: Structured logger for execution observability.
            retry_policy: Policy for classifying errors and determining retries.
            config: Application configuration.
            run_record_store: Optional store for persisting run records.
        """
        self._agent_registry = agent_registry
        self._serializer = serializer
        self._logger = logger
        self._retry_policy = retry_policy
        self._config = config
        self._run_record_store = run_record_store

    def create_run_record(self, ticket_id: str, ticket_title: str = "", mode: str = "live") -> RunRecord:
        """Create a new RunRecord for tracking this execution.

        Args:
            ticket_id: The Jira ticket ID being processed.
            ticket_title: Title of the Jira ticket.
            mode: Execution mode ("live", "dry-run", "resume").

        Returns:
            The newly created RunRecord.
        """
        record = RunRecord(
            ticket_id=ticket_id,
            ticket_title=ticket_title,
            mode=mode,
        )
        if self._run_record_store:
            self._run_record_store.save(record)
        return record

    def update_run_record(self, record: RunRecord) -> None:
        """Save the current state of a RunRecord.

        Args:
            record: The RunRecord to save.
        """
        if self._run_record_store:
            self._run_record_store.save(record)

    @property
    def max_retries(self) -> int:
        """Return the configured retry budget."""
        return self._retry_policy.max_retries

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

            input_data = {k: state.get(k) for k in agent.input_schema}

            memory_context = state.get("metadata")
            self._log_agent_event(agent_name, input_data, "agent.start", "running")

            start_details = self._get_agent_start_details(agent_name, input_data)
            self._logger.log_agent_start(agent_name, start_details["action"], start_details.get("details"))

            start_time = time.time()
            last_exception: Exception | None = None

            for attempt in range(self._retry_policy.max_retries + 1):
                try:
                    output = agent.execute(input_data, memory_context=memory_context)

                    elapsed_ms = int((time.time() - start_time) * 1000)
                    summary = self._get_agent_summary(agent_name, output)
                    self._logger.log_agent_completion(
                        agent_name=agent_name,
                        elapsed_ms=elapsed_ms,
                        status="success",
                        input_data=input_data,
                        output_data=output,
                        summary=summary,
                    )
                    self._log_agent_event(agent_name, input_data, "agent.execute", "success")

                    if agent_name == "Planner":
                        self._logger.log_plan_steps(output.get("plan"))

                    self._persist_state(state, output)

                    return output

                except Exception as exc:
                    last_exception = exc
                    error_type = self._retry_policy.classify(exc)

                    if error_type == ErrorType.NEEDS_CLARIFICATION:
                        # The agent isn't broken, it's asking a question.
                        # Pause immediately (no retry — the question won't
                        # answer itself) and persist it distinctly from a
                        # failure so `autopilot resume --answer` can find it.
                        question = getattr(exc, "question", str(exc))
                        elapsed_ms = int((time.time() - start_time) * 1000)
                        self._logger.log_agent_completion(
                            agent_name=agent_name,
                            elapsed_ms=elapsed_ms,
                            status="blocked",
                            summary=f"Needs clarification: {question[:100]}",
                        )
                        self._log_agent_event(agent_name, input_data, "agent.execute", "blocked")
                        error_record = ErrorRecord(
                            error_type=ErrorType.NEEDS_CLARIFICATION,
                            description=question,
                            agent_name=agent_name,
                            attempt_count=attempt + 1,
                            exception_class=type(exc).__name__,
                        )
                        pending_question = {
                            "agent_name": agent_name,
                            "question": question,
                            "asked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        }
                        self._persist_error_state(
                            state, error_record, extra={"pending_question": pending_question}
                        )
                        raise

                    if error_type == ErrorType.NON_RETRYABLE:
                        # Non-retryable: immediate pause, no retry.
                        # Distinguish a deliberately configured business
                        # error (auth/config/schema) from an unrecognized
                        # exception type that fell back to NON_RETRYABLE by
                        # default — the latter is more likely a genuine
                        # agent bug and deserves operator attention.
                        recognized = self._retry_policy.is_recognized(exc)
                        description = str(exc)
                        if not recognized:
                            description = f"[unclassified exception] {description}"

                        elapsed_ms = int((time.time() - start_time) * 1000)
                        self._logger.log_agent_completion(
                            agent_name=agent_name,
                            elapsed_ms=elapsed_ms,
                            status="failed",
                            summary=f"Error: {str(exc)[:100]}",
                        )
                        self._log_agent_event(agent_name, input_data, "agent.execute", "failed")
                        error_record = ErrorRecord(
                            error_type=ErrorType.NON_RETRYABLE,
                            description=description,
                            agent_name=agent_name,
                            attempt_count=attempt + 1,
                            exception_class=type(exc).__name__,
                        )
                        self._persist_error_state(state, error_record)
                        raise

                    if attempt < self._retry_policy.max_retries:
                        self._logger.log_retry(
                            agent_name=agent_name,
                            attempt=attempt + 1,
                            max_attempts=self._retry_policy.max_retries,
                            error=str(exc),
                        )
                        delay = self._retry_policy.get_delay(attempt)
                        time.sleep(delay)

            elapsed_ms = int((time.time() - start_time) * 1000)
            self._logger.log_agent_completion(
                agent_name=agent_name,
                elapsed_ms=elapsed_ms,
                status="failed",
            )
            self._log_agent_event(agent_name, input_data, "agent.execute", "failed")
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

    _PYTEST_SUMMARY_RE = re.compile(
        r"={1,}\s*(?:.*\s)?(?P<passed>\d+) passed"
        r"(?:.*?(?P<failed>\d+) failed)?"
        r"(?:.*?(?P<errors>\d+) error)?",
    )

    @classmethod
    def _parse_test_counts(cls, final_test: dict | None) -> tuple[int, int]:
        """Extract real test case counts from the pytest summary line.

        Falls back to (0, 0) when the framework output has no parsable
        summary, so the caller can apply its suite-level default.

        Args:
            final_test: The last "test_result" evidence entry, if any.

        Returns:
            Tuple of (tests_executed, tests_passed) per test case.
        """
        if not final_test:
            return 0, 0
        output = final_test.get("data", {}).get("output", "")
        if not isinstance(output, str) or not output:
            return 0, 0
        match = cls._PYTEST_SUMMARY_RE.search(output)
        if not match:
            return 0, 0
        passed = int(match.group("passed"))
        failed = int(match.group("failed") or 0) + int(match.group("errors") or 0)
        return passed + failed, passed

    def _log_agent_event(
        self, agent_name: str, input_data: dict[str, Any], operation: str, status: str
    ) -> None:
        """Forward concurrent-run identity to loggers that support events."""
        method = getattr(self._logger, "log_agent_event", None)
        workspace = input_data.get("workspace", {})
        if method is None or not isinstance(workspace, dict):
            return
        ticket = input_data.get("ticket", {})
        method(
            ticket_id=ticket.get("id", "") if isinstance(ticket, dict) else "",
            agent_id=agent_name,
            workspace_path=workspace.get("path", ""),
            branch=workspace.get("branch", ""),
            operation=operation,
            status=status,
        )

    def execute(self, graph: Any, initial_state: dict, run_record: RunRecord | None = None) -> dict:
        """Execute a compiled LangGraph graph.

        Args:
            graph: A compiled LangGraph StateGraph ready for invocation.
            initial_state: The initial state dictionary to pass to the graph.
            run_record: Optional RunRecord to update during execution.

        Returns:
            The final state dictionary after graph execution completes.
        """
        try:
            result = graph.invoke(initial_state)

            if run_record:
                test_results = [e for e in result.get("evidence", [])
                               if e.get("type") == "test_result"]
                final_test = test_results[-1] if test_results else None
                final_test_status = ""
                if final_test:
                    final_test_status = final_test.get("data", {}).get("status", "").lower()
                    if not final_test_status:
                        legacy_result = final_test.get("result", "").upper()
                        if legacy_result.startswith("PASS"):
                            final_test_status = "passed"
                        elif legacy_result.startswith("FAIL"):
                            final_test_status = "failed"
                tests_executed, tests_passed = self._parse_test_counts(final_test)
                if tests_executed == 0 and final_test:
                    tests_executed = 1
                    tests_passed = 1 if final_test_status == "passed" else 0

                run_record.update_test_counts(
                    executed=tests_executed,
                    passed=tests_passed,
                    failed=tests_executed - tests_passed,
                )
                run_record.modified_files = result.get("modified_files", [])
                run_record.workspace = result.get("workspace", run_record.workspace)

                errors = result.get("errors", [])
                if errors:
                    run_record.mark_failed(f"Workflow failed with {len(errors)} error(s)")
                elif final_test_status == "passed":
                    run_record.mark_completed("PASS")
                elif final_test:
                    run_record.mark_completed("FAIL")
                else:
                    run_record.mark_completed("FAIL")

                if self._run_record_store:
                    self._run_record_store.save(run_record)

            return result

        except Exception as exc:
            if run_record:
                from autopilot.domain.value_objects.exceptions import (
                    ApprovalRejectedError,
                    NeedsClarificationError,
                )

                if isinstance(exc, NeedsClarificationError):
                    run_record.mark_blocked(exc.question)
                elif isinstance(exc, ApprovalRejectedError):
                    run_record.mark_cancelled()
                else:
                    run_record.mark_failed(str(exc))
                if self._run_record_store:
                    self._run_record_store.save(run_record)
            raise

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

    def _persist_error_state(
        self, current_state: dict, error_record: ErrorRecord, extra: dict[str, Any] | None = None
    ) -> None:
        """Persist the last-good state with the error recorded.

        Appends the error to the state's errors list and persists. The failed
        agent's partial output is discarded (only current_state is used).

        Args:
            current_state: The state as it existed before the failed agent ran.
            error_record: The error record to append.
            extra: Optional additional fields to overlay onto the persisted
                state (e.g. "pending_question" for a clarification pause).
        """
        import dataclasses

        errors = list(current_state.get("errors", []))
        errors.append(dataclasses.asdict(error_record))
        state_with_error = {**current_state, "errors": errors, **(extra or {})}
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
                workspace=state.get("workspace", {}),
                pending_question=state.get("pending_question"),
            )
            workspace = state.get("workspace", {})
            storage_path = workspace.get("path") if isinstance(workspace, dict) else None
            storage_path = storage_path or getattr(self._config, "workspace_location", ".")
            filepath = f"{storage_path}/.autopilot_state.json"
            self._serializer.persist(workflow_state, filepath)
        except Exception as exc:
            # State persistence failure should not crash the workflow,
            # but it must not be invisible either.
            self._logger.log_warning(
                f"Failed to persist workflow state: {exc}"
            )

    def _get_agent_start_details(self, agent_name: str, input_data: dict) -> dict:
        """Generate meaningful start details based on agent type.

        Args:
            agent_name: The name of the agent.
            input_data: The input data for the agent.

        Returns:
            Dict with 'action' and optional 'details'.
        """
        ticket_id = input_data.get("ticket", {}).get("id", "") if isinstance(input_data.get("ticket"), dict) else ""

        if agent_name == "context_builder":
            return {"action": f"fetching ticket {ticket_id} and vault context"}
        elif agent_name == "planner":
            return {"action": f"generating implementation plan for {ticket_id}"}
        elif agent_name == "code_executor":
            plan = input_data.get("plan", {})
            steps = plan.get("steps", []) if isinstance(plan, dict) else []
            return {"action": f"executing {len(steps)} plan steps"}
        elif agent_name == "tester":
            files = input_data.get("modified_files", [])
            return {"action": f"testing {len(files)} modified files"}
        elif agent_name == "publisher":
            files = input_data.get("modified_files", [])
            return {"action": f"publishing {len(files)} files to git"}
        elif agent_name == "documentation":
            return {"action": "generating workflow documentation"}
        else:
            return {"action": "executing"}

    def _get_agent_summary(self, agent_name: str, output: dict) -> str:
        """Generate a meaningful summary based on agent output.

        Args:
            agent_name: The name of the agent.
            output: The output from the agent.

        Returns:
            Summary string.
        """
        if agent_name == "context_builder":
            ticket = output.get("ticket", {})
            title = ticket.get("title", "") if isinstance(ticket, dict) else ""
            return f"Ticket: {title[:50]}" if title else "Context loaded"
        elif agent_name == "planner":
            plan = output.get("plan", {})
            steps = plan.get("steps", []) if isinstance(plan, dict) else []
            return f"Plan with {len(steps)} steps"
        elif agent_name == "code_executor":
            files = output.get("modified_files", [])
            if not files:
                return "No files modified"
            names = ", ".join(f.split("/")[-1] for f in files[:3])
            return f"Modified {len(files)} files: {names}"
        elif agent_name == "tester":
            evidence = output.get("evidence", [])
            tests = [e for e in evidence if e.get("type") == "test_result"]
            passed = sum(
                1 for t in tests
                if "pass" in str(t.get("result", "")).lower()
                or t.get("data", {}).get("status", "").lower() == "passed"
            )
            return f"{passed}/{len(tests)} tests passed" if tests else "No tests found"
        elif agent_name == "publisher":
            files = output.get("modified_files", [])
            return f"Committed {len(files)} files"
        elif agent_name == "documentation":
            return "Documentation generated"
        else:
            return "Completed"
