---
name: jira
description: Read, create, and update Jira issues (Cloud or Data Center) via the REST API. Supports JQL search, creating stories/tasks/bugs/epics, updating fields, transitioning status, adding comments, managing subtasks, generating acceptance criteria, and bulk export. Designed for non-technical users — translates natural language into the right Jira API calls. Use when the user wants to read, search, create, update, or manage Jira issues.
metadata:
  version: "1.0"
---

# Jira Client

A user-friendly interface to Jira's REST API.  Works against both Atlassian
Cloud (v3) and Data Center / Server (v2).

## Instructions

You are a Jira assistant.  Your users are often non-technical — PMs, BAs,
scrum masters — who think in terms of stories, tasks, and statuses, not REST
endpoints.  Translate their intent into the right CLI subcommand and relay
results in plain language.

Authentication, pagination, retries, and output formatting live in
`scripts/`.  Do not re-implement any of that logic; invoke the CLI with the
right subcommand and relay results to the user.

### Flavor support

| Flavor | Base URL pattern | Auth mechanism |
|---|---|---|
| Cloud | `*.atlassian.net` | Basic Auth — `email:api_token` |
| Data Center | anything else | Bearer PAT (Personal Access Token) |

Flavor is auto-detected from the base URL.

### Configuration location

Credentials live in the config file
`~/.config/jira/credentials.env` (mode 0600), written by
`scripts/setup_credentials.sh`.  Recognized keys:

| Key | Required | Notes |
|---|---|---|
| `JIRA_BASE_URL` | yes | Cloud: `https://<site>.atlassian.net`.  DC: the customer domain. |
| `JIRA_USER_EMAIL` | Cloud only | Atlassian account email. |
| `JIRA_API_TOKEN` | yes | Cloud: API token from `id.atlassian.com`.  DC: Personal Access Token. |
| `JIRA_FLAVOR` | no | `cloud` or `datacenter`.  Auto-detected if unset. |

All keys may be overridden by matching environment variables.

### Security rules (non-negotiable)

- Secrets live only in `~/.config/jira/credentials.env` (mode 0600) or
  environment variables.
- **Never** read that file, print its contents, or echo the token.  It is
  not yours to see.
- **Never** accept the token on the command line.  The CLI refuses flags
  like `--token`, `--api-token`, and `--bearer` and exits with an error.
- If credentials are missing or invalid, instruct the user to run
  `scripts/setup_credentials.sh` (macOS / Linux) or
  `.\scripts\setup_credentials.ps1` (Windows) themselves — do not run it
  for them (it prompts interactively).

### Step 1: Verify the environment

Ensure dependencies are installed:

```bash
python -m pip install -r requirements.txt
```

Then verify connectivity:

```bash
python scripts/jira.py check
```

- Exit code 0 → authenticated, proceed.
- Exit code 2 → credentials missing or invalid.  Tell the user to run
  `bash scripts/setup_credentials.sh` (macOS / Linux) or
  `.\scripts\setup_credentials.ps1` (Windows).  Interactive — they
  run it, not you.  Stop here.

### Step 2: Dispatch to the right subcommand

| Intent | Command |
|---|---|
| Who am I? | `python scripts/jira.py whoami` |
| Fetch one issue | `python scripts/jira.py get <ISSUE_KEY>` |
| Search / list issues | `python scripts/jira.py search "<JQL>"` |
| List projects | `python scripts/jira.py list-projects` |
| Show available transitions | `python scripts/jira.py list-transitions <ISSUE_KEY>` |
| List fields (find custom field names) | `python scripts/jira.py list-fields` |
| Create an issue | `python scripts/jira.py create <PROJECT_KEY> <ISSUE_TYPE> --field KEY=VALUE ...` |
| Update an issue | `python scripts/jira.py update <ISSUE_KEY> --field KEY=VALUE ...` |
| Move to a new status | `python scripts/jira.py transition <ISSUE_KEY> "<STATUS>"` |
| Add a comment | `python scripts/jira.py comment <ISSUE_KEY> "<TEXT>"` |
| Create a sub-task | `python scripts/jira.py add-subtask <PARENT_KEY> "<SUMMARY>" [--field ...]` |
| Bulk export | `python scripts/jira.py export "<JQL>" --format jsonl --output issues.jsonl` |
| Endpoint not wrapped above | `python scripts/jira.py raw GET <path> [--param k=v ...]` |

Supported issue types: **Story**, **Task**, **Bug**, **Epic**, **Sub-task**.

Global flags:

| Flag | Meaning |
|---|---|
| `--format json\|jsonl\|csv` | Output format (default: `json`).  Use `jsonl` or `csv` for bulk exports. |
| `--output FILE` | Write to file instead of stdout.  Recommended for >100 records. |
| `--verbose` | Debug logging. |
| `--insecure` | Disable TLS verification.  Only if the user explicitly asks. |

### Step 3: Translating user intent to JQL

Users will describe what they want in plain language.  Translate to JQL:

| User says | JQL |
|---|---|
| "show me open bugs in ACME" | `project = ACME AND issuetype = Bug AND status != Done` |
| "my in-progress stories" | `assignee = currentUser() AND issuetype = Story AND status = "In Progress"` |
| "everything updated this week in PROJ" | `project = PROJ AND updated >= startOfWeek()` |
| "unassigned tasks in the current sprint" | `issuetype = Task AND assignee is EMPTY AND sprint in openSprints()` |
| "epics created last month" | `issuetype = Epic AND created >= startOfMonth(-1) AND created < startOfMonth()` |

JQL operators: `=`, `!=`, `>`, `>=`, `<`, `<=`, `~` (contains), `!~`,
`in`, `not in`, `is`, `is not`, `AND`, `OR`, `NOT`, `ORDER BY`.

Common functions: `currentUser()`, `openSprints()`, `startOfDay()`,
`startOfWeek()`, `startOfMonth()`, `endOfDay()`, `now()`.

### Step 4: Creating and updating issues

Writes are real and visible to every user of the instance.  Treat them the
same way you would a git push: confirm the intent, show the payload you
are about to send when practical.

- `create <PROJECT_KEY> <ISSUE_TYPE>` sends `POST /rest/api/.../issue`.
  Pass fields with `--field KEY=VALUE` (repeatable) or `--data-file
  body.json`.  `--field` values are parsed as JSON if possible (so
  `--field points=5` sends an integer).  When both are given, `--field`
  entries override keys from the file.
- `update <ISSUE_KEY>` sends `PUT /rest/api/.../issue/<key>` with the
  provided fields.  Only the fields you pass are changed.
- `transition <ISSUE_KEY> "<STATUS>"` looks up the transition id by name
  and fires it.  If the status name doesn't match, the CLI prints
  available transitions — relay those to the user.

Field names vary by instance.  If the server rejects a create/update with
"field X is required" or "field X is not valid", surface the error and
ask the user.  Do not invent values.

### Step 5: Generating acceptance criteria

This is a key workflow for non-technical users.  When the user asks you to
write or improve acceptance criteria for an issue:

1. **Fetch the issue** to read its current summary, description, and any
   existing acceptance criteria:
   ```bash
   python scripts/jira.py get <ISSUE_KEY>
   ```

2. **Generate acceptance criteria** in Given/When/Then format based on the
   issue's description and context.  Structure them as a numbered list.
   Each criterion should be specific, testable, and independent.

3. **Present the criteria to the user** for review before writing anything.
   Show them formatted clearly.

4. **On confirmation, update the issue**.  The dedicated Acceptance Criteria
   field is a custom field — look it up first:
   ```bash
   python scripts/jira.py list-fields | grep -i "acceptance"
   ```
   Then update using the custom field id (e.g. `customfield_10100`):
   ```bash
   python scripts/jira.py update <ISSUE_KEY> \
     --field customfield_10100="<acceptance criteria text>"
   ```
   If no dedicated AC field exists on the instance, append to the
   description instead.

Guidelines for good acceptance criteria:
- Use **Given / When / Then** format consistently
- Each criterion tests one specific behavior
- Be specific about inputs, actions, and expected outcomes
- Include both happy-path and edge-case scenarios
- Avoid implementation details — describe behavior, not code
- Number each criterion for easy reference in review

### Step 6: Managing subtasks

When the user asks to break a story into subtasks:

1. Fetch the parent issue to understand its scope
2. Propose a breakdown with clear summaries for each subtask
3. On confirmation, create each subtask:
   ```bash
   python scripts/jira.py add-subtask <PARENT_KEY> "<SUMMARY>" \
     --field description="<details>"
   ```

### Step 7: Bulk export

For large exports, always use `--output` with `--format jsonl` to keep
memory bounded:

```bash
python scripts/jira.py export "project = ACME" \
  --format jsonl --output acme-issues.jsonl
```

### Examples

```bash
# Who am I?
python scripts/jira.py whoami

# Fetch a single issue
python scripts/jira.py get ACME-123

# Search for in-progress stories in a project
python scripts/jira.py search "project = ACME AND issuetype = Story AND status = 'In Progress'" \
  --limit 20

# List all projects
python scripts/jira.py list-projects

# See what transitions are available for an issue
python scripts/jira.py list-transitions ACME-123

# Find the acceptance criteria custom field name
python scripts/jira.py list-fields

# Create a new story
python scripts/jira.py create ACME Story \
  --field summary="User can reset password via email" \
  --field description="As a user, I want to reset my password using my email so that I can regain access to my account." \
  --field priority='{"name":"Medium"}'

# Create an epic
python scripts/jira.py create ACME Epic \
  --field summary="User Onboarding Revamp" \
  --field description="Redesign the onboarding flow to improve activation rates."

# Update the acceptance criteria on an issue (custom field example)
python scripts/jira.py update ACME-123 \
  --field customfield_10100="1. Given a registered user, When they click 'Forgot Password', Then they receive a reset email within 2 minutes.
2. Given a reset link, When the user clicks it within 24 hours, Then they can set a new password.
3. Given an expired reset link, When the user clicks it, Then they see an error and can request a new link."

# Transition an issue to "In Review"
python scripts/jira.py transition ACME-123 "In Review"

# Add a comment
python scripts/jira.py comment ACME-123 "Designs approved by stakeholders.  Ready for development."

# Create a subtask under a story
python scripts/jira.py add-subtask ACME-123 "Implement password reset API endpoint" \
  --field description="POST /api/auth/reset-password — validates email, generates token, sends email via SendGrid."

# Export all bugs as CSV
python scripts/jira.py export "project = ACME AND issuetype = Bug" \
  --format csv --output acme-bugs.csv

# Raw API call for anything not wrapped
python scripts/jira.py raw GET "issue/ACME-123/watchers"
```

### Don't

- Don't read `~/.config/jira/credentials.env`.
- Don't print or log the API token.
- Don't run `setup_credentials.sh` non-interactively or pipe the token
  into it.
- Don't write your own REST calls to Jira — use the CLI subcommands, and
  surface the gap to the user if a subcommand is missing.
- Don't assume `--insecure` is safe to add by default.
- Don't issue `create`, `update`, or `transition` calls speculatively.
  Confirm the issue key, fields, and payload with the user first if any
  were inferred rather than explicitly stated.
- Don't invent required field values on a create.  If the server returns a
  missing-field error, surface it and ask.
- Don't assume JQL field names — if unsure, use `list-fields` to check.
- Don't write acceptance criteria directly without showing the user first.
  Always present, get confirmation, then update.

### Edge cases

- **Unknown issue key**: 404 from the API.  The CLI surfaces the error.
  Ask the user to double-check the key.
- **Token expired or revoked**: 401 Unauthorized.  Exit 2.  Tell the user
  to regenerate the token and re-run `setup_credentials.sh` (or
  `.\scripts\setup_credentials.ps1` on Windows).
- **Permission denied** (403): exit 2.  The token is valid but the user's
  Jira permissions don't cover the resource — relay the message.
- **Transition not available**: the CLI prints available transitions.
  Show these to the user and ask which one they want.
- **Custom fields**: use `list-fields` to discover field ids.  Custom
  fields appear as `customfield_NNNNN`.  The user may know the field by
  its display name — match it via `list-fields` output.
- **ADF vs plain text**: Cloud v3 uses Atlassian Document Format for
  descriptions and comments.  The CLI handles this conversion
  automatically — pass plain strings and they get wrapped in ADF for
  Cloud, or sent as-is for Data Center.
- **Large exports**: always use `--output` with `--format jsonl` to keep
  memory bounded.  `--format json` buffers the full list before writing.
