#!/usr/bin/env python3
"""Jira REST API CLI (Cloud v3 + Data Center v2).

Subcommands:
    check                          Verify credentials and reachability.
    whoami                         Print the authenticated user record.
    get ISSUE_KEY                  Fetch a single issue (e.g. ``get PROJ-123``).
    search JQL                     Search issues with JQL, paginated.
    list-projects                  List accessible projects.
    list-transitions ISSUE_KEY     Show available workflow transitions.
    list-fields                    List all fields (useful for custom field names).
    create PROJECT_KEY ISSUE_TYPE  Create an issue with --field / --data-file.
    update ISSUE_KEY               Update fields on an existing issue.
    transition ISSUE_KEY STATUS    Move issue through its workflow.
    comment ISSUE_KEY TEXT         Add a comment to an issue.
    add-subtask PARENT_KEY SUMMARY Create a sub-task under a parent issue.
    export JQL                     Bulk export matching issues.
    raw METHOD PATH                Arbitrary API call for anything not wrapped.

The Jira API token is never accepted on the command line.  It is read only
from the shared jira credential file or environment.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _client import (  # noqa: E402
    AuthError,
    JiraClient,
    JiraError,
    load_credentials,
    FLAVOR_CLOUD,
)

log = logging.getLogger("jira.cli")

EXIT_OK = 0
EXIT_USER_ERROR = 1
EXIT_AUTH_ERROR = 2
EXIT_SERVER_ERROR = 3

TOKEN_CLI_FLAGS = frozenset({
    "--token", "--api-token", "--bearer", "-t",
    "--jira-token", "--jira-api-token", "--password",
})


def _reject_token_on_cli(argv: list[str]) -> None:
    for arg in argv:
        head = arg.split("=", 1)[0]
        if head in TOKEN_CLI_FLAGS:
            sys.stderr.write(
                "error: API tokens must not be passed on the command line.  "
                "Run scripts/setup_credentials.sh or export JIRA_API_TOKEN.\n"
            )
            sys.exit(EXIT_USER_ERROR)


# ---- Argument parser --------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jira.py",
        description="Query Jira REST API (Cloud v3 / Data Center v2).",
    )
    p.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    p.add_argument(
        "--insecure", action="store_true",
        help="Disable TLS verification.  Only if the user explicitly asks.",
    )
    p.add_argument(
        "--format", choices=("json", "jsonl", "csv"), default="json",
        help="Output format (default: json).",
    )
    p.add_argument(
        "--output", type=Path, default=None,
        help="Write output to this file instead of stdout.",
    )

    sub = p.add_subparsers(dest="command", required=True)

    # -- check / whoami -------------------------------------------------------
    sub.add_parser("check", help="Verify credentials and reachability.")
    sub.add_parser("whoami", help="Show the authenticated user record.")

    # -- get ------------------------------------------------------------------
    g = sub.add_parser("get", help="Fetch a single issue by key.")
    g.add_argument("issue_key", help="Issue key, e.g. PROJ-123.")
    g.add_argument("--fields", default=None, help="Comma-separated field list.")
    g.add_argument("--expand", default=None, help="Comma-separated expand list.")

    # -- search ---------------------------------------------------------------
    s = sub.add_parser("search", help="Search issues with JQL.")
    s.add_argument("jql", help="JQL query string.")
    s.add_argument("--fields", default=None, help="Comma-separated field list.")
    s.add_argument("--expand", default=None, help="Comma-separated expand list.")
    s.add_argument("--limit", type=int, default=None, help="Max issues to return.")
    s.add_argument("--page-size", type=int, default=50, help="Issues per request.")

    # -- list-projects --------------------------------------------------------
    sub.add_parser("list-projects", help="List accessible projects.")

    # -- list-transitions -----------------------------------------------------
    lt = sub.add_parser("list-transitions", help="Show available transitions.")
    lt.add_argument("issue_key", help="Issue key.")

    # -- list-fields ----------------------------------------------------------
    sub.add_parser("list-fields", help="List all fields (system + custom).")

    # -- create ---------------------------------------------------------------
    cr = sub.add_parser("create", help="Create an issue.")
    cr.add_argument("project_key", help="Project key, e.g. ACME.")
    cr.add_argument("issue_type", help="Issue type: Story, Task, Bug, Epic, Sub-task.")
    _add_body_flags(cr)

    # -- update ---------------------------------------------------------------
    up = sub.add_parser("update", help="Update fields on an existing issue.")
    up.add_argument("issue_key", help="Issue key.")
    _add_body_flags(up)

    # -- transition -----------------------------------------------------------
    tr = sub.add_parser("transition", help="Transition an issue to a new status.")
    tr.add_argument("issue_key", help="Issue key.")
    tr.add_argument("status", help="Target status name (e.g. 'In Progress', 'Done').")

    # -- comment --------------------------------------------------------------
    cm = sub.add_parser("comment", help="Add a comment to an issue.")
    cm.add_argument("issue_key", help="Issue key.")
    cm.add_argument("text", help="Comment text.")

    # -- add-subtask ----------------------------------------------------------
    st = sub.add_parser("add-subtask", help="Create a sub-task under a parent.")
    st.add_argument("parent_key", help="Parent issue key.")
    st.add_argument("summary", help="Sub-task summary.")
    _add_body_flags(st)

    # -- export ---------------------------------------------------------------
    ex = sub.add_parser("export", help="Bulk export issues matching a JQL query.")
    ex.add_argument("jql", help="JQL query string.")
    ex.add_argument("--fields", default=None, help="Comma-separated field list.")
    ex.add_argument("--limit", type=int, default=None, help="Max issues.")
    ex.add_argument("--page-size", type=int, default=50, help="Issues per request.")

    # -- raw ------------------------------------------------------------------
    rw = sub.add_parser("raw", help="Issue an arbitrary API request.")
    rw.add_argument(
        "method", choices=("GET", "POST", "PUT", "PATCH", "DELETE"),
        help="HTTP method.",
    )
    rw.add_argument("path", help="API path (absolute or relative to API prefix).")
    rw.add_argument(
        "--param", action="append", default=[], metavar="KEY=VALUE",
        help="Query parameter (repeatable).",
    )
    rw.add_argument(
        "--data-file", type=Path, default=None,
        help="JSON file to send as the request body.",
    )

    return p


def _add_body_flags(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "--data-file", type=Path, default=None,
        help="Path to a JSON file containing the fields payload.",
    )
    sub.add_argument(
        "--field", action="append", default=[], metavar="KEY=VALUE",
        help=(
            "Field to set (repeatable).  VALUE is parsed as JSON if possible, "
            "otherwise sent as a string.  Merges over --data-file."
        ),
    )


def _parse_field_pairs(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--field {pair!r} must be KEY=VALUE")
        k, v = pair.split("=", 1)
        if not k:
            raise ValueError(f"--field {pair!r} has an empty key")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def _load_fields(args: argparse.Namespace) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    if getattr(args, "data_file", None) is not None:
        raw = json.loads(args.data_file.read_text("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("--data-file must contain a JSON object")
        fields.update(raw)
    fields.update(_parse_field_pairs(args.field))
    return fields


# ---- ADF helpers (Cloud v3 uses Atlassian Document Format) ------------------

def _text_to_adf(text: str) -> dict:
    """Wrap plain text in a minimal ADF document for Cloud v3."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _make_comment_body(text: str, flavor: str) -> Any:
    """Cloud v3 expects ADF; Data Center v2 expects a plain string."""
    if flavor == FLAVOR_CLOUD:
        return _text_to_adf(text)
    return text


def _make_description(text: str, flavor: str) -> Any:
    if flavor == FLAVOR_CLOUD:
        return _text_to_adf(text)
    return text


# ---- Subcommand handlers ----------------------------------------------------

async def _cmd_check(client: JiraClient) -> int:
    try:
        info = await client.whoami()
    except AuthError as exc:
        print(f"auth failed: {exc}", file=sys.stderr)
        return EXIT_AUTH_ERROR
    except JiraError as exc:
        print(f"server error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR
    display = info.get("displayName") or info.get("name") or "?"
    email = info.get("emailAddress") or ""
    print(f"ok: connected to {client.base_url} as {display} {email}".rstrip())
    return EXIT_OK


async def _cmd_whoami(client: JiraClient, writer: "OutputWriter") -> int:
    info = await client.whoami()
    writer.emit_single(info)
    return EXIT_OK


async def _cmd_get(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    issue = await client.get_issue(
        args.issue_key, fields=args.fields, expand=args.expand
    )
    writer.emit_single(issue)
    return EXIT_OK


async def _cmd_search(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    async for issue in client.iter_search(
        args.jql,
        fields=args.fields,
        expand=args.expand,
        page_size=args.page_size,
        limit=args.limit,
    ):
        writer.emit_record(issue)
    writer.finish()
    return EXIT_OK


async def _cmd_list_projects(
    client: JiraClient, writer: "OutputWriter"
) -> int:
    projects = await client.list_projects()
    for p in projects:
        writer.emit_record(p)
    writer.finish()
    return EXIT_OK


async def _cmd_list_transitions(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    transitions = await client.get_transitions(args.issue_key)
    for t in transitions:
        writer.emit_record(t)
    writer.finish()
    return EXIT_OK


async def _cmd_list_fields(
    client: JiraClient, writer: "OutputWriter"
) -> int:
    fields = await client.list_fields()
    for f in fields:
        writer.emit_record(f)
    writer.finish()
    return EXIT_OK


async def _cmd_create(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    user_fields = _load_fields(args)
    if not user_fields and not getattr(args, "data_file", None):
        print(
            "error: no fields provided — pass --field or --data-file",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    # Build the Jira create payload.
    fields_payload: dict[str, Any] = {
        "project": {"key": args.project_key},
        "issuetype": {"name": args.issue_type},
    }

    # Map flat --field keys to Jira's nested structure where needed.
    for k, v in user_fields.items():
        if k == "description" and isinstance(v, str):
            fields_payload[k] = _make_description(v, client.flavor)
        else:
            fields_payload[k] = v

    body: dict[str, Any] = {"fields": fields_payload}
    result = await client.create_issue(body)
    writer.emit_single(result)
    return EXIT_OK


async def _cmd_update(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    user_fields = _load_fields(args)
    if not user_fields:
        print(
            "error: no fields provided — pass --field or --data-file",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    update_payload: dict[str, Any] = {}
    for k, v in user_fields.items():
        if k == "description" and isinstance(v, str):
            update_payload[k] = _make_description(v, client.flavor)
        else:
            update_payload[k] = v

    await client.update_issue(args.issue_key, {"fields": update_payload})
    print(f"ok: updated {args.issue_key}", file=sys.stderr)
    # Fetch the updated issue to show the result.
    issue = await client.get_issue(args.issue_key)
    writer.emit_single(issue)
    return EXIT_OK


async def _cmd_transition(
    client: JiraClient, args: argparse.Namespace
) -> int:
    transitions = await client.get_transitions(args.issue_key)
    target = args.status.strip().lower()

    match = None
    for t in transitions:
        if t.get("name", "").strip().lower() == target:
            match = t
            break

    if match is None:
        available = ", ".join(
            f"\"{t.get('name')}\" (id {t.get('id')})" for t in transitions
        )
        print(
            f"error: status \"{args.status}\" is not available for "
            f"{args.issue_key}.  Available transitions: {available}",
            file=sys.stderr,
        )
        return EXIT_USER_ERROR

    await client.transition_issue(args.issue_key, match["id"])
    print(
        f"ok: transitioned {args.issue_key} → {match['name']}",
        file=sys.stderr,
    )
    return EXIT_OK


async def _cmd_comment(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    body = _make_comment_body(args.text, client.flavor)
    result = await client.add_comment(args.issue_key, body)
    writer.emit_single(result)
    return EXIT_OK


async def _cmd_add_subtask(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    extra_fields = _load_fields(args)

    fields_payload: dict[str, Any] = {
        "parent": {"key": args.parent_key},
        "issuetype": {"name": "Sub-task"},
        "summary": args.summary,
    }

    # Inherit the parent's project.
    parent = await client.get_issue(args.parent_key, fields="project")
    project_key = parent.get("fields", {}).get("project", {}).get("key")
    if project_key:
        fields_payload["project"] = {"key": project_key}

    for k, v in extra_fields.items():
        if k == "description" and isinstance(v, str):
            fields_payload[k] = _make_description(v, client.flavor)
        else:
            fields_payload[k] = v

    result = await client.create_issue({"fields": fields_payload})
    writer.emit_single(result)
    return EXIT_OK


async def _cmd_export(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    async for issue in client.iter_search(
        args.jql,
        fields=args.fields,
        page_size=args.page_size,
        limit=args.limit,
    ):
        writer.emit_record(issue)
    writer.finish()
    return EXIT_OK


async def _cmd_raw(
    client: JiraClient, args: argparse.Namespace, writer: "OutputWriter"
) -> int:
    params: dict[str, str] = {}
    for pair in args.param:
        if "=" not in pair:
            print(f"error: --param {pair!r} must be KEY=VALUE", file=sys.stderr)
            return EXIT_USER_ERROR
        k, v = pair.split("=", 1)
        params[k] = v
    body: Any = None
    if args.data_file is not None:
        body = json.loads(args.data_file.read_text("utf-8"))
    result = await client.raw(
        args.method, args.path, params=params or None, json_body=body
    )
    if isinstance(result, list):
        for item in result:
            writer.emit_record(item if isinstance(item, dict) else {"value": item})
        writer.finish()
    elif isinstance(result, dict):
        writer.emit_single(result)
    elif result is None:
        print("(no content)", file=sys.stderr)
    else:
        writer.emit_single({"value": result})
    return EXIT_OK


# ---- Output writer ----------------------------------------------------------

class OutputWriter:
    """Streams records in json / jsonl / csv."""

    def __init__(self, fmt: str, output: Path | None) -> None:
        self._fmt = fmt
        self._path = output
        self._fh = (
            output.open("w", encoding="utf-8", newline="") if output else sys.stdout
        )
        self._close = output is not None
        self._buffer: list[dict] = []
        self._csv_writer: csv.DictWriter | None = None

    def emit_single(self, record: dict) -> None:
        if self._fmt == "json":
            json.dump(record, self._fh, indent=2, default=str)
            self._fh.write("\n")
        elif self._fmt == "jsonl":
            self._fh.write(json.dumps(record, default=str) + "\n")
        elif self._fmt == "csv":
            self._write_csv_row(record)

    def emit_record(self, record: dict) -> None:
        if self._fmt == "json":
            self._buffer.append(record)
        elif self._fmt == "jsonl":
            self._fh.write(json.dumps(record, default=str) + "\n")
        elif self._fmt == "csv":
            self._write_csv_row(record)

    def finish(self) -> None:
        if self._fmt == "json" and self._buffer:
            json.dump(self._buffer, self._fh, indent=2, default=str)
            self._fh.write("\n")

    def _write_csv_row(self, record: dict) -> None:
        if self._csv_writer is None:
            self._csv_writer = csv.DictWriter(
                self._fh,
                fieldnames=list(record.keys()),
                extrasaction="ignore",
                quoting=csv.QUOTE_MINIMAL,
            )
            self._csv_writer.writeheader()
        self._csv_writer.writerow(
            {k: _csv_scalar(v) for k, v in record.items()}
        )

    def close(self) -> None:
        if self._close:
            self._fh.close()


def _csv_scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, default=str)


# ---- Dispatch ---------------------------------------------------------------

async def _run(args: argparse.Namespace) -> int:
    try:
        credentials = load_credentials()
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_AUTH_ERROR

    writer = OutputWriter(args.format, args.output)
    try:
        async with JiraClient(
            credentials, verify_tls=not args.insecure
        ) as client:
            cmd = args.command
            if cmd == "check":
                return await _cmd_check(client)
            if cmd == "whoami":
                return await _cmd_whoami(client, writer)
            if cmd == "get":
                return await _cmd_get(client, args, writer)
            if cmd == "search":
                return await _cmd_search(client, args, writer)
            if cmd == "list-projects":
                return await _cmd_list_projects(client, writer)
            if cmd == "list-transitions":
                return await _cmd_list_transitions(client, args, writer)
            if cmd == "list-fields":
                return await _cmd_list_fields(client, writer)
            if cmd == "create":
                return await _cmd_create(client, args, writer)
            if cmd == "update":
                return await _cmd_update(client, args, writer)
            if cmd == "transition":
                return await _cmd_transition(client, args)
            if cmd == "comment":
                return await _cmd_comment(client, args, writer)
            if cmd == "add-subtask":
                return await _cmd_add_subtask(client, args, writer)
            if cmd == "export":
                return await _cmd_export(client, args, writer)
            if cmd == "raw":
                return await _cmd_raw(client, args, writer)
            print(f"error: unknown command {cmd!r}", file=sys.stderr)
            return EXIT_USER_ERROR
    except AuthError as exc:
        print(f"auth error: {exc}", file=sys.stderr)
        return EXIT_AUTH_ERROR
    except JiraError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_SERVER_ERROR
    finally:
        writer.close()


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _reject_token_on_cli(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
