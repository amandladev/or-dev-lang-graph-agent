"""CLI commands for Autopilot using Click."""

import sys
import time

import click


def _print_banner() -> None:
    """Print the autopilot startup banner."""
    click.secho("⚡ Autopilot", fg="cyan", bold=True)
    click.echo()


def _print_validation(result) -> bool:
    """Print validation results and return True if critical errors exist.

    Args:
        result: ValidationResult from validators.

    Returns:
        True if there are errors (should abort), False if OK to continue.
    """
    for warning in result.warnings:
        click.secho(f"  ⚠ {warning}", fg="yellow")

    for error in result.errors:
        click.secho(f"  ✗ {error}", fg="red")

    if result.errors:
        click.echo()
        click.secho("Aborting: fix the errors above before running.", fg="red")
        return True

    if result.warnings:
        click.echo()

    return False


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Autopilot - Local developer workflow orchestration system."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit(1)


@cli.command()
@click.argument("ticket_id")
@click.option("--config-path", default="auto", help="Path to .autopilot.yaml (default: auto-discover)")
@click.option("--skip-validation", is_flag=True, help="Skip environment validation checks")
@click.option("--dry-run", is_flag=True, help="Execute in dry-run mode (no git commits)")
def work(ticket_id: str, config_path: str, skip_validation: bool, dry_run: bool) -> None:
    """Initiate a full workflow execution for the specified ticket.

    TICKET_ID is the identifier of the ticket to work on (e.g., CULQI-123).
    """
    if not ticket_id.strip():
        click.echo("Error: ticket-id must not be empty.", err=True)
        sys.exit(1)

    _print_banner()

    try:
        from autopilot.infrastructure.bootstrap import create_application
        from autopilot.infrastructure.validators import validate_environment
        from autopilot.domain.entities.ledger_entry import LedgerEntry

        click.secho(f"  Ticket: {ticket_id}", fg="white")
        click.secho(f"  Config: {config_path}", fg="white", dim=True)
        if dry_run:
            click.secho("  Mode: dry-run", fg="yellow")
        click.echo()

        # Load application
        app = create_application(config_path)

        # Validate environment
        if not skip_validation:
            click.secho("Validating environment...", fg="white", dim=True)
            validation = validate_environment(app.config, ticket_id)
            if _print_validation(validation):
                sys.exit(1)
            if validation.valid and not validation.warnings:
                click.secho("  ✓ Environment OK", fg="green")
                click.echo()

        # Execute workflow
        click.secho("Starting workflow...", fg="cyan")
        click.echo()
        start_time = time.time()

        mode = "dry-run" if dry_run else "live"
        run_record = app.work_command.execute(ticket_id, mode=mode)

        # Store experience from completed workflow
        try:
            from autopilot.infrastructure.adapters.json_serializer import JSONSerializer
            import os

            state_path = os.path.join(app.config.workspace_location, ".autopilot_state.json")
            if os.path.exists(state_path):
                serializer = JSONSerializer()
                state = serializer.load(state_path)
                state_dict = {
                    "ticket": state.ticket,
                    "plan": state.plan,
                    "context": state.context,
                    "evidence": state.evidence,
                    "modified_files": state.modified_files,
                    "errors": state.errors,
                    "metrics": state.metrics,
                }
                experience = app.experience_builder.build(state_dict)
                exp_id = app.knowledge_engine.store(experience)
                click.secho(f"  💡 Experience stored: {exp_id[:8]}...", fg="blue", dim=True)
        except Exception:
            pass  # Experience storage failure shouldn't break the workflow report

        # Add to ledger
        try:
            ledger_entry = LedgerEntry.from_run_record(run_record)
            app.ledger.append(ledger_entry)

            # Commit ledger to git
            if not dry_run:
                commit_message = f"run {run_record.run_id[:8]} - {ticket_id}"
                app.ledger_committer.commitledger(
                    ledger_path=app.config.workspace_location + "/ledger.json",
                    message=commit_message,
                )
        except Exception:
            pass  # Ledger failure shouldn't break the workflow report

        elapsed = time.time() - start_time
        click.echo()
        click.secho("─" * 50, dim=True)

        # Display results based on status
        if run_record.status == "completed":
            click.secho(f"✓ Workflow completed in {elapsed:.1f}s", fg="green", bold=True)
            click.secho(f"  Run ID: {run_record.run_id[:16]}...", fg="white", dim=True)
            click.secho(f"  Verdict: {run_record.verdict}", fg="white", dim=True)
            click.secho(f"  Tests: {run_record.tests_passed}/{run_record.tests_executed} passed",
                       fg="white", dim=True)
            if run_record.modified_files:
                click.secho(f"  Files modified: {len(run_record.modified_files)}", fg="white", dim=True)
        elif run_record.status == "failed":
            click.secho(f"✗ Workflow failed in {elapsed:.1f}s", fg="red", bold=True)
            click.secho(f"  Run ID: {run_record.run_id[:16]}...", fg="white", dim=True)
            if run_record.errors:
                click.secho(f"  Error: {run_record.errors[-1].get('description', 'Unknown')}",
                           fg="red", dim=True)
        else:
            click.secho(f"Workflow {run_record.status} in {elapsed:.1f}s", fg="yellow", bold=True)
            click.secho(f"  Run ID: {run_record.run_id[:16]}...", fg="white", dim=True)

    except SystemExit:
        raise
    except Exception as exc:
        click.echo()
        click.secho(f"✗ Workflow failed: {exc}", fg="red", err=True)
        sys.exit(1)


@cli.command()
def status() -> None:
    """Display the current workflow state."""
    click.echo("Status: not implemented yet")


@cli.command()
@click.option("--config-path", default="auto", help="Path to .autopilot.yaml (default: auto-discover)")
def resume(config_path: str) -> None:
    """Resume a previously paused or failed workflow from its last successful step."""
    _print_banner()

    try:
        from autopilot.infrastructure.bootstrap import create_application

        app = create_application(config_path)

        click.secho("Resuming workflow from last checkpoint...", fg="cyan")
        click.echo()

        start_time = time.time()
        execution_id = app.resume_command.execute()

        elapsed = time.time() - start_time
        click.echo()
        click.secho(f"✓ Workflow resumed and completed in {elapsed:.1f}s", fg="green", bold=True)
        click.secho(f"  Execution ID: {execution_id}", fg="white", dim=True)

    except SystemExit:
        raise
    except Exception as exc:
        click.secho(f"✗ Resume failed: {exc}", fg="red", err=True)
        sys.exit(1)


@cli.command()
@click.option("--config-path", default="auto", help="Path to .autopilot.yaml (default: auto-discover)")
def config(config_path: str) -> None:
    """Display the current configuration in YAML format."""
    try:
        from autopilot.infrastructure.bootstrap import create_application

        app = create_application(config_path)
        output = app.config_command.execute()
        click.echo(output)

    except SystemExit:
        raise
    except Exception as exc:
        click.secho(f"Config error: {exc}", fg="red", err=True)
        sys.exit(1)


@cli.command()
def review() -> None:
    """Initiate a review workflow for the current working context."""
    click.echo("Review: not implemented yet")


@cli.command()
@click.option("--config-path", default="auto", help="Path to .autopilot.yaml (default: auto-discover)")
@click.option("--ticket", default=None, help="Filter by ticket ID")
@click.option("--limit", default=20, help="Number of entries to show")
def ledger(config_path: str, ticket: str | None, limit: int) -> None:
    """Display the audit ledger summary."""
    _print_banner()

    try:
        from autopilot.infrastructure.bootstrap import create_application

        app = create_application(config_path)

        if ticket:
            entries = app.ledger.get_by_ticket(ticket)
            click.secho(f"Ledger entries for {ticket}:", fg="cyan")
            for entry in entries[:limit]:
                click.echo(f"  {entry.run_id[:8]} | {entry.status} | {entry.verdict or '—'} | "
                          f"{entry.summary}")
        else:
            summary = app.ledger.summary()
            click.echo(summary)

    except SystemExit:
        raise
    except Exception as exc:
        click.secho(f"Ledger error: {exc}", fg="red", err=True)
        sys.exit(1)
