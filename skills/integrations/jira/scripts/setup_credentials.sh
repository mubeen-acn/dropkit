#!/usr/bin/env bash
# One-time credential capture for the Jira skill.
# Writes to ~/.config/jira/credentials.env with mode 0600.
# The API token is never echoed, logged, or passed on the command line.
#
# This script merges Jira keys into the existing file without touching
# other keys.
#
# Supports both Atlassian Cloud (*.atlassian.net) and Data Center.
#   - Cloud auth:  Basic Auth (email + API token from id.atlassian.com)
#   - DC auth:     Bearer PAT (Personal Access Token from Jira profile)

set -euo pipefail

CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/jira"
CONFIG_FILE="$CONFIG_DIR/credentials.env"

umask 077
mkdir -p "$CONFIG_DIR"

printf 'Jira base URL:\n'
printf '  - Cloud example:       https://your-site.atlassian.net\n'
printf '  - Data Center example: https://jira.corp.example.com\n'
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
FLAVOR="datacenter"
USER_EMAIL=""

if [[ "$HOST" == *.atlassian.net ]]; then
  FLAVOR="cloud"
  echo "detected Atlassian Cloud ($HOST)"
  printf 'Atlassian account email: '
  read -r USER_EMAIL
  if [[ -z "$USER_EMAIL" ]]; then
    echo "error: email is required for Cloud auth" >&2
    exit 1
  fi
  printf '\nAPI token from https://id.atlassian.com/manage-profile/security/api-tokens (hidden): '
else
  echo "detected Data Center / Server ($HOST)"
  printf 'Personal Access Token from Jira profile (hidden): '
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
# skills sharing this file keep working.
TMP="$(mktemp "$CONFIG_DIR/.credentials.XXXXXX")"
chmod 600 "$TMP"
if [[ -f "$CONFIG_FILE" ]]; then
  grep -v -E '^(JIRA_BASE_URL|JIRA_USER_EMAIL|JIRA_API_TOKEN|JIRA_FLAVOR)=' "$CONFIG_FILE" > "$TMP" || true
fi
{
  printf 'JIRA_BASE_URL=%q\n' "$BASE_URL"
  printf 'JIRA_FLAVOR=%q\n' "$FLAVOR"
  printf 'JIRA_USER_EMAIL=%q\n' "$USER_EMAIL"
  printf 'JIRA_API_TOKEN=%q\n' "$API_TOKEN"
} >> "$TMP"
mv "$TMP" "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"

unset API_TOKEN

echo "Wrote credentials to $CONFIG_FILE (mode 0600)."
echo "Verify connectivity with: python scripts/jira.py check"
