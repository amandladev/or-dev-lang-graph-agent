"""Ticket entity."""

from dataclasses import dataclass


@dataclass
class Ticket:
    """Represents a work ticket from an issue tracker."""

    id: str = ""
    title: str = ""
    description: str = ""
    status: str = ""
