#!/usr/bin/env python3
"""Validate generated SpicyChat site data before an automatic commit.

The checks are intentionally conservative: stop on structural corruption and
known bad scrape patterns, while leaving subjective/curated metadata alone.
"""
from __future__ import annotations

import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "assets" / "data"

FILES = {
    "bots": DATA / "bots.json",
    "stats": DATA / "bot-stats.json",
    "history": DATA / "bot-history.json",
    "events": DATA / "bot-events.json",
    "discoveries": DATA / "bot-discoveries.json",
    "public": DATA / "bot-public.json",
    "archived": DATA / "archived-bots.json",
}

errors: list[str] = []
warnings: list[str] = []


def err(message: str) -> None:
    errors.append(message)


def warn(message: str) -> None:
    warnings.append(message)


def load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        err(f"{path.relative_to(ROOT)} is not valid JSON: {exc}")
        return {}


def ids(rows, label: str) -> list[str]:
    result: list[str] = []
    for index, row in enumerate(rows or []):
        if not isinstance(row, dict):
            err(f"{label}[{index}] is not an object")
            continue
        value = row.get("id")
        if not isinstance(value, str) or not value.strip():
            err(f"{label}[{index}] has no usable id")
            continue
        result.append(value)
    return result


def duplicate_values(values: list[str]) -> list[str]:
    counts = defaultdict(int)
    for value in values:
        counts[value] += 1
    return sorted(value for value, count in counts.items() if count > 1)


def git_head_json(relative_path: str):
    try:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{relative_path}"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        return json.loads(proc.stdout)
    except Exception:
        return None


def number(row: dict, key: str):
    value = row.get(key)
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


docs = {name: load(path) for name, path in FILES.items()}

bots = docs["bots"].get("bots", []) if isinstance(docs["bots"], dict) else []
stats = docs["stats"].get("bots", []) if isinstance(docs["stats"], dict) else []
archived = docs["archived"].get("bots", []) if isinstance(docs["archived"], dict) else []
discoveries = docs["discoveries"].get("discoveries", []) if isinstance(docs["discoveries"], dict) else []
public_rows = docs["public"].get("bots", []) if isinstance(docs["public"], dict) else []
snapshots = docs["history"].get("snapshots", []) if isinstance(docs["history"], dict) else []

active_ids_list = ids(bots, "bots.bots")
stats_ids_list = ids(stats, "bot-stats.bots")
archived_ids_list = ids(archived, "archived-bots.bots")
discovery_ids_list = ids(discoveries, "bot-discoveries.discoveries")
public_ids_list = ids(public_rows, "bot-public.bots")

for label, values in (
    ("active bots", active_ids_list),
    ("stats rows", stats_ids_list),
    ("archived bots", archived_ids_list),
    ("discoveries", discovery_ids_list),
    ("public records", public_ids_list),
):
    dupes = duplicate_values(values)
    if dupes:
        err(f"duplicate IDs in {label}: {', '.join(dupes)}")

active_ids = set(active_ids_list)
stats_ids = set(stats_ids_list)
archived_ids = set(archived_ids_list)
discovery_ids = set(discovery_ids_list)
public_ids = set(public_ids_list)

if active_ids & archived_ids:
    err("archived bot IDs reappeared in active bots: " + ", ".join(sorted(active_ids & archived_ids)))
if discovery_ids & active_ids:
    err("discoveries still contain already-curated active bots: " + ", ".join(sorted(discovery_ids & active_ids)))
if discovery_ids & archived_ids:
    err("discoveries contain archived bots: " + ", ".join(sorted(discovery_ids & archived_ids)))
if public_ids - active_ids:
    err("active bot-public.json contains IDs not present in active bots: " + ", ".join(sorted(public_ids - active_ids)))

missing_stats = active_ids - stats_ids
extra_stats = stats_ids - active_ids
if missing_stats:
    err("active bots missing stats rows: " + ", ".join(sorted(missing_stats)))
if extra_stats:
    err("stats rows exist for non-active bots: " + ", ".join(sorted(extra_stats)))

category_ids = {
    row.get("id") for row in docs["bots"].get("categories", [])
    if isinstance(row, dict) and row.get("id")
}
allowed_origins = {"requested", "personal", "unknown", None, ""}
for bot in bots:
    name = bot.get("name") or bot.get("id") or "unknown"
    if bot.get("category") not in category_ids:
        err(f"{name}: invalid category {bot.get('category')!r}")
    if bot.get("origin") not in allowed_origins:
        err(f"{name}: invalid origin {bot.get('origin')!r}")
    for field in ("nsfw", "imageHidden", "needsReview"):
        if field in bot and not isinstance(bot.get(field), bool):
            err(f"{name}: {field} must be boolean when present")

for item in discoveries:
    name = item.get("name") or item.get("id") or "unknown discovery"
    for field in ("nsfw", "avatarIsNsfw", "imageHiddenDefault"):
        if field in item and not isinstance(item.get(field), bool):
            err(f"{name}: discovery {field} must be boolean when present")
    if item.get("origin") not in allowed_origins:
        err(f"{name}: discovery has invalid origin {item.get('origin')!r}")

stats_by_id = {row.get("id"): row for row in stats if isinstance(row, dict) and row.get("id")}
bots_by_id = {row.get("id"): row for row in bots if isinstance(row, dict) and row.get("id")}

# Any currently public stats row should have publication metadata. This makes
# public-date regressions obvious without requiring unlisted bots to have it.
for bot_id, row in stats_by_id.items():
    if row.get("visibility") == "public" and bot_id not in public_ids:
        err(f"{row.get('name', bot_id)} is public in stats but has no bot-public record")

# The latest automatic history snapshot should be a complete copy of active stats.
if snapshots:
    latest = snapshots[-1]
    if isinstance(latest, dict) and latest.get("source") == "github-public-updater":
        latest_ids = set(ids(latest.get("bots", []), "bot-history.latest.bots"))
        if latest_ids != active_ids:
            err(
                "latest automatic history snapshot is incomplete "
                f"(active={len(active_ids)}, snapshot={len(latest_ids)})"
            )

# Enforce the per-bot mirrored-stats guards that protect known corruption cases.
for bot_id, bot in bots_by_id.items():
    guard = bot.get("statsGuard") or {}
    if guard.get("type") != "reject-mirrored-stats":
        continue
    mirror_id = guard.get("mirrorBotId")
    row = stats_by_id.get(bot_id)
    mirror = stats_by_id.get(mirror_id)
    if not row or not mirror:
        continue
    fallback_messages = (guard.get("fallback") or {}).get("messages")
    messages = number(row, "messages")
    mirror_messages = number(mirror, "messages")
    tokens = number(row, "tokens")
    mirror_tokens = number(mirror, "tokens")
    if (
        messages is not None
        and mirror_messages is not None
        and fallback_messages is not None
        and messages > int(fallback_messages)
        and messages == mirror_messages
        and (tokens is None or mirror_tokens is None or tokens == mirror_tokens)
    ):
        err(
            f"statsGuard violation: {bot.get('name', bot_id)} still mirrors "
            f"{mirror.get('name', mirror_id)}"
        )

# Generic high-value exact mirroring is almost certainly a card-boundary scrape.
# Require both messages and tokens to match to avoid flagging ordinary ties.
pairs: dict[tuple[int, int], list[str]] = defaultdict(list)
for row in stats:
    messages = number(row, "messages")
    tokens = number(row, "tokens")
    if messages is not None and tokens is not None and messages >= 10_000:
        pairs[(messages, tokens)].append(row.get("name") or row.get("id"))
for (messages, tokens), names in pairs.items():
    if len(names) > 1:
        err(
            "suspicious exact high-count mirroring: "
            f"{', '.join(names)} all report {messages} messages / {tokens} tokens"
        )

# Compare with the checked-out HEAD when running in GitHub Actions. These checks
# target catastrophic scraper output, not normal growth.
head_bots_doc = git_head_json("assets/data/bots.json")
head_stats_doc = git_head_json("assets/data/bot-stats.json")
if isinstance(head_bots_doc, dict):
    old_count = len(head_bots_doc.get("bots", []))
    new_count = len(bots)
    allowed_drop = max(2, int(old_count * 0.10))
    if old_count and new_count < old_count - allowed_drop:
        err(f"active bot count collapsed from {old_count} to {new_count}")

if isinstance(head_stats_doc, dict):
    old_stats = {
        row.get("id"): row for row in head_stats_doc.get("bots", [])
        if isinstance(row, dict) and row.get("id")
    }
    for bot_id, new_row in stats_by_id.items():
        old_row = old_stats.get(bot_id)
        if not old_row:
            continue
        old_messages = number(old_row, "messages")
        new_messages = number(new_row, "messages")
        if old_messages is None or new_messages is None:
            continue
        if old_messages >= 1000 and new_messages < old_messages * 0.80 and old_messages - new_messages > 1000:
            err(
                f"large message regression for {new_row.get('name', bot_id)}: "
                f"{old_messages} -> {new_messages}"
            )
        if old_messages > 0 and new_messages - old_messages > 100_000 and new_messages > old_messages * 10:
            err(
                f"implausible one-run message jump for {new_row.get('name', bot_id)}: "
                f"{old_messages} -> {new_messages}"
            )

# Warn, but don't fail, on origin fields that still need manual context.
unknown_origins = [
    bot.get("name", bot.get("id")) for bot in bots
    if bot.get("origin") in {None, "", "unknown"}
]
if unknown_origins:
    warn("origin still needs curation: " + ", ".join(unknown_origins))

print(
    f"Validated {len(active_ids)} active bots, {len(stats_ids)} stats rows, "
    f"{len(archived_ids)} archived bot(s), and {len(discovery_ids)} pending discovery item(s)."
)
for message in warnings:
    print(f"::warning::{message}")
if errors:
    for message in errors:
        print(f"::error::{message}")
    print(f"Validation failed with {len(errors)} error(s).", file=sys.stderr)
    raise SystemExit(1)
print("Bot data validation passed.")
