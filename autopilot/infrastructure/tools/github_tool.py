"""GitHub tool implementation — pull request creation via the gh CLI.

Uses the user's existing `gh` authentication, so no tokens need to be
stored by Autopilot. `gh` only understands `owner/name` repo references,
not raw SSH remote URLs with host aliases, so the tool normalizes the
remote URL before calling `gh`.
"""

import subprocess
from typing import Any

from autopilot.domain.interfaces.tool_interface import ToolResult


class GitHubTool:
    """GitHub operations executed through the gh CLI.

    Implements the ToolInterface protocol for uniform tool access.
    """

    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout

    @property
    def name(self) -> str:
        """Unique string identifier for tool lookup."""
        return "github"

    @property
    def input_schema(self) -> dict[str, type]:
        """Expected input parameters."""
        return {"action": str, "cwd": str, "head": str, "base": str, "title": str, "body": str}

    @property
    def output_schema(self) -> dict[str, type]:
        """Expected output structure on success."""
        return {"result": dict}

    def execute(self, **kwargs: Any) -> ToolResult:
        """Execute a GitHub operation through gh.

        Args:
            action: One of "create_pr".
            cwd: Git repository root used to resolve the remote.
            head: Source branch of the pull request.
            base: Target branch of the pull request.
            title: Pull request title.
            body: Pull request body.

        Returns:
            ToolResult with the PR URL on success. When the workspace is
            not a GitHub repository the result carries success=False with
            data["skipped"]=True, letting callers downgrade it to a warning.
        """
        action = kwargs.get("action", "")
        if action != "create_pr":
            return ToolResult(success=False, error=f"Unsupported action: {action}")
        return self._create_pr(**kwargs)

    def _create_pr(self, **kwargs: Any) -> ToolResult:
        cwd = kwargs.get("cwd") or None
        head = kwargs.get("head", "")
        base = kwargs.get("base", "")
        title = kwargs.get("title", "")
        body = kwargs.get("body", "")

        remote = self._remote_url(cwd)
        if remote is None:
            return ToolResult(success=False, error="Unable to resolve git remote 'origin'")
        if not self._remote_host(remote).endswith("github.com"):
            return ToolResult(
                success=False,
                data={"skipped": True, "reason": f"Remote '{remote}' is not a GitHub repository"},
            )
        repo = self._repo_slug(remote)
        if not repo:
            return ToolResult(success=False, error=f"Unable to parse owner/name from remote '{remote}'")

        cmd = [
            "gh", "pr", "create",
            "--repo", repo,
            "--base", base,
            "--head", head,
            "--title", title,
            "--body", body,
        ]
        try:
            result = self.run(cmd, cwd)
        except FileNotFoundError:
            return ToolResult(success=False, error="gh command not found. Is GitHub CLI installed?")
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error=f"gh pr create timed out after {self._timeout}s")
        except Exception as exc:
            return ToolResult(success=False, error=f"Error running gh: {exc}")

        output = (result.stdout or "").strip()
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            return ToolResult(
                success=False,
                error=f"gh pr create exited with {result.returncode}: {stderr or output}",
            )
        return ToolResult(success=True, data={"pr_url": output, "repo": repo})

    def _remote_url(self, cwd: str | None) -> str | None:
        try:
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=cwd,
            )
        except Exception:
            return None
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None

    @staticmethod
    def _remote_host(remote: str) -> str:
        """Extract the host from any remote URL form."""
        remote = remote.replace("ssh://", "").replace("https://", "").replace("http://", "")
        if remote.startswith("git@"):
            return remote.split(":", 1)[0]
        return remote.split("/", 1)[0]

    @classmethod
    def _repo_slug(cls, remote: str) -> str:
        """Extract owner/name from any remote URL form."""
        remote = remote.replace("ssh://", "").replace("https://", "").replace("http://", "")
        path = remote.split(":", 1)[-1] if ":" in remote else remote.split("/", 1)[-1]
        path = path.removesuffix(".git").removesuffix("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            return f"{parts[-2]}/{parts[-1]}"
        return ""

    def run(self, cmd: list[str], cwd: str | None) -> subprocess.CompletedProcess:
        """Run a subprocess (exposed for test doubles)."""
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=self._timeout, cwd=cwd
        )
