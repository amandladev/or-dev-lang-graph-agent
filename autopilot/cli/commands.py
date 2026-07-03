"""CLI commands for Autopilot using Click."""

import sys
import uuid

import click


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Autopilot - Local developer workflow orchestration system."""
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())
        ctx.exit(1)


@cli.command()
@click.argument("ticket_id")
def work(ticket_id: str) -> None:
    """Initiate a full workflow execution for the specified ticket.

    TICKET_ID is the identifier of the ticket to work on (e.g., TICKET-123).
    """
    if not ticket_id.strip():
        click.echo("Error: ticket-id must not be empty.", err=True)
        sys.exit(1)

    # Placeholder: In the bootstrap phase, this will call the WorkCommand use case.
    execution_id = str(uuid.uuid4())
    click.echo(f"Workflow started: {execution_id}")


@cli.command()
def status() -> None:
    """Display the current workflow state."""
    click.echo("Status: not implemented in MVP")


@cli.command()
def resume() -> None:
    """Resume a previously paused or failed workflow from its last successful step."""
    # Placeholder: In the bootstrap phase, this will call the ResumeCommand use case.
    click.echo("Resuming workflow from last successful step...")


@cli.command()
def config() -> None:
    """Display the current configuration in YAML format."""
    # Placeholder: In the bootstrap phase, this will call the ConfigCommand use case.
    click.echo("Config: not implemented in MVP")


@cli.command()
def review() -> None:
    """Initiate a review workflow for the current working context."""
    click.echo("Review: not implemented in MVP")
