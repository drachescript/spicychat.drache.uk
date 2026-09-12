#!/usr/bin/env python3
"""
SpicyChat Gmail Public-Date Scanner

Reads saved Gmail HTML/HTM pages (and optionally .eml/.mbox files), extracts
SpicyChat "Your character is live" approvals, matches them to the site's
assets/data/bots.json + assets/data/bot-public.json, and safely upgrades
first-observed public dates to confirmed approval-email dates.

Default behaviour:
- Scan and write CSV/JSON reports.
- Ask before changing bot-public.json.
- Never overwrite an already-confirmed public date.
- Never use an approval that happened before a later known non-public
  observation, or after the first observed public state.
- Back up bot-public.json before any write.

No third-party Python packages are required.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import mailbox
import os
import re
import shutil
import sys
import unicodedata
from dataclasses import dataclass, asdict
from datetime import datetime
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Optional


LIVE_TEXT_RE = re.compile(
    r"Great news\s*[—–-]\s*your character\s+(.+?)\s+"
    r"has been approved and is now live on SpicyChat",
    re.IGNORECASE | re.DOTALL,
)

ROW_RE = re.compile(
    r"""(?is)<tr\b[^>]*\brole=["']row["'][^>]*>.*?</tr>"""
)

TAG_RE = re.compile(r"(?is)<[^>]+>")
SPACE_RE = re.compile(r"\s+")
THREAD_COUNT_RE = re.compile(
    r"""(?is)<span\b[^>]*class=["'][^"']*\bbx0\b[^"']*["'][^>]*>\s*(\d+)\s*</span>"""
)
TITLE_ATTR_RE = re.compile(r"""(?is)\btitle=["']([^"']+)["']""")
SENDER_RE = re.compile(r"support@spicychat\.ai", re.IGNORECASE)
SUBJECT_RE = re.compile(r"Your character is live", re.IGNORECASE)

SUPPORTED_SUFFIXES = {".html", ".htm", ".eml", ".mbox"}

PUBLIC_NOTE = (
    "Public time confirmed from the SpicyChat approval email. "
    "The message baseline is the first saved stats point after approval, "
    "so the since-public message gain is a minimum."
)


@dataclass(frozen=True)
class Approval:
    character_name: str
    approved_at: datetime
    source_file: str
    source_kind: str
    thread_count: Optional[int] = None

    @property
    def iso(self) -> str:
        return self.approved_at.isoformat(timespec="seconds")


@dataclass
class ReportRow:
    character_name: str
    email_approved_at: str
    source_file: str
    source_kind: str
    thread_count: str
    bot_id: str
    matched_site_name: str
    current_public_since: str
    previous_non_public_observed_at: str
    first_public_observed_at: str
    status: str
    reason: str


def clean_html(fragment: str) -> str:
    text = TAG_RE.sub(" ", fragment)
    text = html.unescape(text)
    return SPACE_RE.sub(" ", text).strip()


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "")
    value = value.casefold().strip()
    value = value.replace("’", "'").replace("“", '"').replace("”", '"')
    return SPACE_RE.sub(" ", value)


def soft_name(value: str) -> str:
    value = normalize_name(value)
    return re.sub(r"[^a-z0-9]+", "", value)


def parse_gmail_title_date(value: str) -> Optional[datetime]:
    """
    Gmail saved HTML uses values like:
      Thu, 27 Aug 2026, 05:32

    The page renders the date in the browser/Gmail local timezone, so attach
    the computer's local timezone for that historical date.
    """
    value = html.unescape(value).strip()

    # Gmail sometimes renders September as the non-RFC abbreviation "Sept"
    # (for example: "Sat, 5 Sept 2026, 23:16"). Python's email date
    # parser accepts "Sep" and "September", but rejects "Sept", which made
    # otherwise-valid September approval rows silently disappear from scans.
    value = re.sub(r"\bSept\.?\b", "Sep", value, flags=re.IGNORECASE)

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if dt is None:
        return None

    if dt.tzinfo is None:
        # For a naive datetime, astimezone() interprets it as local wall time
        # and applies the local UTC offset appropriate to that historical date.
        dt = dt.astimezone()

    return dt.replace(second=0, microsecond=0)


def parse_iso(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt


def extract_date_from_html(fragment: str) -> Optional[datetime]:
    candidates = []
    for raw in TITLE_ATTR_RE.findall(fragment):
        dt = parse_gmail_title_date(raw)
        if dt:
            candidates.append(dt)
    return candidates[-1] if candidates else None


def extract_html_approvals(path: Path) -> list[Approval]:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    approvals: list[Approval] = []

    # Preferred path: Gmail inbox/search rows. Keeping each match inside its
    # row prevents a nearby message's date from being assigned to the wrong bot.
    rows = ROW_RE.findall(raw)
    for row in rows:
        if not SENDER_RE.search(row):
            continue

        plain = clean_html(row)
        if not SUBJECT_RE.search(plain):
            continue

        name_match = LIVE_TEXT_RE.search(plain)
        if not name_match:
            continue

        approved_at = extract_date_from_html(row)
        if not approved_at:
            continue

        count_match = THREAD_COUNT_RE.search(row)
        thread_count = int(count_match.group(1)) if count_match else None

        approvals.append(
            Approval(
                character_name=SPACE_RE.sub(" ", name_match.group(1)).strip(" ,"),
                approved_at=approved_at,
                source_file=str(path),
                source_kind="gmail-html-row",
                thread_count=thread_count,
            )
        )

    # Fallback for a saved page containing an opened message rather than rows.
    if not approvals:
        plain = clean_html(raw)
        names = list(LIVE_TEXT_RE.finditer(plain))
        if len(names) == 1:
            approved_at = extract_date_from_html(raw)
            if approved_at:
                approvals.append(
                    Approval(
                        character_name=SPACE_RE.sub(" ", names[0].group(1)).strip(" ,"),
                        approved_at=approved_at,
                        source_file=str(path),
                        source_kind="gmail-html-message",
                    )
                )

    return approvals


def message_plain_text(message) -> str:
    if message.is_multipart():
        parts = []
        for part in message.walk():
            ctype = part.get_content_type()
            disp = (part.get("Content-Disposition") or "").lower()
            if "attachment" in disp:
                continue
            if ctype == "text/plain":
                try:
                    parts.append(part.get_content())
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    parts.append(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        if parts:
            return "\n".join(parts)

        # HTML-only fallback.
        for part in message.walk():
            if part.get_content_type() == "text/html":
                try:
                    return clean_html(part.get_content())
                except Exception:
                    payload = part.get_payload(decode=True) or b""
                    return clean_html(payload.decode(part.get_content_charset() or "utf-8", errors="ignore"))
        return ""

    try:
        content = message.get_content()
    except Exception:
        payload = message.get_payload(decode=True) or b""
        content = payload.decode(message.get_content_charset() or "utf-8", errors="ignore")

    return clean_html(content) if message.get_content_type() == "text/html" else str(content)


def extract_message_approval(message, source: Path, kind: str) -> list[Approval]:
    sender = str(message.get("From", ""))
    subject = str(message.get("Subject", ""))
    if "support@spicychat.ai" not in sender.casefold():
        return []
    if "your character is live" not in subject.casefold():
        return []

    body = message_plain_text(message)
    match = LIVE_TEXT_RE.search(body)
    if not match:
        return []

    raw_date = str(message.get("Date", "")).strip()
    try:
        dt = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError, OverflowError):
        return []

    if dt is None:
        return []
    if dt.tzinfo is None:
        dt = dt.astimezone()

    return [
        Approval(
            character_name=SPACE_RE.sub(" ", match.group(1)).strip(" ,"),
            approved_at=dt.replace(microsecond=0),
            source_file=str(source),
            source_kind=kind,
        )
    ]


def extract_eml_approvals(path: Path) -> list[Approval]:
    with path.open("rb") as fh:
        msg = BytesParser(policy=policy.default).parse(fh)
    return extract_message_approval(msg, path, "eml")


def extract_mbox_approvals(path: Path) -> list[Approval]:
    approvals: list[Approval] = []
    box = mailbox.mbox(path, factory=lambda f: BytesParser(policy=policy.default).parse(f))
    try:
        for msg in box:
            approvals.extend(extract_message_approval(msg, path, "mbox"))
    finally:
        box.close()
    return approvals


def gather_input_files(inputs: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw).expanduser()
        if path.is_dir():
            files.extend(
                p for p in path.rglob("*")
                if p.is_file() and p.suffix.casefold() in SUPPORTED_SUFFIXES
            )
        elif path.is_file() and path.suffix.casefold() in SUPPORTED_SUFFIXES:
            files.append(path)

    # Deduplicate while keeping deterministic ordering.
    unique = {}
    for path in files:
        try:
            key = str(path.resolve()).casefold()
        except OSError:
            key = str(path).casefold()
        unique[key] = path
    return sorted(unique.values(), key=lambda p: str(p).casefold())


def choose_files_interactively() -> list[str]:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askopenfilenames(
            title="Select saved Gmail / SpicyChat approval emails",
            filetypes=[
                ("Gmail / email files", "*.html *.htm *.eml *.mbox"),
                ("HTML files", "*.html *.htm"),
                ("Email files", "*.eml *.mbox"),
                ("All files", "*.*"),
            ],
        )
        root.destroy()
        if selected:
            return list(selected)
    except Exception:
        pass

    print()
    print("No files were passed to the scanner.")
    print("Drag saved Gmail HTML/EML files onto the BAT, or paste a file/folder path here.")
    value = input("Path: ").strip().strip('"')
    return [value] if value else []


def find_repo_root(explicit: Optional[str]) -> Optional[Path]:
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if (candidate / "assets" / "data" / "bots.json").is_file():
            return candidate
        return None

    starts = [Path(__file__).resolve().parent, Path.cwd().resolve()]
    seen = set()

    for start in starts:
        for candidate in [start, *start.parents]:
            key = str(candidate).casefold()
            if key in seen:
                continue
            seen.add(key)
            if (
                (candidate / "assets" / "data" / "bots.json").is_file()
                and (candidate / "assets" / "data" / "bot-public.json").is_file()
            ):
                return candidate
    return None


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def unique_index(items: list[dict], key_name: str = "name") -> tuple[dict[str, dict], set[str]]:
    grouped: dict[str, list[dict]] = {}
    for item in items:
        key = normalize_name(str(item.get(key_name, "")))
        if key:
            grouped.setdefault(key, []).append(item)

    unique = {k: values[0] for k, values in grouped.items() if len(values) == 1}
    ambiguous = {k for k, values in grouped.items() if len(values) > 1}
    return unique, ambiguous


def closest_names(name: str, candidates: Iterable[str], limit: int = 3) -> list[str]:
    import difflib
    mapping = {soft_name(c): c for c in candidates if soft_name(c)}
    hits = difflib.get_close_matches(soft_name(name), list(mapping), n=limit, cutoff=0.78)
    return [mapping[h] for h in hits]


def dedupe_approvals(items: list[Approval]) -> list[Approval]:
    seen = set()
    result = []
    for item in sorted(items, key=lambda a: (a.approved_at, normalize_name(a.character_name), a.source_file)):
        key = (normalize_name(item.character_name), item.approved_at.isoformat())
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def evaluate(
    approvals: list[Approval],
    bots_data: dict,
    public_data: dict,
) -> tuple[list[ReportRow], list[tuple[dict, Approval]]]:
    bots = list(bots_data.get("bots") or [])
    public_records = list(public_data.get("bots") or [])

    bot_by_name, bot_name_ambiguous = unique_index(bots)
    pub_by_name, pub_name_ambiguous = unique_index(public_records)
    pub_by_id = {
        str(item.get("id")): item
        for item in public_records
        if item.get("id")
    }

    all_known_names = [str(x.get("name", "")) for x in bots + public_records if x.get("name")]

    grouped: dict[str, list[Approval]] = {}
    display_names: dict[str, str] = {}
    for approval in approvals:
        key = normalize_name(approval.character_name)
        grouped.setdefault(key, []).append(approval)
        display_names.setdefault(key, approval.character_name)

    report: list[ReportRow] = []
    safe_updates: list[tuple[dict, Approval]] = []

    for key, group in sorted(grouped.items(), key=lambda kv: display_names[kv[0]].casefold()):
        group = sorted(group, key=lambda a: a.approved_at)
        email_name = display_names[key]

        if key in bot_name_ambiguous or key in pub_name_ambiguous:
            for approval in group:
                report.append(ReportRow(
                    email_name, approval.iso, Path(approval.source_file).name,
                    approval.source_kind, str(approval.thread_count or ""),
                    "", "", "", "", "", "ambiguous-name",
                    "More than one site record uses this character name; nothing was changed."
                ))
            continue

        bot = bot_by_name.get(key)
        public_record = None
        if bot and bot.get("id") is not None:
            public_record = pub_by_id.get(str(bot.get("id")))
        if public_record is None:
            public_record = pub_by_name.get(key)

        if bot is None and public_record is None:
            suggestions = closest_names(email_name, all_known_names)
            reason = "No exact character-name match in bots.json or bot-public.json."
            if suggestions:
                reason += " Possible match: " + ", ".join(suggestions)
            for approval in group:
                report.append(ReportRow(
                    email_name, approval.iso, Path(approval.source_file).name,
                    approval.source_kind, str(approval.thread_count or ""),
                    "", "", "", "", "", "unmatched", reason
                ))
            continue

        if public_record is None:
            for approval in group:
                report.append(ReportRow(
                    email_name, approval.iso, Path(approval.source_file).name,
                    approval.source_kind, str(approval.thread_count or ""),
                    str(bot.get("id", "")) if bot else "",
                    str(bot.get("name", "")) if bot else "",
                    "", "", "", "no-public-record",
                    "Character exists in bots.json but has no bot-public.json record yet. Run the normal visibility/stat scan first; this tool will not create incomplete public-stat records."
                ))
            continue

        current_public = parse_iso(public_record.get("publicSinceAt"))
        previous_non_public = parse_iso(public_record.get("previousNonPublicObservedAt"))
        first_public = parse_iso(public_record.get("firstPublicObservedAt")) or current_public

        current_accuracy = str(public_record.get("publicSinceAccuracy") or public_record.get("accuracy") or "")
        current_source = str(public_record.get("publicSinceSource") or public_record.get("source") or "")

        # Existing confirmed data wins. If an imported email disagrees, show that
        # in the report instead of silently replacing it.
        if current_accuracy.casefold() == "confirmed":
            for approval in group:
                same = current_public and abs((approval.approved_at - current_public).total_seconds()) < 90
                status = "already-confirmed" if same else "confirmed-date-differs"
                reason = (
                    "This approval matches the already-confirmed public date."
                    if same else
                    "bot-public.json already has a confirmed public date. The email was recorded for review only and did not overwrite it."
                )
                report.append(ReportRow(
                    email_name, approval.iso, Path(approval.source_file).name,
                    approval.source_kind, str(approval.thread_count or ""),
                    str(public_record.get("id", "")),
                    str(public_record.get("name", "")),
                    str(public_record.get("publicSinceAt", "")),
                    str(public_record.get("previousNonPublicObservedAt", "") or ""),
                    str(public_record.get("firstPublicObservedAt", "") or ""),
                    status, reason
                ))
            continue

        if first_public is None:
            for approval in group:
                report.append(ReportRow(
                    email_name, approval.iso, Path(approval.source_file).name,
                    approval.source_kind, str(approval.thread_count or ""),
                    str(public_record.get("id", "")),
                    str(public_record.get("name", "")),
                    str(public_record.get("publicSinceAt", "")),
                    str(public_record.get("previousNonPublicObservedAt", "") or ""),
                    str(public_record.get("firstPublicObservedAt", "") or ""),
                    "needs-observation",
                    "There is no first-public observation to bracket the approval time, so it was not auto-applied."
                ))
            continue

        safe_candidates: list[Approval] = []
        for approval in group:
            if approval.approved_at > first_public:
                status = "after-first-public-observation"
                reason = (
                    "This approval happened after the bot was already observed public, "
                    "so it is probably a later edit/re-review approval."
                )
            elif previous_non_public and approval.approved_at <= previous_non_public:
                status = "before-later-nonpublic-observation"
                reason = (
                    "A later saved observation still had the bot non-public. "
                    "This email therefore cannot safely represent the transition to the current public state."
                )
            else:
                status = "safe-candidate"
                reason = (
                    "Approval falls after the last known non-public observation "
                    "(when available) and no later than the first public observation."
                )
                safe_candidates.append(approval)

            report.append(ReportRow(
                email_name, approval.iso, Path(approval.source_file).name,
                approval.source_kind, str(approval.thread_count or ""),
                str(public_record.get("id", "")),
                str(public_record.get("name", "")),
                str(public_record.get("publicSinceAt", "")),
                str(public_record.get("previousNonPublicObservedAt", "") or ""),
                str(public_record.get("firstPublicObservedAt", "") or ""),
                status, reason
            ))

        if safe_candidates:
            # Earliest approval inside the known non-public -> public bracket is
            # the best available first-public candidate.
            chosen = min(safe_candidates, key=lambda a: a.approved_at)
            safe_updates.append((public_record, chosen))

    return report, safe_updates


def apply_updates(public_data: dict, updates: list[tuple[dict, Approval]]) -> int:
    applied = 0
    for record, approval in updates:
        old_accuracy = str(record.get("publicSinceAccuracy") or record.get("accuracy") or "")
        if old_accuracy.casefold() == "confirmed":
            continue

        record["publicSinceAt"] = approval.iso
        record["publicSinceAccuracy"] = "confirmed"
        record["publicSinceSource"] = "spicychat-approval-email"
        record["accuracy"] = "confirmed"
        record["source"] = "spicychat-approval-email"

        existing_notes = str(record.get("notes") or "").strip()
        if "Public time confirmed from the SpicyChat approval email." not in existing_notes:
            record["notes"] = (existing_notes + " " + PUBLIC_NOTE).strip() if existing_notes else PUBLIC_NOTE

        baseline = parse_iso(record.get("baselineAt"))
        if baseline:
            lag_minutes = max(0, round((baseline - approval.approved_at).total_seconds() / 60))
            record["baselineLagMinutes"] = int(lag_minutes)
            record["baselineAccuracy"] = "same-observation" if lag_minutes == 0 else "after-public"
            if not record.get("baselineSource") and record.get("source"):
                record["baselineSource"] = record.get("source")

        applied += 1

    return applied


def write_reports(report: list[ReportRow], approvals: list[Approval], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    csv_path = output_dir / f"gmail-public-dates-{stamp}.csv"
    json_path = output_dir / f"gmail-public-dates-{stamp}.json"

    fieldnames = list(ReportRow.__dataclass_fields__.keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in report:
            writer.writerow(asdict(row))

    payload = {
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "approvalsFound": len(approvals),
        "results": [asdict(row) for row in report],
    }
    with json_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    return csv_path, json_path


def print_summary(report: list[ReportRow], safe_updates: list[tuple[dict, Approval]]) -> None:
    counts: dict[str, int] = {}
    for row in report:
        counts[row.status] = counts.get(row.status, 0) + 1

    print()
    print("=" * 68)
    print(" SpicyChat Gmail public-date scan")
    print("=" * 68)
    print(f"Report rows : {len(report)}")
    print(f"Safe updates: {len(safe_updates)}")
    for key in sorted(counts):
        print(f"  {key:34} {counts[key]}")
    print()

    if safe_updates:
        print("Safe public-date updates:")
        for record, approval in safe_updates:
            print(f"  - {record.get('name', approval.character_name)} -> {approval.iso}")
        print()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract SpicyChat approval dates from saved Gmail/email files and safely update bot-public.json."
    )
    parser.add_argument("inputs", nargs="*", help="Saved Gmail HTML/HTM, EML, MBOX, or folders containing them.")
    parser.add_argument("--repo", help="Path to the spicychat.drache.uk repository root.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--scan-only", action="store_true", help="Never modify bot-public.json.")
    mode.add_argument("--apply", action="store_true", help="Apply safe updates without the interactive apply question.")
    parser.add_argument("--yes", action="store_true", help="Alias for --apply.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    raw_inputs = list(args.inputs)
    if not raw_inputs:
        raw_inputs = choose_files_interactively()
    files = gather_input_files(raw_inputs)

    if not files:
        print("No supported Gmail/email files were selected.")
        return 2

    repo_root = find_repo_root(args.repo)
    if repo_root is None:
        print()
        print("Could not find the spicychat.drache.uk repo root.")
        print("Expected: assets\\data\\bots.json and assets\\data\\bot-public.json")
        print("Put this script inside the repo's tools folder, or use --repo PATH.")
        return 3

    bots_path = repo_root / "assets" / "data" / "bots.json"
    public_path = repo_root / "assets" / "data" / "bot-public.json"
    tools_dir = repo_root / "tools"
    output_dir = tools_dir / "output"

    approvals: list[Approval] = []
    failures: list[tuple[Path, str]] = []

    print(f"Repo: {repo_root}")
    print(f"Scanning {len(files)} file(s)...")

    for path in files:
        try:
            suffix = path.suffix.casefold()
            if suffix in {".html", ".htm"}:
                found = extract_html_approvals(path)
            elif suffix == ".eml":
                found = extract_eml_approvals(path)
            elif suffix == ".mbox":
                found = extract_mbox_approvals(path)
            else:
                found = []
            approvals.extend(found)
            print(f"  {path.name}: {len(found)} approval(s)")
        except Exception as exc:
            failures.append((path, str(exc)))
            print(f"  {path.name}: ERROR - {exc}")

    approvals = dedupe_approvals(approvals)

    if not approvals:
        print()
        print("No SpicyChat 'Your character is live' approvals were found.")
        if failures:
            print(f"{len(failures)} file(s) also failed to parse.")
        return 4

    try:
        bots_data = load_json(bots_path)
        public_data = load_json(public_path)
    except Exception as exc:
        print(f"Could not read site JSON data: {exc}")
        return 5

    report, safe_updates = evaluate(approvals, bots_data, public_data)
    csv_path, json_path = write_reports(report, approvals, output_dir)

    print_summary(report, safe_updates)
    print(f"CSV report : {csv_path}")
    print(f"JSON report: {json_path}")

    if failures:
        print()
        print("Files with parse errors:")
        for path, error in failures:
            print(f"  - {path}: {error}")

    if not safe_updates:
        print()
        print("Nothing safe to update automatically.")
        return 0

    do_apply = bool(args.apply or args.yes)
    if args.scan_only:
        do_apply = False
    elif not do_apply:
        print()
        answer = input(f"Apply {len(safe_updates)} safe update(s) to bot-public.json? [y/N]: ").strip().casefold()
        do_apply = answer in {"y", "yes"}

    if not do_apply:
        print("No changes written to bot-public.json.")
        return 0

    backup_dir = tools_dir / "backups" / "gmail-public-dates"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"bot-public-{stamp}.json"
    shutil.copy2(public_path, backup_path)

    applied = apply_updates(public_data, safe_updates)
    temp_path = public_path.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as fh:
        json.dump(public_data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(temp_path, public_path)

    print()
    print(f"Applied {applied} update(s).")
    print(f"Backup: {backup_path}")
    print(f"Updated: {public_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
