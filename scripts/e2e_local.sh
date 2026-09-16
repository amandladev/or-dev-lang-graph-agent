#!/usr/bin/env bash
# Self-contained realistic E2E test for Autopilot.
#
# Everything runs locally — no GitHub, no real Jira:
#   1. Creates a disposable sandbox repo with a LOCAL bare remote
#   2. Starts the local fake Jira server serving a simulated user story
#   3. Runs `autopilot work <TICKET>` (real LLM via opencode does the work)
#   4. Verifies story fetch, run record, branch, commit, push and ledger
#
# Requirements:
#   - autopilot installed (`pip install -e .`)
#   - opencode in PATH (configured with a working LLM)
#
# Usage:
#   scripts/e2e_local.sh                       # story DFX5-2 by default
#   scripts/e2e_local.sh --ticket DFX5-1       # simpler hello story
#   scripts/e2e_local.sh --expect-files "src/hello.py tests/test_hello.py"
#   scripts/e2e_local.sh --keep                # keep sandbox for inspection

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
TICKET="DFX5-2"
EXPECT_FILES=""
KEEP=0
VERBOSE=0
BASE_CONFIG="${AUTOPILOT_CONFIG:-$HOME/.autopilot.yaml}"

usage() {
  sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ticket) TICKET="$2"; shift 2 ;;
    --config) BASE_CONFIG="$2"; shift 2 ;;
    --expect-files) EXPECT_FILES="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
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
SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-e2e-local.XXXXXX")
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
ok "ticket: $TICKET (instance $INSTANCE)"
ok "story: $STORY"

# ---------------------------------------------------------------------------
# Sandbox workspace (disposable git repo + local bare remote)
# ---------------------------------------------------------------------------

say "=== Sandbox workspace ==="

WS="$SANDBOX/workspace"
REMOTE="$SANDBOX/remote.git"
mkdir -p "$WS"

git init -q -b develop "$WS"
git -C "$WS" config user.name "Autopilot E2E"
git -C "$WS" config user.email "autopilot-e2e@localhost"
git init -q --bare "$REMOTE"
git -C "$WS" remote add origin "$REMOTE"

cat > "$WS/pyproject.toml" <<'EOF'
[project]
name = "autopilot-e2e"
version = "0.1.0"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["."]
EOF

mkdir -p "$WS/src" "$WS/tests"
cat > "$WS/tests/test_sanity.py" <<'EOF'
def test_sanity():
    assert True
EOF

git -C "$WS" add -A
git -C "$WS" commit -qm "initial commit"
git -C "$WS" push -qu origin develop
ok "sandbox repo: $WS (develop pushed to local bare remote)"

WORKTREE_ROOT="$SANDBOX/.autopilot-worktrees"
TICKET_WORKTREE="$WORKTREE_ROOT/$(printf '%s' "$TICKET" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//')"

# ---------------------------------------------------------------------------
# Fake Jira server
# ---------------------------------------------------------------------------

say "=== Fake Jira server ==="

JIRA_LOG="$SANDBOX/jira-log.jsonl"
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

python3 - "$BASE_CONFIG" "$WS" "$FAKE_VAULT" "$SANDBOX/e2e.yaml" "$WORKTREE_ROOT" "$VERBOSE" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}

cfg["workspace_location"] = sys.argv[2]
cfg["vault_location"] = sys.argv[3]
cfg["worktree_root"] = sys.argv[5]
cfg["approvals"] = []
with open(sys.argv[4], "w") as f:
    yaml.safe_dump(cfg, f)
PY

E2E_CONFIG="$SANDBOX/e2e.yaml"
ok "vault: $FAKE_VAULT (fake)"
ok "workspace: $WS"
ok "worktree_root: $WORKTREE_ROOT"

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

say "=== Running: autopilot work $TICKET ==="

(cd "$WS" && autopilot work "$TICKET" --config-path "$E2E_CONFIG")

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

say "=== Verification ==="

grep -q "GET.*/rest/api/3/issue/$TICKET" "$JIRA_LOG" \
  || fail "fake Jira server never received the story fetch (agent did not read the story)"
ok "story fetched from simulated Jira"

RUN_RECORD=$(ls "$WS"/runs/*/run-record.json 2>/dev/null | head -1)
[ -n "$RUN_RECORD" ] || fail "run record not found under $WS/runs/"

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

[ -d "$TICKET_WORKTREE" ] || fail "ticket worktree not found: $TICKET_WORKTREE"
ok "worktree: $TICKET_WORKTREE"

STATE_FILE="$TICKET_WORKTREE/.autopilot_state.json"
[ -f "$STATE_FILE" ] || fail "state file not found: $STATE_FILE"

git -C "$WS" branch --list "$BRANCH" | grep -q . || {
  echo "  ✗ branch $BRANCH not found — publisher git operations:" >&2
  python3 - "$STATE_FILE" <<'PY' >&2
import json
import sys

d = json.load(open(sys.argv[1]))
for op in d.get("metrics", {}).get("git", {}).get("operations", []):
    mark = "OK  " if op["success"] else "FAIL"
    print(f"  {mark} {' '.join(op['command'])} | {op['output'][:200]}")
PY
  exit 1
}
ok "branch: $BRANCH"

COMMIT_MSG=$(git -C "$WS" log -1 --pretty=%s "$BRANCH")
[[ "$COMMIT_MSG" == "feat($TICKET):"* ]] || fail "unexpected commit message: $COMMIT_MSG"
ok "commit: $COMMIT_MSG"

git -C "$WS" ls-remote origin "refs/heads/$BRANCH" | grep -q . || fail "branch not pushed to origin"
ok "pushed to local bare remote"

COMMIT_FILES=$(git -C "$WS" show --name-only --pretty=format: "$BRANCH")
DEFAULT_EXPECT="src/ tests/"
if [ -z "$EXPECT_FILES" ]; then
  EXPECT_FILES="$DEFAULT_EXPECT"
fi
for EXPECTED in $EXPECT_FILES; do
  grep -q "$EXPECTED" <<< "$COMMIT_FILES" || fail "$EXPECTED not in the pushed commit"
done
ok "expected files in commit ($EXPECT_FILES)"

grep -q "$TICKET" "$WS/ledger.json" || fail "ticket not found in ledger.json"
ok "ledger entry present"

python3 - "$STATE_FILE" <<'PY'
import json
import sys

d = json.load(open(sys.argv[1]))
assert d["metrics"]["published"] is True, "publisher did not mark the run as published"
assert any(e.get("type") == "test_result" for e in d["evidence"]), "no test evidence recorded"
print(f"  evidence: {len(d['evidence'])} entries, tests={{k: v for k, v in d['metrics'].items() if 'test' in k}}")
PY
ok "state evidence present"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

say "=== Cleanup ==="

if [ "$KEEP" = 1 ]; then
  ok "keeping sandbox at $SANDBOX"
else
  rm -rf "$SANDBOX"
  ok "sandbox removed"
fi

printf '\n\033[1;32m✔ E2E test passed.\033[0m\n'
