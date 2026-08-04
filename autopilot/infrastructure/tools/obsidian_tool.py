"""Obsidian tool implementation for searching notes in a local vault.

Searches markdown files in the configured vault directory for content
relevant to a given query. Uses simple keyword matching for the MVP,
with plans to integrate semantic search later.
"""

from pathlib import Path
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolResult


class ObsidianTool:
    """Tool for searching and reading notes from an Obsidian vault.

    Searches markdown files in the vault for content matching a query.
    Returns relevant note excerpts with file paths for context assembly.
    """

    def __init__(self, vault_path: str = "") -> None:
        """Initialize ObsidianTool.

        Args:
            vault_path: Path to the Obsidian vault directory.
                If empty, must be provided in execute() kwargs.
        """
        self._vault_path = vault_path

    @property
    def name(self) -> str:
        return "obsidian"

    @property
    def input_schema(self) -> dict[str, type]:
        return {"query": str, "vault_path": str, "max_results": int}

    @property
    def output_schema(self) -> dict[str, type]:
        return {"notes": list}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Search the Obsidian vault for notes matching the query.

        Args:
            query: Search terms (space-separated keywords).
            vault_path: Path to the vault. Overrides constructor value.
            max_results: Maximum number of notes to return (default: 10).

        Returns:
            ToolResult with list of matching note excerpts.
        """
        query = kwargs.get("query", "")
        vault_path = kwargs.get("vault_path", "") or self._vault_path
        max_results = kwargs.get("max_results", 10)

        if not query:
            return ToolResult(success=False, error="Missing required parameter: query")

        if not vault_path:
            return ToolResult(success=False, error="Missing required parameter: vault_path")

        vault_dir = Path(vault_path)
        if not vault_dir.exists():
            return ToolResult(success=False, error=f"Vault directory not found: {vault_path}")

        if not vault_dir.is_dir():
            return ToolResult(success=False, error=f"Vault path is not a directory: {vault_path}")

        try:
            notes = self._search_vault(vault_dir, query, max_results)
            return ToolResult(success=True, data=notes)
        except PermissionError as e:
            return ToolResult(success=False, error=f"Permission denied reading vault: {e}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error searching vault: {e}")

    def _search_vault(self, vault_dir: Path, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search markdown files in the vault for matching content.

        Uses keyword-based scoring: counts occurrences of query terms
        in each file (case-insensitive). Returns top-scoring files.

        Args:
            vault_dir: Path to the vault directory.
            query: Space-separated search terms.
            max_results: Max notes to return.

        Returns:
            List of note dicts with path, title, excerpt, and score.
        """
        keywords = [kw.lower() for kw in query.split() if kw.strip()]
        if not keywords:
            return []

        scored_notes: list[tuple[float, dict[str, Any]]] = []

        # Walk all markdown files
        for md_file in vault_dir.rglob("*.md"):
            # Skip hidden directories and files
            if any(part.startswith(".") for part in md_file.relative_to(vault_dir).parts):
                continue

            try:
                content = md_file.read_text(encoding="utf-8", errors="ignore")
            except (OSError, PermissionError):
                continue

            # Score by keyword occurrences
            content_lower = content.lower()
            filename_lower = md_file.stem.lower()

            score = 0.0
            for kw in keywords:
                # Content matches
                score += content_lower.count(kw) * 1.0
                # Filename matches (weighted higher)
                score += filename_lower.count(kw) * 5.0

            if score > 0:
                # Extract relevant excerpt
                excerpt = self._extract_excerpt(content, keywords)
                title = md_file.stem
                rel_path = str(md_file.relative_to(vault_dir))

                scored_notes.append((score, {
                    "path": rel_path,
                    "title": title,
                    "excerpt": excerpt,
                    "score": round(score, 2),
                }))

        # Sort by score (descending) and return top results
        scored_notes.sort(key=lambda x: x[0], reverse=True)
        return [note for _, note in scored_notes[:max_results]]

    def _extract_excerpt(self, content: str, keywords: list[str], context_chars: int = 300) -> str:
        """Extract a relevant excerpt around the first keyword match.

        Args:
            content: Full file content.
            keywords: Keywords to find.
            context_chars: Characters of context around the match.

        Returns:
            An excerpt string with the most relevant section.
        """
        content_lower = content.lower()

        # Find the first occurrence of any keyword
        earliest_pos = len(content)
        for kw in keywords:
            pos = content_lower.find(kw)
            if pos != -1 and pos < earliest_pos:
                earliest_pos = pos

        if earliest_pos == len(content):
            # No match found, return the beginning
            return content[:context_chars].strip() + "..." if len(content) > context_chars else content.strip()

        # Extract context around the match
        start = max(0, earliest_pos - context_chars // 2)
        end = min(len(content), earliest_pos + context_chars // 2)

        excerpt = content[start:end].strip()

        if start > 0:
            excerpt = "..." + excerpt
        if end < len(content):
            excerpt = excerpt + "..."

        return excerpt
