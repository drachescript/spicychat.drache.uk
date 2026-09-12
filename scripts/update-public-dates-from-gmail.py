#!/usr/bin/env python3
"""Update SpicyChat public dates from Gmail using the Gmail API.

This is the unattended counterpart to tools/scan_gmail_public_dates.py.
It deliberately reuses that scanner's matching and safe-date evaluation rules:
- exact character-name matching
- ambiguous names are never auto-applied
- existing confirmed dates are never overwritten
- approvals before a later non-public observation are rejected
- approvals after the first public observation are treated as later re-reviews

Required environment variables:
  GMAIL_CLIENT_ID
  GMAIL_CLIENT_SECRET
  GMAIL_REFRESH_TOKEN
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scan_gmail_public_dates import (  # noqa: E402
    apply_updates,
    dedupe_approvals,
    evaluate,
    extract_message_approval,
    load_json,
)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_QUERY = 'from:support@spicychat.ai subject:"Your character is live"'


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def gmail_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Missing Gmail API packages. Install scripts/requirements-gmail-public-dates.txt"
        ) from exc

    creds = Credentials(
        token=None,
        refresh_token=require_env("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=require_env("GMAIL_CLIENT_ID"),
        client_secret=require_env("GMAIL_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def list_matching_message_ids(service) -> list[str]:
    ids: list[str] = []
    page_token = None
    while True:
        kwargs = {
            "userId": "me",
            "q": GMAIL_QUERY,
            "maxResults": 100,
        }
        if page_token:
            kwargs["pageToken"] = page_token
        result = service.users().messages().list(**kwargs).execute()
        ids.extend(str(item["id"]) for item in result.get("messages", []) if item.get("id"))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return ids


def fetch_approvals(service, message_ids: list[str]):
    approvals = []
    failures: list[tuple[str, str]] = []
    for message_id in message_ids:
        try:
            item = service.users().messages().get(userId="me", id=message_id, format="raw").execute()
            raw = item.get("raw")
            if not raw:
                failures.append((message_id, "message had no raw MIME payload"))
                continue
            padded = raw + "=" * (-len(raw) % 4)
            data = base64.urlsafe_b64decode(padded.encode("ascii"))
            message = BytesParser(policy=policy.default).parsebytes(data)
            approvals.extend(
                extract_message_approval(message, Path(f"gmail-api-{message_id}.eml"), "gmail-api")
            )
        except Exception as exc:
            failures.append((message_id, str(exc)))
    return dedupe_approvals(approvals), failures


def atomic_write_json(path: Path, data: dict) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(temp, path)


def summary_counts(report) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in report:
        counts[row.status] = counts.get(row.status, 0) + 1
    return counts


def write_summary(path: Path | None, approvals, report, updates, failures, applied: int) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = summary_counts(report)
    lines = [
        "## Gmail public-date scan",
        "",
        f"- Matching approval emails parsed: **{len(approvals)}**",
        f"- Safe updates found: **{len(updates)}**",
        f"- Updates applied: **{applied}**",
        f"- Gmail messages that failed to parse: **{len(failures)}**",
    ]
    if counts:
        lines += ["", "### Results"]
        for key in sorted(counts):
            lines.append(f"- `{key}`: {counts[key]}")
    if updates:
        lines += ["", "### Applied candidates"]
        for record, approval in updates:
            lines.append(f"- {record.get('name', approval.character_name)} → `{approval.iso}`")
    if failures:
        lines += ["", "### Parse failures"]
        for message_id, error in failures[:20]:
            lines.append(f"- `{message_id}`: {error}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Safely apply SpicyChat approval dates from Gmail API.")
    parser.add_argument("--repo", default=str(ROOT), help="Repository root")
    parser.add_argument("--scan-only", action="store_true", help="Report only; do not modify bot-public.json")
    parser.add_argument("--summary-file", help="Write a Markdown GitHub Actions summary file")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo).expanduser().resolve()
    bots_path = root / "assets" / "data" / "bots.json"
    public_path = root / "assets" / "data" / "bot-public.json"
    summary_path = Path(args.summary_file) if args.summary_file else None

    if not bots_path.is_file() or not public_path.is_file():
        print("Could not find assets/data/bots.json and assets/data/bot-public.json")
        return 2

    try:
        service = gmail_service()
        message_ids = list_matching_message_ids(service)
        approvals, failures = fetch_approvals(service, message_ids)
    except Exception as exc:
        print(f"Gmail API error: {exc}")
        write_summary(summary_path, [], [], [], [], 0)
        return 3

    print(f"Gmail matches : {len(message_ids)}")
    print(f"Approvals     : {len(approvals)}")
    if failures:
        print(f"Parse failures: {len(failures)}")

    bots_data = load_json(bots_path)
    public_data = load_json(public_path)
    report, safe_updates = evaluate(approvals, bots_data, public_data)

    counts = summary_counts(report)
    print(f"Safe updates  : {len(safe_updates)}")
    for key in sorted(counts):
        print(f"  {key:34} {counts[key]}")

    applied = 0
    if safe_updates and not args.scan_only:
        applied = apply_updates(public_data, safe_updates)
        atomic_write_json(public_path, public_data)
        print(f"Applied       : {applied}")
    elif args.scan_only:
        print("Scan-only mode: no JSON changes written.")
    else:
        print("Nothing safe to update automatically.")

    write_summary(summary_path, approvals, report, safe_updates, failures, applied)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
