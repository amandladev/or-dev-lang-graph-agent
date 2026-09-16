#!/usr/bin/env bash
# Realistic E2E test with a SIMULATED Jira (local server) and a REAL
# GitHub repo, REAL opencode and REAL git operations.
#
# Flow:
#   1. Clones (or uses) your GitHub repo and ensures a `develop` branch
#   2. Starts the local fake Jira server serving a simulated user story
#   3. Runs `autopilot work <TICKET>` against it (real LLM does the work)
#   4. Verifies branch, commit, push, run record, ledger and story fetch
#   5. Opens a PR (gh) and cleans up local artifacts
#
# Requirements:
#   - autopilot installed (`pip install -e .`)
#   - opencode in PATH
#   - gh authenticated (for --repo-url clone and the PR)
#
# Usage:
#   scripts/e2e_fake_jira.sh --repo-url git@github.com:you/repo.git
#   scripts/e2e_fake_jira.sh --repo-path /path/to/clone --no-pr
#   scripts/e2e_fake_jira.sh --repo-url ... --ticket DFX5-2 --keep

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_URL=""
REPO_PATH=""
TICKET="DFX5-2"
EXPECT_FILES="src/todo.py tests/test_todo.py README.md"
KEEP=0
DO_PR=1
VERBOSE=0
BASE_CONFIG="${AUTOPILOT_CONFIG:-$HOME/.autopilot.yaml}"

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-url) REPO_URL="$2"; shift 2 ;;
    --repo-path) REPO_PATH="$2"; shift 2 ;;
    --ticket) TICKET="$2"; shift 2 ;;
    --config) BASE_CONFIG="$2"; shift 2 ;;
    --expect-files) EXPECT_FILES="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --no-pr) DO_PR=0; shift ;;
    --verbose) VERBOSE=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m  %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

INSTANCE=$(printf '%s' "$TICKET" | cut -d- -f1 | tr '[:lower:]' '[:upper:]')
BRANCH="feature/$(printf '%s' "$TICKET" | tr '[:upper:]' '[:lower:]')"
STORY="$SCRIPT_DIR/stories/$(printf '%s' "$TICKET" | tr '[:upper:]' '[:lower:]').json"
FAKE_VAULT="$SCRIPT_DIR/fake_vault"
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-fake-jira.XXXXXX")
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
  fi
  if [ "$KEEP" = 0 ]; then
    rm -rf "$SANDBOX"
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

say "=== Preflight ==="

command -v autopilot >/dev/null || fail "autopilot not found in PATH (pip install -e .)"
command -v opencode >/dev/null || fail "opencode not found in PATH"
command -v python3 >/dev/null || fail "python3 not found in PATH"
[ -f "$STORY" ] || fail "story file not found: $STORY"
[ -d "$FAKE_VAULT" ] || fail "fake vault not found: $FAKE_VAULT"
[ -f "$BASE_CONFIG" ] || fail "base config not found: $BASE_CONFIG"
if [ "$DO_PR" = 1 ]; then
  command -v gh >/dev/null || fail "gh not found in PATH (or use --no-pr)"
fi
if [ -n "$REPO_URL" ] && [ -n "$REPO_PATH" ]; then
  fail "use only one of --repo-url / --repo-path"
fi
ok "ticket: $TICKET (instance $INSTANCE)"
ok "story: $STORY"

# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

say "=== Repository ==="

if [ -n "$REPO_URL" ]; then
  REPO_PATH="$SANDBOX/repo"
  if command -v gh >/dev/null; then
    gh repo clone "$REPO_URL" "$REPO_PATH" >/dev/null 2>&1 || \
      git clone -q "$REPO_URL" "$REPO_PATH"
  else
    git clone -q "$REPO_URL" "$REPO_PATH"
  fi
  ok "cloned: $REPO_URL"
else
  [ -d "$REPO_PATH" ] || fail "repo path not found: $REPO_PATH"
  ok "using existing clone: $REPO_PATH"
fi

REPO_PATH=$(cd "$REPO_PATH" && pwd)

# autopilot runs each ticket in its own Git worktree (GitWorktreeManager),
# not in $REPO_PATH itself. Mirror its own path resolution here — an
# explicit worktree_root in the base config wins, otherwise it defaults to
# a sibling ".autopilot-worktrees" directory next to workspace_location —
# so preflight/cleanup can find and remove the right worktree.
WORKTREE_ROOT=$(python3 -c "
import yaml
cfg = yaml.safe_load(open('$BASE_CONFIG')) or {}
print(cfg.get('worktree_root') or '')
")
[ -n "$WORKTREE_ROOT" ] || WORKTREE_ROOT="$(dirname "$REPO_PATH")/.autopilot-worktrees"
TICKET_SLUG=$(printf '%s' "$TICKET" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')
TICKET_WORKTREE="$WORKTREE_ROOT/$TICKET_SLUG"

# Unregister the ticket's worktree and drop its metadata so a subsequent
# branch delete (below) actually succeeds — `git branch -D` fails silently
# on a branch still checked out in a worktree, which used to leave stale
# worktrees/branches behind on every re-run against --repo-path.
reset_ticket_worktree() {
  if [ -d "$TICKET_WORKTREE" ]; then
    git -C "$REPO_PATH" worktree remove --force "$TICKET_WORKTREE" 2>/dev/null || rm -rf "$TICKET_WORKTREE"
  fi
  git -C "$REPO_PATH" worktree prune 2>/dev/null || true
  rm -f "$WORKTREE_ROOT/.autopilot-workspaces/$TICKET_SLUG.json"
}

reset_ticket_worktree
git -C "$REPO_PATH" checkout -q develop 2>/dev/null || git -C "$REPO_PATH" checkout -q -b develop
git -C "$REPO_PATH" push -qu origin develop
ok "develop branch ready (with upstream)"

git -C "$REPO_PATH" branch -qD "$BRANCH" 2>/dev/null || true
git -C "$REPO_PATH" push -q origin ":$BRANCH" 2>/dev/null || true
BRANCH_ALT="feature/$(printf '%s' "$TICKET" | tr '[:lower:]' '[:upper:]')"
git -C "$REPO_PATH" branch -qD "$BRANCH_ALT" 2>/dev/null || true
git -C "$REPO_PATH" push -q origin ":$BRANCH_ALT" 2>/dev/null || true
git -C "$REPO_PATH" branch -qD autopilot-results 2>/dev/null || true

# ---------------------------------------------------------------------------
# Fake Jira server
# ---------------------------------------------------------------------------

say "=== Fake Jira server ==="

JIRA_LOG="$SANDBOX/jira.log"
python3 "$SCRIPT_DIR/fake_jira_server.py" --story "$STORY" --log "$JIRA_LOG" \
  > "$SANDBOX/server.out" 2>>"$SANDBOX/server.err" &
SERVER_PID=$!

for _ in $(seq 1 50); do
  grep -q '^FAKE_JIRA_PORT=' "$SANDBOX/server.out" 2>/dev/null && break
  sleep 0.1
done
PORT=$(sed -n 's/^FAKE_JIRA_PORT=//p' "$SANDBOX/server.out")
[ -n "$PORT" ] || fail "fake jira server failed to start (see $SANDBOX/server.err)"

export "JIRA_${INSTANCE}_URL=http://127.0.0.1:${PORT}"
export "JIRA_${INSTANCE}_EMAIL=autopilot-e2e@localhost"
export "JIRA_${INSTANCE}_TOKEN=fake-token"
ok "JIRA_${INSTANCE}_URL=http://127.0.0.1:${PORT}"

# ---------------------------------------------------------------------------
# Autopilot config
# ---------------------------------------------------------------------------

say "=== Config ==="

python3 - "$BASE_CONFIG" "$REPO_PATH" "$FAKE_VAULT" "$SANDBOX/e2e.yaml" "$VERBOSE" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}

cfg["workspace_location"] = sys.argv[2]
cfg["vault_location"] = sys.argv[3]
cfg["timeout_seconds"] = 300
cfg["max_retries"] = 2
cfg["verbosity"] = "verbose" if sys.argv[5] == "1" else "normal"
cfg["approvals"] = []

with open(sys.argv[4], "w") as f:
    yaml.safe_dump(cfg, f)
PY

E2E_CONFIG="$SANDBOX/e2e.yaml"
MODEL=$(python3 -c "import yaml; print(yaml.safe_load(open('$E2E_CONFIG')).get('llm_model', '') or 'opencode default')")
ok "vault: $FAKE_VAULT (fake)"
ok "workspace: $REPO_PATH"
ok "model: $MODEL"

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

say "=== Running: autopilot work $TICKET ==="

(cd "$REPO_PATH" && autopilot work "$TICKET" --config-path "$E2E_CONFIG")

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

say "=== Verification ==="

grep -q "GET.*/rest/api/3/issue/$TICKET" "$JIRA_LOG" \
  || fail "fake Jira server never received the story fetch (agent did not read the story)"
ok "story fetched from simulated Jira"

RUN_RECORD=$(ls -dt "$REPO_PATH"/runs/*/run-record.json 2>/dev/null | head -1)
[ -n "$RUN_RECORD" ] || fail "run record not found under $REPO_PATH/runs/"

python3 - "$RUN_RECORD" <<'PY'
import json
import sys

d = json.load(open(sys.argv[1]))
print(f"  run record: status={d['status']} verdict={d.get('verdict')} "
      f"tests={d.get('tests_executed')}/{d.get('tests_passed')}")
if d["status"] != "completed" or d.get("verdict") != "PASS":
    sys.exit(1)
PY
ok "run record: completed / PASS"

git -C "$REPO_PATH" branch --list "$BRANCH" | grep -q . || {
  echo "  ✗ branch $BRANCH not found — publisher git operations:" >&2
  # .autopilot_state.json lives inside the ticket's worktree, not $REPO_PATH.
  STATE_FILE="$TICKET_WORKTREE/.autopilot_state.json"
  if [ -f "$STATE_FILE" ]; then
    python3 - "$STATE_FILE" <<'PY' >&2
import json
import sys

d = json.load(open(sys.argv[1]))
for op in d.get("metrics", {}).get("git", {}).get("operations", []):
    mark = "OK  " if op["success"] else "FAIL"
    print(f"  {mark} {' '.join(op['command'])} | {op['output'][:200]}")
PY
  else
    echo "  (no state file at $STATE_FILE)" >&2
  fi
  exit 1
}
ok "branch: $BRANCH"

COMMIT_MSG=$(git -C "$REPO_PATH" log -1 --pretty=%s "$BRANCH")
[[ "$COMMIT_MSG" == "feat($TICKET):"* ]] || fail "unexpected commit message: $COMMIT_MSG"
ok "commit: $COMMIT_MSG"

git -C "$REPO_PATH" ls-remote origin "refs/heads/$BRANCH" | grep -q . || fail "branch not pushed to origin"
ok "pushed to origin"

COMMIT_FILES=$(git -C "$REPO_PATH" show --name-only --pretty=format: "$BRANCH")
for EXPECTED in $EXPECT_FILES; do
  grep -q "$EXPECTED" <<< "$COMMIT_FILES" || fail "$EXPECTED not in the pushed commit"
done
ok "expected files in commit ($EXPECT_FILES)"

grep -q "$TICKET" "$REPO_PATH/ledger.json" || fail "ticket not found in ledger.json"
ok "ledger entry present"

if git -C "$REPO_PATH" show --name-only --pretty=format: "$BRANCH" | grep -q ".gitignore"; then
  ok ".gitignore present in commit"
else
  echo "  ⚠ .gitignore not found in commit (check for __pycache__ pollution in the PR)"
fi

# ---------------------------------------------------------------------------
# Pull request
# ---------------------------------------------------------------------------

if [ "$DO_PR" = 1 ]; then
  say "=== Pull request ==="
  PR_TITLE="${COMMIT_MSG}"
  REMOTE_URL=$(git -C "$REPO_PATH" config --get remote.origin.url)
  # Normalize any remote URL (ssh with host alias, https, ...) to owner/name
  # because `gh` only understands its own repo references, not ssh host aliases.
  REPO_REF="${REMOTE_URL#*:}"
  REPO_REF="${REPO_REF%.git}"
  REPO_REF=$(basename "$(dirname "$REPO_REF")")/"$(basename "$REPO_REF")"
  echo "  remote: $REMOTE_URL -> gh repo: $REPO_REF"
  if gh pr create \
      --repo "$REPO_REF" \
      --base develop --head "$BRANCH" \
      --title "$PR_TITLE" \
      --body "Automated E2E test run for $TICKET (simulated Jira, real implementation)." \
      > "$SANDBOX/pr.out" 2>"$SANDBOX/pr.err"; then
    ok "PR created: $(cat "$SANDBOX/pr.out")"
  else
    echo "  ⚠ PR creation failed: $(cat "$SANDBOX/pr.err")" >&2
  fi
fi

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

say "=== Cleanup ==="

if [ "$KEEP" = 1 ]; then
  ok "keeping audit artifacts at $REPO_PATH and code/branch in the worktree at $TICKET_WORKTREE"
else
  reset_ticket_worktree
  git -C "$REPO_PATH" branch -qD "$BRANCH" 2>/dev/null || true
  git -C "$REPO_PATH" branch -qD autopilot-results 2>/dev/null || true
  rm -rf "$REPO_PATH/runs" "$REPO_PATH/.autopilot_state.json" \
         "$REPO_PATH/ledger.json" "$REPO_PATH/knowledge" \
         "$REPO_PATH/.autopilot_run.lock"
  ok "local artifacts and worktree removed (remote branch kept for the PR)"
fi

printf '\n\033[1;32m✔ E2E test passed.\033[0m\n'
printf '  Remote branch: %s (review / delete in GitHub)\n' "$BRANCH"