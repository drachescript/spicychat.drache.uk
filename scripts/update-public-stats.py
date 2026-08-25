#!/usr/bin/env python3
"""Update bot usage stats from SpicyChat pages that work without signing in."""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "assets" / "data"
BOTS_PATH = DATA_DIR / "bots.json"
STATS_PATH = DATA_DIR / "bot-stats.json"
HISTORY_PATH = DATA_DIR / "bot-history.json"
EVENTS_PATH = DATA_DIR / "bot-events.json"
DISCOVERIES_PATH = DATA_DIR / "bot-discoveries.json"
PUBLIC_PATH = DATA_DIR / "bot-public.json"

PROFILE_RE = re.compile(r"/chatbot/([^/?#]+)")
CHAT_RE = re.compile(r"/chat/([^/?#]+)")
NUMBER_RE = re.compile(r"([0-9][0-9,.]*)(?:\s*)([kmb])?", re.I)
MILESTONES_DEFAULT = [100, 250, 500, 1000, 2500, 5000, 10000]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default=None):
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    # Validate the exact text before replacing the file.
    json.loads(text)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def normalize_metric(text: str | None):
    if not text:
        return None
    cleaned = " ".join(str(text).split())
    match = NUMBER_RE.search(cleaned)
    if not match:
        return None
    number = match.group(1).replace(",", "")
    suffix = (match.group(2) or "").lower()
    try:
        value = float(number)
    except ValueError:
        return None
    multiplier = {"": 1, "k": 1000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    numeric = int(round(value * multiplier))
    return {
        "value": numeric,
        "display": match.group(0).strip(),
        "approximate": bool(suffix),
    }


def metric_text_from_svg(svg) -> str | None:
    if not svg:
        return None
    wrapper = svg.find_parent("div")
    if not wrapper:
        return None
    p = wrapper.find("p")
    return p.get_text(" ", strip=True) if p else None


def parse_creator_html(html: str, creator_url: str) -> dict[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries: dict[str, dict] = {}

    for profile_link in soup.select('a[aria-label="character-info"][href*="/chatbot/"]'):
        href = profile_link.get("href", "")
        match = PROFILE_RE.search(href)
        if not match:
            continue
        bot_id = match.group(1)

        card = None
        for ancestor in profile_link.parents:
            if getattr(ancestor, "name", None) != "div":
                continue
            if ancestor.select_one("svg.lucide-message-square-text") and ancestor.select_one(
                f'a[href*="/chat/{bot_id}"]'
            ):
                card = ancestor
                break
        if card is None:
            continue

        name_el = card.select_one(f'a[href*="/chat/{bot_id}"][title]')
        if name_el is not None:
            name = name_el.get("title", "").strip()
        else:
            image = card.select_one(f'a[href*="/chat/{bot_id}"] img[alt]')
            name = (image.get("alt", "") if image else "").strip()

        message_text = metric_text_from_svg(card.select_one("svg.lucide-message-square-text"))
        token_text = metric_text_from_svg(card.select_one("svg.lucide-blocks"))
        messages = normalize_metric(message_text)
        tokens = normalize_metric(token_text)
        if messages is None:
            continue

        chat_link = card.select_one(f'a[href*="/chat/{bot_id}"]')
        chat_url = urljoin(creator_url, chat_link.get("href", "")) if chat_link else f"https://spicychat.ai/chat/{bot_id}"
        profile_url = urljoin(creator_url, href)

        entries[bot_id] = {
            "id": bot_id,
            "name": name,
            "chatUrl": chat_url,
            "profileUrl": profile_url,
            "messages": messages,
            "tokens": tokens,
            "source": "creator-profile",
        }

    return entries


def parse_profile_html(html: str, expected_id: str, profile_url: str) -> dict | None:
    soup = BeautifulSoup(html, "html.parser")

    canonical = soup.select_one('link[rel="canonical"]')
    if canonical:
        match = PROFILE_RE.search(canonical.get("href", ""))
        if match and match.group(1) != expected_id:
            return None

    messages = None
    for message_svg in soup.select("svg.lucide-message-square-text"):
        candidate = normalize_metric(metric_text_from_svg(message_svg))
        if candidate is not None:
            messages = candidate
            break
    if messages is None:
        return None

    tokens_anchor = soup.select_one('a[aria-label="tokens-info"]')
    token_text = tokens_anchor.get_text(" ", strip=True) if tokens_anchor else None
    tokens = normalize_metric(token_text)

    h1 = soup.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ""
    chat_link = soup.select_one(f'a[href*="/chat/{expected_id}"]')
    chat_url = urljoin(profile_url, chat_link.get("href", "")) if chat_link else f"https://spicychat.ai/chat/{expected_id}"

    return {
        "id": expected_id,
        "name": name,
        "chatUrl": chat_url,
        "profileUrl": profile_url,
        "messages": messages,
        "tokens": tokens,
        "source": "direct-profile",
    }


def creator_pagination_urls(html: str, creator_url: str) -> list[str]:
    """Pick up normal page links if SpicyChat starts paginating this creator profile."""
    soup = BeautifulSoup(html, "html.parser")
    base = urlparse(creator_url)
    urls = set()
    for a in soup.find_all("a", href=True):
        candidate = urljoin(creator_url, a["href"])
        parsed = urlparse(candidate)
        if parsed.netloc != base.netloc or parsed.path.rstrip("/") != base.path.rstrip("/"):
            continue
        query = parse_qs(parsed.query)
        if any(key.lower() in {"page", "p"} for key in query):
            urls.add(candidate)
    return sorted(urls)


def load_live_creator(creator: str, browser, pause_seconds: float = 0.5) -> tuple[dict[str, dict], int]:
    creator_url = f"https://spicychat.ai/creator/{creator}"
    page = browser.new_page()
    seen_urls = {creator_url}
    queue = [creator_url]
    all_entries: dict[str, dict] = {}
    pages_checked = 0

    try:
        while queue and pages_checked < 10:
            url = queue.pop(0)
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_selector('a[aria-label="character-info"][href*="/chatbot/"]', timeout=35_000)
            page.wait_for_timeout(1800)
            html = page.content()
            page_entries = parse_creator_html(html, url)
            all_entries.update(page_entries)
            pages_checked += 1

            for next_url in creator_pagination_urls(html, creator_url):
                if next_url not in seen_urls:
                    seen_urls.add(next_url)
                    queue.append(next_url)
            time.sleep(pause_seconds)
    finally:
        page.close()

    if len(all_entries) < 5:
        raise RuntimeError(
            f"Only found {len(all_entries)} bots on the creator page. Stopping instead of writing suspicious data."
        )
    return all_entries, pages_checked


def load_live_profile(bot_id: str, browser, pause_seconds: float = 0.5) -> dict | None:
    profile_url = f"https://spicychat.ai/chatbot/{bot_id}"
    page = browser.new_page()
    try:
        response = page.goto(profile_url, wait_until="domcontentloaded", timeout=45_000)
        if response is not None and response.status >= 400:
            return None
        try:
            page.wait_for_selector("h1", timeout=18_000)
            page.wait_for_timeout(900)
        except Exception:
            return None
        result = parse_profile_html(page.content(), bot_id, profile_url)
        time.sleep(pause_seconds)
        return result
    finally:
        page.close()


def launch_browser():
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
    except Exception:
        playwright.stop()
        raise
    return playwright, browser


def history_row(row: dict) -> dict:
    keys = [
        "id",
        "name",
        "visibility",
        "messages",
        "messagesDisplay",
        "messagesApproximate",
        "tokens",
        "tokensDisplay",
        "tokensApproximate",
        "rawMessages",
        "rawTokens",
    ]
    return {key: row.get(key) for key in keys if key in row}


def add_event(events: dict, event: dict) -> bool:
    existing = events.setdefault("events", [])
    etype = event.get("type")
    bot_id = event.get("botId")

    for old in existing:
        if old.get("type") != etype or old.get("botId") != bot_id:
            continue
        if etype == "milestone" and old.get("value") == event.get("value"):
            return False
        if etype == "new":
            return False
        if etype == "visibility" and old.get("from") == event.get("from") and old.get("to") == event.get("to"):
            return False

    existing.append(event)
    return True


def safe_message_update(old_row: dict, observed: dict, warnings: list[str]) -> tuple[dict, bool]:
    new_metric = observed.get("messages")
    if not new_metric:
        return old_row, False

    new_value = new_metric["value"]
    old_value = old_row.get("messages")
    old_approx = bool(old_row.get("messagesApproximate"))
    new_approx = bool(new_metric.get("approximate"))

    # Message totals normally only move upward. Rounded public counts can be noisy,
    # so a lower observed value is ignored instead of rewriting history backwards.
    if old_value is not None and new_value < int(old_value):
        allow_more_precise = old_approx and not new_approx and new_value >= int(old_value * 0.9)
        if not allow_more_precise:
            warnings.append(
                f"{old_row.get('name', old_row.get('id'))}: ignored message regression "
                f"{old_row.get('messagesDisplay', old_value)} -> {new_metric['display']}"
            )
            return old_row, False

    changed = (
        old_row.get("messages") != new_value
        or old_row.get("messagesDisplay") != new_metric["display"]
        or bool(old_row.get("messagesApproximate")) != new_approx
    )
    if changed:
        old_row["messages"] = new_value
        old_row["messagesDisplay"] = new_metric["display"]
        old_row["messagesApproximate"] = new_approx
        old_row["rawMessages"] = new_metric["display"]
    return old_row, changed


def update_token_metric(row: dict, observed: dict) -> bool:
    metric = observed.get("tokens")
    if not metric:
        return False
    changed = (
        row.get("tokens") != metric["value"]
        or bool(row.get("tokensApproximate")) != bool(metric["approximate"])
    )
    if changed:
        row["tokens"] = metric["value"]
        row["tokensDisplay"] = metric["display"] if metric["approximate"] else str(metric["value"])
        row["tokensApproximate"] = bool(metric["approximate"])
        row["rawTokens"] = metric["display"]
    return changed


def make_base_stat(bot: dict) -> dict:
    return {
        "id": bot["id"],
        "name": bot.get("name", bot["id"]),
        "title": bot.get("title", ""),
        "url": bot.get("url", f"https://spicychat.ai/chat/{bot['id']}"),
        "visibility": "unknown",
        "messages": None,
        "messagesDisplay": None,
        "messagesApproximate": False,
        "tokens": None,
        "tokensDisplay": None,
        "tokensApproximate": False,
        "image": None if bot.get("imageHidden") else bot.get("image"),
        "rawMessages": None,
        "rawTokens": None,
    }


def process_updates(
    bots_doc: dict,
    stats_doc: dict,
    history_doc: dict,
    events_doc: dict,
    discoveries_doc: dict,
    public_doc: dict,
    creator_entries: dict[str, dict],
    direct_entries: dict[str, dict],
    now: str,
):
    curated_bots = bots_doc.get("bots", [])
    known_ids = {bot["id"] for bot in curated_bots}
    old_rows = {row["id"]: row for row in stats_doc.get("bots", []) if row.get("id")}
    warnings: list[str] = []
    changed_bot_ids: set[str] = set()
    milestones_added: list[str] = []
    visibility_changes: list[str] = []
    public_baselines_added: list[str] = []
    public_changed = False
    public_doc.setdefault("schemaVersion", 1)
    public_doc.setdefault(
        "note",
        "Public baselines are evidence-based. first-observed means the bot was definitely public by that point, not that the exact switch time is known.",
    )
    public_entries = public_doc.setdefault("bots", [])
    public_by_id = {item.get("id"): item for item in public_entries if item.get("id")}

    milestones = events_doc.get("milestones") or MILESTONES_DEFAULT
    new_rows = []

    for bot in curated_bots:
        bot_id = bot["id"]
        previous = copy.deepcopy(old_rows.get(bot_id) or make_base_stat(bot))
        row = copy.deepcopy(previous)
        observed = creator_entries.get(bot_id) or direct_entries.get(bot_id)

        if observed:
            old_messages = previous.get("messages")
            row, message_changed = safe_message_update(row, observed, warnings)
            token_changed = update_token_metric(row, observed)

            # Appearing on the public creator profile is enough to confirm public visibility.
            visibility_changed = False
            old_visibility = row.get("visibility", "unknown")
            if observed["source"] == "creator-profile" and old_visibility != "public":
                row["visibility"] = "public"
                visibility_changed = True
                visibility_changes.append(f"{row.get('name')}: {old_visibility} -> public")
                add_event(
                    events_doc,
                    {
                        "at": now,
                        "botId": bot_id,
                        "botName": row.get("name", bot.get("name")),
                        "type": "visibility",
                        "from": old_visibility,
                        "to": "public",
                        "source": "creator-profile",
                    },
                )

            # Save the first public message baseline once. Direct chatbot pages can also
            # belong to unlisted bots, so only the creator listing confirms public status.
            if observed["source"] == "creator-profile" and bot_id not in public_by_id and row.get("messages") is not None:
                was_non_public = old_visibility not in {None, "", "unknown", "public"}
                baseline = {
                    "id": bot_id,
                    "name": bot.get("name", row.get("name", bot_id)),
                    "firstPublicObservedAt": now,
                    "previousNonPublicObservedAt": stats_doc.get("capturedAt") if was_non_public else None,
                    "baselineAt": now,
                    "messagesAtBaseline": row.get("messages"),
                    "messagesDisplayAtBaseline": row.get("messagesDisplay") or str(row.get("messages")),
                    "messagesApproximateAtBaseline": bool(row.get("messagesApproximate")),
                    "accuracy": "first-observed",
                    "source": "creator-profile",
                }
                public_entries.append(baseline)
                public_by_id[bot_id] = baseline
                public_baselines_added.append(baseline["name"])
                public_changed = True

            if old_messages is None and row.get("messages") is not None:
                add_event(
                    events_doc,
                    {
                        "at": now,
                        "botId": bot_id,
                        "botName": row.get("name", bot.get("name")),
                        "type": "new",
                        "source": "automatic-check",
                    },
                )

            new_messages = row.get("messages")
            if old_messages is not None and new_messages is not None and new_messages >= old_messages:
                for milestone in milestones:
                    if int(old_messages) < int(milestone) <= int(new_messages):
                        if add_event(
                            events_doc,
                            {
                                "at": now,
                                "botId": bot_id,
                                "botName": row.get("name", bot.get("name")),
                                "type": "milestone",
                                "value": int(milestone),
                                "approximate": bool(row.get("messagesApproximate")),
                                "source": observed["source"],
                            },
                        ):
                            milestones_added.append(f"{row.get('name')}: {milestone}")

            scraped_name = (observed.get("name") or "").strip()
            curated_name = (bot.get("name") or "").strip()
            if scraped_name and curated_name and scraped_name != curated_name:
                warnings.append(f"{curated_name}: SpicyChat currently shows the name '{scraped_name}'")

            if message_changed or token_changed or visibility_changed:
                row["statsSource"] = observed["source"]
                row["profileUrl"] = observed.get("profileUrl") or f"https://spicychat.ai/chatbot/{bot_id}"
                row["statsUpdatedAt"] = now
                changed_bot_ids.add(bot_id)

        # Curated fields always win. The automatic updater never rewrites them.
        row["id"] = bot_id
        row["name"] = bot.get("name", row.get("name", bot_id))
        row["title"] = bot.get("title", row.get("title", ""))
        row["url"] = bot.get("url", row.get("url", f"https://spicychat.ai/chat/{bot_id}"))
        row["image"] = None if bot.get("imageHidden") else row.get("image", bot.get("image"))
        new_rows.append(row)

    # New public bots are only noted. They are never added to bots.json automatically.
    discoveries = discoveries_doc.setdefault("discoveries", [])
    by_id = {item.get("id"): item for item in discoveries if item.get("id")}
    new_discoveries = []

    # Remove discoveries that have since been added to the curated bot list.
    cleaned_discoveries = [item for item in discoveries if item.get("id") not in known_ids]
    discoveries_changed = len(cleaned_discoveries) != len(discoveries)
    discoveries_doc["discoveries"] = cleaned_discoveries
    by_id = {item.get("id"): item for item in cleaned_discoveries if item.get("id")}

    for bot_id, observed in sorted(creator_entries.items()):
        if bot_id in known_ids or bot_id in by_id:
            continue
        item = {
            "id": bot_id,
            "name": observed.get("name") or "Unknown bot",
            "profileUrl": observed.get("profileUrl"),
            "chatUrl": observed.get("chatUrl"),
            "firstSeenAt": now,
            "messagesDisplay": observed.get("messages", {}).get("display"),
            "tokensDisplay": observed.get("tokens", {}).get("display") if observed.get("tokens") else None,
        }
        discoveries_doc["discoveries"].append(item)
        by_id[bot_id] = item
        new_discoveries.append(item)
        discoveries_changed = True

    meaningful_stats_change = bool(changed_bot_ids)
    if meaningful_stats_change:
        stats_doc["schemaVersion"] = max(int(stats_doc.get("schemaVersion", 2)), 2)
        stats_doc["capturedAt"] = now
        stats_doc["source"] = "github-public-updater"
        stats_doc["label"] = "Automatic update"
        stats_doc["bots"] = new_rows

        snapshot = {
            "capturedAt": now,
            "source": "github-public-updater",
            "label": "Automatic update",
            "bots": [history_row(row) for row in new_rows],
        }
        history_doc.setdefault("snapshots", []).append(snapshot)
    else:
        # Keep row order stable even when nothing changed, but don't rewrite a file for it.
        new_rows = stats_doc.get("bots", [])

    events_doc["events"] = sorted(events_doc.get("events", []), key=lambda e: e.get("at", ""))
    discoveries_doc["discoveries"] = sorted(discoveries_doc.get("discoveries", []), key=lambda d: d.get("firstSeenAt", ""))
    public_doc["bots"] = sorted(public_doc.get("bots", []), key=lambda d: (d.get("firstPublicObservedAt", ""), d.get("name", "")))

    return {
        "statsChanged": meaningful_stats_change,
        "discoveriesChanged": discoveries_changed,
        "publicChanged": public_changed,
        "publicBaselines": public_baselines_added,
        "changedBotIds": sorted(changed_bot_ids),
        "newDiscoveries": new_discoveries,
        "milestones": milestones_added,
        "visibilityChanges": visibility_changes,
        "warnings": warnings,
        "newRows": new_rows,
    }


def parse_fixture_profiles(values: list[str]) -> dict[str, Path]:
    result = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--fixture-profile must be BOT_ID=/path/to/file.html")
        bot_id, path = value.split("=", 1)
        result[bot_id] = Path(path)
    return result


def build_summary(result: dict, creator_count: int, pages_checked: int, direct_checked: int, unavailable: list[str]) -> str:
    lines = [
        "## Bot stats update",
        "",
        f"- Creator bots seen: **{creator_count}** across **{pages_checked}** page(s)",
        f"- Direct profiles checked: **{direct_checked}**",
        f"- Known bots updated: **{len(result['changedBotIds'])}**",
        f"- New public bots found: **{len(result['newDiscoveries'])}**",
    ]
    if result["changedBotIds"]:
        names = {row.get("id"): row.get("name", row.get("id")) for row in result.get("newRows", [])}
        changed_names = [names.get(bot_id, bot_id) for bot_id in result["changedBotIds"]]
        lines.append(f"- Updated: **{', '.join(changed_names)}**")
    if result["milestones"]:
        lines.append(f"- Milestones: **{', '.join(result['milestones'])}**")
    if result["visibilityChanges"]:
        lines.append(f"- Visibility changes: **{', '.join(result['visibilityChanges'])}**")
    if result.get("publicBaselines"):
        lines.append(f"- Public baselines added: **{', '.join(result['publicBaselines'])}**")
    if unavailable:
        lines.append(f"- Direct profiles unavailable: **{len(unavailable)}**")
    if result["warnings"]:
        lines += ["", "### Warnings"] + [f"- {item}" for item in result["warnings"]]
    if result["newDiscoveries"]:
        lines += ["", "### Needs site info"] + [
            f"- {item['name']} (`{item['id']}`)" for item in result["newDiscoveries"]
        ]
    if not result["statsChanged"] and not result["discoveriesChanged"] and not result.get("publicChanged"):
        lines += ["", "No repository data changed this run."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creator", default="dragongraf1312")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-file")
    parser.add_argument("--fixture-creator", type=Path)
    parser.add_argument("--fixture-profile", action="append", default=[])
    args = parser.parse_args()

    bots_doc = read_json(BOTS_PATH)
    stats_doc = read_json(STATS_PATH)
    history_doc = read_json(HISTORY_PATH)
    events_doc = read_json(EVENTS_PATH, {"schemaVersion": 1, "milestones": MILESTONES_DEFAULT, "events": []})
    discoveries_doc = read_json(DISCOVERIES_PATH, {"schemaVersion": 1, "discoveries": []})
    public_doc = read_json(PUBLIC_PATH, {"schemaVersion": 1, "bots": []})

    known_ids = {bot["id"] for bot in bots_doc.get("bots", [])}
    creator_url = f"https://spicychat.ai/creator/{args.creator}"
    playwright = browser = None

    try:
        if args.fixture_creator:
            html = args.fixture_creator.read_text(encoding="utf-8", errors="ignore")
            creator_entries = parse_creator_html(html, creator_url)
            pages_checked = 1
            if len(creator_entries) < 5:
                raise RuntimeError(f"Fixture creator page only contained {len(creator_entries)} bots")
        else:
            playwright, browser = launch_browser()
            creator_entries, pages_checked = load_live_creator(args.creator, browser)

        missing_ids = sorted(known_ids - set(creator_entries))
        direct_entries: dict[str, dict] = {}
        unavailable: list[str] = []
        direct_checked = 0

        fixture_profiles = parse_fixture_profiles(args.fixture_profile)
        for bot_id in missing_ids:
            observed = None
            if bot_id in fixture_profiles:
                profile_path = fixture_profiles[bot_id]
                observed = parse_profile_html(
                    profile_path.read_text(encoding="utf-8", errors="ignore"),
                    bot_id,
                    f"https://spicychat.ai/chatbot/{bot_id}",
                )
                direct_checked += 1
            elif args.fixture_creator:
                # Fixture mode is intentionally offline. Missing fixtures stay untouched.
                continue
            else:
                observed = load_live_profile(bot_id, browser)
                direct_checked += 1

            if observed:
                direct_entries[bot_id] = observed
            else:
                unavailable.append(bot_id)

        now = utc_now()
        result = process_updates(
            bots_doc,
            stats_doc,
            history_doc,
            events_doc,
            discoveries_doc,
            public_doc,
            creator_entries,
            direct_entries,
            now,
        )

        summary = build_summary(result, len(creator_entries), pages_checked, direct_checked, unavailable)
        print(summary)
        for warning in result["warnings"]:
            print(f"::warning::{warning}")
        for bot_id in unavailable:
            print(f"::notice::Direct profile unavailable: {bot_id}")

        if args.summary_file:
            Path(args.summary_file).write_text(summary, encoding="utf-8")

        if not args.dry_run:
            if result["statsChanged"]:
                write_json(STATS_PATH, stats_doc)
                write_json(HISTORY_PATH, history_doc)
                write_json(EVENTS_PATH, events_doc)
            elif result["milestones"] or result["visibilityChanges"]:
                # Normally covered by statsChanged; this keeps the write rule explicit.
                write_json(EVENTS_PATH, events_doc)

            if result["discoveriesChanged"]:
                write_json(DISCOVERIES_PATH, discoveries_doc)
            if result.get("publicChanged"):
                write_json(PUBLIC_PATH, public_doc)

        return 0
    finally:
        if browser is not None:
            browser.close()
        if playwright is not None:
            playwright.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"::error::{exc}")
        raise
