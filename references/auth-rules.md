# Auth rules — the dropkit pattern

This document is for developers maintaining or contributing skills. It
describes the auth pattern that every authenticated dropkit skill (jira,
jira-align, confluence-crawler, …) implements. Per-skill `SKILL.md`
files include a tightened version of these rules so the agent reads them
on every call; this file is the canonical design reference.

## What every authenticated skill must guarantee

1. **Secrets live in one place: `~/.config/dropkit/credentials.env`,
   mode 0600.** Created by `scripts/setup_credentials.sh` on the user's
   explicit invocation. The legacy per-skill paths (e.g.,
   `~/.config/confluence-crawler/config.env`) are still read for
   backward compatibility, but new skills should use the shared path.
2. **Environment variables override the file.** Same key names as the
   file. This is what makes CI use straightforward.
3. **No token on the command line.** The CLI rejects flags whose name
   resembles a token surface (`--token`, `--api-token`, `--bearer`,
   `--pat`, etc.) and exits with a user error. The intent is not to be
   exhaustive about flag names — it's to make the failure mode loud
   when an agent or a user pastes a secret onto the line.
4. **The agent never sees the token.** No `Read` against the credentials
   file, no `cat` via Bash, no echo into chat. SKILL.md states this in
   the imperative.
5. **`setup_credentials.sh` is interactive and idempotent.** It prompts
   for the URL and the token, writes the file at mode 0600, and merges
   into any existing dropkit credentials without disturbing other
   skills' keys. The agent does not run it; it tells the user to.
6. **Mutating operations require explicit confirmation.** `delete`
   refuses to run without `--yes`; the agent does not infer `--yes`
   from intent. Create / update operations have no analogous flag, but
   the SKILL.md instructs the agent to confirm payload and target with
   the user before issuing destructive calls.

## How `SKILL.md` enforces the above

Every authenticated skill has a `### Security rules (non-negotiable)`
section that paraphrases rules 1, 3, 4, and 5 in the imperative voice.
The content is short on purpose — agents pay this prose every call, so
verbosity costs tokens. The wording across skills should match closely
enough that a single `git diff` makes drift visible.

## How the client (`scripts/_client.py`) enforces the above

- Reads credentials only via `load_credentials()`, which checks env
  first then the file. Returns an `AuthError` if either the URL or
  token is missing.
- Builds the `Authorization` header in the constructor. The token is
  never logged, never serialized.
- Maps API responses:
  - `401 Unauthorized` → `AuthError("…re-run scripts/setup_credentials.sh.")`
  - `403 Forbidden` → `AuthError` with permission hint
  - other 4xx → `JiraError`/`JiraAlignError`/etc. with the body text truncated

## How the CLI (`scripts/<skill>.py`) enforces the above

- A `_reject_token_on_cli(argv)` pre-pass scans argv for the banned
  flags before argparse runs, exits with a clear error if any are
  found. Add new banned flags here as new naming variants emerge.
- `check` is the connectivity verifier. Exit codes:
  - `0` — authenticated, ready
  - `2` — missing or invalid credentials (agent should stop and tell
    the user to run `setup_credentials.sh`)
  - `3` — server error (relay to user, don't loop)

## Adding a new authenticated skill

Copy the pattern from `jira` (most current). The credential keys should
be `<SKILL>_BASE_URL`, `<SKILL>_API_TOKEN`, optional `<SKILL>_FLAVOR`,
and any skill-specific extras. Reuse the rejection list. Reuse the
`AuthError` / `JiraError` exception split. Add the new skill's `SKILL.md`
security block by copying the existing one and changing the path.
