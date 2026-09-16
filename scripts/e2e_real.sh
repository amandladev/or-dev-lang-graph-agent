#!/usr/bin/env bash
# Realistic end-to-end test for Autopilot.
#
# Runs the full pipeline with real Jira, real vault, real opencode and real
# git:
#   1. Creates a disposable sandbox repo (develop + local bare remote)
#   2. Creates a small ticket in Jira (via REST API)
#   3. Runs `autopilot work TICKET-ID` in the sandbox
#   4. Verifies branch, commit, push, run record and ledger
#   5. Cleans up the sandbox (and the pushed branch)
#
# Requirements:
#   - autopilot installed (`pip install -e .`)
#   - opencode in PATH
#   - Jira credentials: JIRA_<INSTANCE>_URL, JIRA_<INSTANCE>_EMAIL, JIRA_<INSTANCE>_TOKEN
#
# Usage:
#   scripts/e2e_real.sh                          # creates a new Jira ticket (needs --project)
#   scripts/e2e_real.sh --project WTS            # creates WTS-XXXX and runs the workflow
#   scripts/e2e_real.sh --ticket-id WTS-123      # reuses an existing ticket
#   scripts/e2e_real.sh --config /path/to/cfg.yaml --keep

set -euo pipefail

CONFIG="${AUTOPILOT_CONFIG:-$HOME/.autopilot.yaml}"
TICKET_ID=""
PROJECT=""
KEEP=0

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2 ;;
    --ticket-id) TICKET_ID="$2"; shift 2 ;;
    --project) PROJECT="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) usage ;;
    *) echo "Unknown option: $1" >&2; usage ;;
  esac
done

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
ok() { printf '\033[1;32m  %s\033[0m\n' "$*"; }
fail() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
  if [ -n "${SANDBOX:-}" ] && [ "$KEEP" = 0 ]; then
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

[ -f "$CONFIG" ] || fail "config not found: $CONFIG"
ok "config: $CONFIG"

if [ -n "$TICKET_ID" ]; then
  INSTANCE="${TICKET_ID%%-*}"
  PROJECT="${PROJECT:-$INSTANCE}"
else
  PROJECT="${PROJECT:?--project is required to create a new ticket}"
  INSTANCE="$PROJECT"
fi

for var in URL EMAIL TOKEN; do
  eval "value=\${JIRA_${INSTANCE}_${var}:?JIRA_${INSTANCE}_${var} is not set}"
done
ok "jira instance: $INSTANCE"

# ---------------------------------------------------------------------------
# Sandbox workspace (disposable git repo with develop + local bare remote)
# ---------------------------------------------------------------------------

say "=== Sandbox workspace ==="

SANDBOX=$(mktemp -d "${TMPDIR:-/tmp}/autopilot-e2e.XXXXXX")
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

python3 - "$CONFIG" "$WS" > "$SANDBOX/env.txt" <<'PY'
import sys
import yaml

with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}

cfg["workspace_location"] = sys.argv[2]
cfg["verbosity"] = "normal"

with open(f"{sys.argv[2]}/autopilot-e2e.yaml", "w") as f:
    yaml.safe_dump(cfg, f)

print(cfg.get("vault_location", ""))
print(cfg.get("llm_model", ""))
PY

SANDBOX_CFG="$WS/autopilot-e2e.yaml"
VAULT=$(sed -n '1p' "$SANDBOX/env.txt")
MODEL=$(sed -n '2p' "$SANDBOX/env.txt")
[ -d "$VAULT" ] || fail "vault not found: $VAULT (set vault_location in $CONFIG)"
ok "vault: $VAULT"
ok "model: ${MODEL:-opencode default}"

# ---------------------------------------------------------------------------
# Jira ticket
# ---------------------------------------------------------------------------

say "=== Jira ticket ==="

create_ticket() {
  python3 - "$INSTANCE" "$PROJECT" <<'PY'
import base64
import json
import os
import sys
import urllib.error
import urllib.request

instance, project = sys.argv[1:3]
base = os.environ[f"JIRA_{instance}_URL"].rstrip("/")
email = os.environ[f"JIRA_{instance}_EMAIL"]
token = os.environ[f"JIRA_{instance}_TOKEN"]

summary = "[Autopilot E2E] Implement hello feature"
description = (
    "Implement a small feature in this repository:\n"
    "1. Create src/hello.py with a function hello() that returns the string 'hello'.\n"
    "2. Create tests/test_hello.py with a test that asserts hello() == 'hello'.\n"
    "Make the minimal changes needed and follow existing code style."
)
body = {
    "fields": {
        "project": {"key": project},
        "issuetype": {"name": "Task"},
        "summary": summary,
        "description": description,
        "labels": ["autopilot-e2e"],
    }
}
auth = base64.b64encode(f"{email}:{token}".encode()).decode()
req = urllib.request.Request(
    f"{base}/rest/api/3/issue",
    data=json.dumps(body).encode(),
    headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    },
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
except urllib.error.HTTPError as e:
    print(f"Ticket creation failed (HTTP {e.code}): {e.read().decode()[:300]}", file=sys.stderr)
    sys.exit(1)
except urllib.error.URLError as e:
    print(f"Ticket creation failed (connection): {e.reason}", file=sys.stderr)
    sys.exit(1)
print(data["key"])
PY
}

if [ -z "$TICKET_ID" ]; then
  TICKET_ID=$(create_ticket)
  ok "created $TICKET_ID"
else
  ok "reusing $TICKET_ID"
fi

BRANCH="feature/$(printf '%s' "$TICKET_ID" | tr '[:upper:]' '[:lower:]')"
JIRA_URL=$(printf 'JIRA_%s_URL' "$INSTANCE")

# ---------------------------------------------------------------------------
# Run the workflow
# ---------------------------------------------------------------------------

say "=== Running: autopilot work $TICKET_ID ==="

(cd "$WS" && autopilot work "$TICKET_ID" --config-path "$SANDBOX_CFG")

# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

say "=== Verification ==="

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

git -C "$WS" branch --list "$BRANCH" | grep -q . || fail "branch $BRANCH not found"
ok "branch: $BRANCH"

COMMIT_MSG=$(git -C "$WS" log -1 --pretty=%s "$BRANCH")
[[ "$COMMIT_MSG" == "feat($TICKET_ID):"* ]] || fail "unexpected commit message: $COMMIT_MSG"
ok "commit: $COMMIT_MSG"

git -C "$WS" ls-remote origin "refs/heads/$BRANCH" | grep -q . || fail "branch not pushed to origin"
ok "pushed to origin"

grep -q "$TICKET_ID" "$WS/ledger.json" || fail "ticket not found in ledger.json"
ok "ledger entry present"

# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

say "=== Cleanup ==="

if [ "$KEEP" = 1 ]; then
  ok "keeping sandbox at $SANDBOX"
else
  git -C "$WS" checkout -q develop
  git -C "$WS" branch -qD "$BRANCH" || true
  git -C "$WS" push -q origin ":$BRANCH" || true
  rm -rf "$SANDBOX"
  ok "sandbox removed"
fi

eval "url=\$$JIRA_URL"
printf '\n\033[1;32m✔ E2E test passed.\033[0m\n'
printf '  Ticket: %s/browse/%s (delete manually if desired)\n' "$url" "$TICKET_ID"