#!/usr/bin/env bash
# One-time credential capture for the jira skill.
# Writes to ~/.config/dropkit/credentials.env with mode 0600.
# The API token is never echoed, logged, or passed on the command line.
#
# The file is shared with other dropkit skills (e.g. jira-align,
# confluence-crawler); this script merges JIRA_* keys into the existing
# file without touching other products' keys.
#
# Works for both Atlassian Cloud (*.atlassian.net) and self-hosted
# Server / Data Center installs. Authentication differs by flavor:
#   - Cloud  : Basic auth = base64(email:api_token).
#   - Server : Bearer Personal Access Token (no email needed).

set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/dropkit"
CONFIG_FILE="$CONFIG_DIR/credentials.env"

umask 077
mkdir -p "$CONFIG_DIR"

printf 'Jira base URL:\n'
printf '  - Cloud example:   https://your-site.atlassian.net\n'
printf '  - Server example:  https://jira.corp.example.com\n'
printf '> '
read -r BASE_URL
BASE_URL="${BASE_URL%/}"
if [[ -z "$BASE_URL" ]]; then
  echo "error: base URL is required" >&2
  exit 1
fi
if [[ ! "$BASE_URL" =~ ^https?:// ]]; then
  echo "error: base URL must start with http:// or https://" >&2
  exit 1
fi

HOST="$(printf '%s' "$BASE_URL" | sed -E 's#^https?://([^/]+).*#\1#' | tr '[:upper:]' '[:lower:]')"
FLAVOR="server"
if [[ "$HOST" == *.atlassian.net || "$HOST" == *.jira.com || "$HOST" == *.jira-dev.com ]]; then
  FLAVOR="cloud"
  echo "detected Atlassian Cloud ($HOST)"
else
  echo "detected self-hosted Server / Data Center ($HOST)"
fi

EMAIL=""
if [[ "$FLAVOR" == "cloud" ]]; then
  printf 'Atlassian account email (used as Basic auth username): '
  read -r EMAIL
  if [[ -z "$EMAIL" ]]; then
    echo "error: email is required for Cloud (Basic auth)" >&2
    exit 1
  fi
fi

if [[ "$FLAVOR" == "cloud" ]]; then
  printf 'Cloud API token (id.atlassian.com → API tokens, hidden): '
else
  printf 'Personal Access Token from Jira (avatar → Profile → Personal Access Tokens, hidden): '
fi
stty -echo
trap 'stty echo' EXIT INT TERM
read -r API_TOKEN
stty echo
trap - EXIT INT TERM
printf '\n'

if [[ -z "$API_TOKEN" ]]; then
  echo "error: API token is required" >&2
  exit 1
fi

# Rewrite the config file, preserving any non-JIRA_* keys so that other
# skills sharing this file (e.g. jira-align, confluence-crawler) keep
# working. JIRA_* keys are removed and replaced; JIRAALIGN_* are left
# untouched (the prefix is distinct).
TMP="$(mktemp "$CONFIG_DIR/.credentials.XXXXXX")"
chmod 600 "$TMP"
if [[ -f "$CONFIG_FILE" ]]; then
  grep -v -E '^(JIRA_BASE_URL|JIRA_EMAIL|JIRA_API_TOKEN|JIRA_FLAVOR)=' "$CONFIG_FILE" > "$TMP" || true
fi
{
  printf 'JIRA_BASE_URL=%q\n' "$BASE_URL"
  printf 'JIRA_FLAVOR=%q\n' "$FLAVOR"
  if [[ -n "$EMAIL" ]]; then
    printf 'JIRA_EMAIL=%q\n' "$EMAIL"
  fi
  printf 'JIRA_API_TOKEN=%q\n' "$API_TOKEN"
} >> "$TMP"
mv "$TMP" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

unset API_TOKEN

echo "Wrote credentials to $CONFIG_FILE (mode 0600)."
echo "Verify connectivity with: python scripts/jira.py check"
