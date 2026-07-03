"""Entry point for `python -m autopilot`."""

import sys


def main():
    """Run the Autopilot CLI."""
    try:
        from autopilot.cli.commands import cli

        cli()
    except SystemExit:
        raise
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
