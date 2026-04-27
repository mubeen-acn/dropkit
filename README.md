# dropkit

Dropkit is a folder of agent playbooks. Each skill is a self-contained directory containing a `SKILL.md` (the agent reads this), a `scripts/` folder (deterministic tooling the agent calls), and a `manifest.json` (deps and I/O). Drop a directory into `~/.claude/skills/` (or your IDE's equivalent) and the skill is installed.

Today the registry covers Atlassian integrations (Jira, Jira Align, Confluence space crawling), file-to-Markdown conversion (PDF, DOCX, XLSX, PPTX, images), Markdown-to-HTML rendering, Outlook `.msg` email conversion, and OpenAPI 3.1 contract generation against the Zalando guidelines. Heavier work (auth flows, retries, pagination, parsing, multipart uploads) lives in the `scripts/` of each skill, so the agent's job stays small: pick a subcommand, run it, relay the output.

## Quickstart

```bash
git clone https://github.com/eugeneacn/dropkit.git
cd dropkit
bash quickstart.sh
```

Generates a sample diagram, runs the file-to-markdown image analyzer against it, and writes two real artifacts under `examples/`. No API keys, no LLM calls — just proof that the toolchain installs and the skill scripts run on your machine. ~30 seconds.

For a working skill in your IDE, jump to **[Installing a skill into your IDE](#installing-a-skill-into-your-ide)** below.

## Catalog

| Skill | Category | Purpose | Deps |
|---|---|---|---|
| [api-contract](skills/contracts/api-contract/) | contracts | Generate OpenAPI 3.1 contracts from natural language, code, or SQL, enforcing 138 Zalando RESTful API Guidelines rules. | none |
| [file-to-markdown](skills/converters/file-to-markdown/) | converters | Convert documents (PDF, DOCX, PPTX, XLSX, XLS) and images (PNG, JPG, TIFF, BMP, WEBP, GIF) to Markdown. Documents use Docling for text extraction; images use a two-pass sliding-window vision strategy. | pip `docling`, `Pillow` |
| [markdown-to-html](skills/converters/markdown-to-html/) | converters | Convert Markdown to styled, self-contained HTML with syntax highlighting, TOC, and responsive layout. | npm `marked`, `highlight.js` |
| [msg-to-markdown](skills/converters/msg-to-markdown/) | converters | Convert Outlook `.msg` emails to structured Markdown preserving headers, body, and attachment metadata. | npm `@nicecode/msg-reader` |
| [confluence-crawler](skills/crawlers/confluence-crawler/) | crawlers | Crawl an authenticated Confluence space (Cloud or Server/DC) by hierarchy and convert pages to Markdown with frontmatter. Handles macros, attachments, link rewriting, depth limits, and idempotent re-crawling. | pip (see `requirements.txt`) |
| [jira](skills/integrations/jira/) | integrations | Read and write Jira (Cloud or Server / Data Center) from chat — JQL search, fetch / create / update / delete issues, apply transitions, add comments and attachments, list projects and users. Auto-handles Cloud (REST v3, basic auth, ADF, nextPageToken) vs Server (REST v2, bearer PAT, plain text, startAt). Exports as JSON, JSONL, or CSV. The agent never sees your API token. | pip (see `requirements.txt`) |
| [jira-align](skills/integrations/jira-align/) | integrations | Read and write Jira Align (Cloud or self-hosted) from chat — fetch, filter, and export epics, features, stories, teams, and more; create and update records; delete with confirmation. Exports as JSON, JSONL, or CSV. The agent never sees your API token. | pip (see `requirements.txt`) |

---

## Installing a skill into your IDE

Each skill is a plain directory. Installation is always the same two steps: **(1) copy the skill folder into your IDE's skills location**, then **(2) install the skill's dependencies** (the commands are in `manifest.json` under `deps`).

### Claude Code

Claude Code reads skills from two locations:

- **User-scope** (available in every project): `~/.claude/skills/<skill-name>/`
- **Project-scope** (tracked with the repo): `<project>/.claude/skills/<skill-name>/`

Install a skill by copying its folder — drop the directory directly into the skills location, not its parent category folder:

```bash
# user-scope (recommended)
mkdir -p ~/.claude/skills
cp -R skills/converters/file-to-markdown ~/.claude/skills/

# project-scope
mkdir -p .claude/skills
cp -R skills/converters/file-to-markdown .claude/skills/
```

Claude Code discovers the skill via its `SKILL.md` frontmatter `name` field. Invoke it in chat with `/<skill-name>` or by describing the task — Claude will route to the matching skill automatically.

### Cursor

Cursor does not have a native "skills" concept, but you can install a skill as a project rule:

1. Copy the skill folder somewhere in the repo (e.g. `.cursor/skills/<skill-name>/`).
2. Create `.cursor/rules/<skill-name>.mdc` that references `SKILL.md`:

   ```
   ---
   description: <paste the skill's description from manifest.json>
   globs:
   alwaysApply: false
   ---
   Follow the instructions in .cursor/skills/<skill-name>/SKILL.md when the user requests this task.
   ```

3. In chat, attach `SKILL.md` with `@` or invoke the rule by describing the task.

### Kiro

Kiro supports agent instructions via steering files and custom agents:

1. Copy the skill folder to `.kiro/skills/<skill-name>/`.
2. Add a steering file at `.kiro/steering/<skill-name>.md` that points Kiro to the skill's `SKILL.md` when the matching task is requested.

Alternatively, paste the contents of `SKILL.md` into a custom Kiro agent definition.

### Other IDEs (Continue, Cline, Aider, etc.)

These tools don't have a standard skills directory. Use one of these patterns:

- **Context attachment**: copy the skill folder anywhere in the repo, then attach `SKILL.md` to your prompt and ask the agent to follow it.
- **Custom prompt/agent**: paste `SKILL.md` into the IDE's custom-agent or system-prompt configuration.

In all cases, the scripts are invoked from the copied folder, so keep the directory structure intact.

### Installing dependencies

Each skill declares its deps in `manifest.json`:

- `deps.npm` — run `npm install <packages>` before using the skill (or let `SKILL.md` Step 1 install them on demand).
- `deps.pip` — run `python -m pip install -r <skill>/requirements.txt`.

Most skills' `SKILL.md` includes a verify-and-install step so dependencies are handled on first use.

---

## Skill usage

All skills are invoked in chat. Arguments are passed as plain text after the skill's trigger phrase (or via `$ARGUMENTS` when invoked as a slash command in Claude Code).

### api-contract

Generate an OpenAPI 3.1 contract.

- **Input**: natural language description, or a path to source code / SQL that describes the API surface.
- **Output**: `.yaml` or `.json` OpenAPI document.
- **Example prompt**: *"Generate an OpenAPI contract for a users CRUD API with pagination and idempotent POST."*

### file-to-markdown

Convert documents and images to Markdown. One skill covers PDF, DOCX, PPTX, XLSX, XLS, and the image formats (PNG, JPG, JPEG, TIFF, BMP, WEBP, GIF).

- **Install deps**: `python -m pip install docling Pillow` (first Docling run downloads ML models, ~1–2 min; subsequent runs are fast)
- **Example prompts**:
  - *"Convert docs/whitepaper.pdf to Markdown."*
  - *"Convert decks/q2-review.pptx to Markdown."*
  - *"Convert data/sales.xlsx to Markdown tables, one per sheet."*
  - *"Convert architecture-diagram.png to Markdown — it's an event-storming board, extract the sticky notes."*

Documents go through Docling text extraction (`scripts/convert.py`). Images go through a two-pass sliding-window vision pipeline (`scripts/split_image.py`) that tiles the source with overlap so no element is bisected at a tile boundary.

### markdown-to-html

Convert a Markdown file to styled HTML.

- **Install deps**: `npm install marked highlight.js`
- **Example prompt**: *"Render notes/weekly.md as a self-contained HTML page with TOC."*

### msg-to-markdown

Convert an Outlook `.msg` email to Markdown.

- **Install deps**: `npm install @nicecode/msg-reader`
- **Example prompt**: *"Convert inbox/2026-03-customer-escalation.msg to Markdown."*

### confluence-crawler

Crawl an authenticated Confluence space and write each page as Markdown with YAML frontmatter. Supports Atlassian Cloud and on-prem Server/Data Center.

- **Install deps**: `python -m pip install -r skills/crawlers/confluence-crawler/requirements.txt`
- **Get an access token** (required before running setup):

  - **Atlassian Cloud** — go to https://id.atlassian.com/manage-profile/security/api-tokens, click **Create API token**, name it, and copy the value. Authentication uses your Atlassian account email plus this token.
  - **Server / Data Center (on-prem)** — in Confluence, click your avatar → **Profile** → **Personal Access Tokens** → **Create token**. Name the token, set an expiry, click **Create**, and copy the value shown (it is only displayed once). Authentication uses the token as a bearer credential; no email is required.

- **One-time setup** (interactive — prompts for base URL, email if Cloud, and the token from the step above; writes `~/.config/confluence-crawler/config.env` at mode 0600):

  ```bash
  bash skills/crawlers/confluence-crawler/scripts/setup_credentials.sh
  ```

- **Verify connectivity**:

  ```bash
  python skills/crawlers/confluence-crawler/scripts/crawl_space.py --check
  ```

- **Example prompts**:
  - *"Crawl the ENG space to ./out at depth 3."*
  - *"Re-crawl ENG, forcing a refresh of every page."* (uses `--force`)

Flags: `--space KEY` (required), `--root PAGE_ID`, `--depth N`, `--output DIR`, `--force`, `--no-attachments`, `--concurrency N`, `--insecure`, `--check`, `--verbose`. The API token is never accepted on the command line.

### jira

Talk to Jira (the issue tracker, **not** Jira Align — those are separate skills) from chat. Ask for issues by key or JQL, create and update issues, transition workflow states, comment, attach files, and list projects or users. Works against Atlassian Cloud (REST v3) and self-hosted Server / Data Center (REST v2); the skill handles the auth, API version, ADF wrapping, and pagination differences automatically.

- **Install deps**: `python -m pip install -r skills/integrations/jira/requirements.txt`
- **Get an access token**:

  - **Atlassian Cloud** — go to https://id.atlassian.com/manage-profile/security/api-tokens, click **Create API token**, name it, and copy the value. Authentication uses your Atlassian account email plus this token (Basic auth).
  - **Server / Data Center (on-prem)** — in Jira, click your avatar → **Profile** → **Personal Access Tokens** → **Create token**. Name the token, set an expiry, click **Create**, and copy the value shown (it is only displayed once). Authentication uses the token as a bearer credential; no email is required.

- **One-time setup** (interactive — prompts for base URL, email if Cloud, and the token; writes `~/.config/dropkit/credentials.env` at mode 0600, merged with any existing dropkit credentials):

  ```bash
  bash skills/integrations/jira/scripts/setup_credentials.sh
  ```

- **Verify connectivity**:

  ```bash
  python skills/integrations/jira/scripts/jira.py check
  ```

- **Example prompts**:
  - *"Show me the 50 most recently created bugs in PROJ — just summary, status, priority, created."*
  - *"Fetch PROJ-123 with renderedFields and changelog expanded."*
  - *"Export every issue assigned to me to issues.jsonl."*
  - *"Create a Task in PROJ titled 'Onboarding revamp' with this description …"*
  - *"Move PROJ-123 to In Progress and add the labels urgent and onboarding."*
  - *"Add a comment to PROJ-123 saying 'Pushed the fix in #4567.' and attach screenshot.png."*

- **What the skill can do**:

  | Action | Example |
  |---|---|
  | Fetch one issue | `get-issue PROJ-123 --fields summary,status` |
  | JQL search | `search "project = PROJ AND status = 'In Progress'" --limit 50` |
  | Create an issue | `create-issue --field 'project={"key":"PROJ"}' --field summary="..." --field 'issuetype={"name":"Task"}'` |
  | Update an issue (PUT, partial) | `update-issue PROJ-123 --field 'labels=["urgent"]'` |
  | Delete an issue | `delete-issue PROJ-123 --yes` |
  | Apply a transition | `transition PROJ-123 --to "In Progress"` |
  | Add a comment | `comment PROJ-123 --body "text"` |
  | Upload an attachment | `attach PROJ-123 --file ./screenshot.png` |
  | List projects | `list-projects --query KW` |
  | Find a user | `list-users --query ada@example.com` |
  | Anything else | `raw GET issue/PROJ-123/worklog` |

  Output format is selectable with `--format json|jsonl|csv`, and `--output FILE` writes to disk instead of stdout. For create and update, `--field KEY=VALUE` values are JSON-parsed, so `--field 'labels=["a","b"]'` sends an array, `--field 'project={"key":"PROJ"}'` sends an object, and anything that fails to parse is sent as a string.

- **Safety**: the API token is never accepted on the command line, `delete-issue` refuses to run without `--yes`, status changes go through `transition` (Jira ignores `status` in `update-issue` by design), and the agent is instructed to confirm any create/update/delete/transition before executing it.

### jira-align

Talk to Jira Align from chat. Ask for records, filter collections, or make changes, and the skill dispatches the right REST API call for you. Works against Atlassian Cloud and self-hosted instances.

- **Install deps**: `python -m pip install -r skills/integrations/jira-align/requirements.txt`
- **Get an access token** (required before running setup; same flow for both flavors):

  1. Sign in to your Jira Align instance (Cloud at `https://<site>.jiraalign.com`, or your self-hosted URL).
  2. Click your avatar in the top navigation bar → **Profile**.
  3. On the Profile page, find the **API Token** section and click **Generate** (or **Regenerate** if one already exists).
  4. Copy the token value — it is only shown once. Tokens do not expire by time; they remain valid until regenerated or until the user is deactivated.

  If you are on self-hosted and the API Token section is missing, ask an administrator: some on-prem installs require `EnableApiTokens` to be turned on in the system configuration before users can generate tokens.

- **One-time setup** (interactive — prompts for base URL and the token; writes `~/.config/dropkit/credentials.env` at mode 0600, merged with any existing dropkit credentials):

  ```bash
  bash skills/integrations/jira-align/scripts/setup_credentials.sh
  ```

- **Verify connectivity**:

  ```bash
  python skills/integrations/jira-align/scripts/jira_align.py check
  ```

- **Example prompts**:
  - *"Show me the 20 most recently modified in-progress features in program 42."*
  - *"Fetch epic 1001 with the owner and milestones expanded."*
  - *"Export every team to `teams.jsonl`."*
  - *"Create a new feature titled 'Onboarding revamp' in program 42 owned by user 77 at 8 points."*
  - *"Change feature 789's state to In Progress and set points to 13."*

- **What the skill can do**:

  | Action | Example |
  |---|---|
  | Fetch one record | `get epics 1001` |
  | List / filter a collection | `list features --filter "state eq 'In Progress'" --limit 20` |
  | Search shortcut | `search stories "title contains 'login'"` |
  | Create a record | `create features --field title="Onboarding revamp" --field points=8` |
  | Update a record | `update features 789 --method PATCH --field state="In Progress"` |
  | Delete a record | `delete stories 5432 --yes` |
  | Anything else | `raw GET features/789/stories` |

  Output format is selectable with `--format json|jsonl|csv`, and `--output FILE` writes to disk instead of stdout. For create and update, `--field KEY=VALUE` values are JSON-parsed, so `--field points=8` sends an integer, `--field isActive=true` sends a boolean, and anything that fails to parse is sent as a string.

- **Safety**: the API token is never accepted on the command line, `delete` refuses to run without `--yes`, and the agent is instructed to confirm any create/update/delete before executing it.

---

## Shared credential file

Skills that call authenticated third-party APIs read their secrets from a shared file at `~/.config/dropkit/credentials.env` (mode 0600). Each skill namespaces its keys (e.g. `JIRAALIGN_*` for jira-align). Re-running any skill's `setup_credentials.sh` only rewrites that skill's own keys — other skills' entries are preserved. The legacy per-skill path `~/.config/confluence-crawler/config.env` is still read for backward compatibility.

Environment variables of the same name always take precedence over the file, which makes CI use straightforward: set the vars in the job and skip the setup script entirely.

---

## Repository layout

```
dropkit/
  skills/
    <category>/
      <skill-name>/
        manifest.json     # metadata + deps + I/O
        SKILL.md          # agent playbook
        scripts/          # executable logic
        requirements.txt  # (when pip-based)
        evals/            # expected-behavior tests
```

---

## Contributing

To add a new skill:

1. **Pick a category.** Reuse one of the existing folders under `skills/` (`contracts`, `converters`, `crawlers`, `integrations`) or create a new one if nothing fits.
2. **Create the skill folder** at `skills/<category>/<skill-name>/`.
3. **Write `manifest.json`.** Match the shape of existing skills — `id`, `name`, `version`, `description`, `category`, `tags`, `deps`, `input`, `output`, and `targets`.
4. **Write `SKILL.md`.** Keep it thin: describe *when* to use the skill and *how* to dispatch to its scripts. Don't reimplement logic in prose.
5. **Put the real work in `scripts/`.** The agent should call into scripts, not duplicate them.
6. **Declare dependencies.** Use `deps.pip` (plus a `requirements.txt`) or `deps.npm` in the manifest.
7. **Add evals.** Drop an `evals/evals.json` that documents prompts, expected behavior, and assertions (see existing skills for the format).
8. **Update the catalog** row and usage section in this README.
