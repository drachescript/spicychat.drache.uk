#!/usr/bin/env python3
"""Update bot usage stats from SpicyChat pages that work without signing in."""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "assets" / "data"
BOTS_PATH = DATA_DIR / "bots.json"
STATS_PATH = DATA_DIR / "bot-stats.json"
HISTORY_PATH = DATA_DIR / "bot-history.json"
EVENTS_PATH = DATA_DIR / "bot-events.json"
DISCOVERIES_PATH = DATA_DIR / "bot-discoveries.json"
PUBLIC_PATH = DATA_DIR / "bot-public.json"
ARCHIVED_PATH = DATA_DIR / "archived-bots.json"

PROFILE_RE = re.compile(r"/chatbot/([^/?#]+)")
CHAT_RE = re.compile(r"/chat/([^/?#]+)")
NUMBER_RE = re.compile(r"([0-9][0-9,.]*)(?:\s*)([kmb])?", re.I)
MILESTONES_DEFAULT = [100, 250, 500, 1000, 2500, 5000, 10000]

TYPESENSE_HOST_DEFAULT = "etmzpxgvnid370fyp.a1.typesense.net"
TYPESENSE_COLLECTION_DEFAULT = "public_characters_alias"
TYPESENSE_QUERY_BY = "name,title,tags,creator_username,character_id,type"
TYPESENSE_INCLUDE_FIELDS = ",".join([
    "name", "title", "tags", "creator_username", "character_id",
    "avatar_is_nsfw", "avatar_url", "visibility", "definition_visible",
    "num_messages", "token_count", "rating_score", "lora_status",
    "creator_user_id", "is_nsfw", "type", "sub_characters_count",
    "group_size_category", "has_lorebooks", "voice_id", "group_addable",
    "createdAt", "updatedAt", "greeting", "language",
])
PUBLIC_DISCOVERY_SOURCES = {"creator-profile", "typesense"}


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


def metric_from_value(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = int(round(float(value)))
        return {"value": numeric, "display": f"{numeric:,}", "approximate": False}
    return normalize_metric(str(value))


def bool_value(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if cleaned in {"true", "1", "yes"}:
            return True
        if cleaned in {"false", "0", "no"}:
            return False
    return None


def bot_image_hidden(bot: dict) -> bool:
    # imageHidden is a manual override. If it is absent, NSFW supplies the default.
    if isinstance(bot.get("imageHidden"), bool):
        return bot["imageHidden"]
    return bool(bot.get("nsfw"))


def pending_override_for(bots_doc: dict, name: str | None) -> dict:
    normalized = (name or "").strip().casefold()
    if not normalized:
        return {}
    for item in bots_doc.get("pendingBotOverrides", []) or []:
        if str(item.get("name", "")).strip().casefold() == normalized:
            return item
    return {}


def normalize_avatar_url(value) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(("https://", "http://")):
        return text
    text = text.lstrip("/")
    if text.startswith("avatars/"):
        suffix = "" if "?" in text else "?class=avatar256x256"
        return f"https://cdn.nd-api.com/{text}{suffix}"
    return text


def date_only(value: str | None, fallback: str) -> str:
    raw = str(value or fallback).strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.date().isoformat()
    except ValueError:
        return raw[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw) else fallback[:10]


def auto_add_public_bots(
    bots_doc: dict,
    archived_doc: dict,
    creator_entries: dict[str, dict],
    now: str,
) -> list[dict]:
    """Promote newly discovered public creator bots into the live site automatically.

    Typesense/creator-profile discovery is already restricted to the configured
    creator and public visibility.  New records use safe defaults for fields that
    cannot be inferred (origin remains unknown; category falls back to Other) and
    can be curated later without blocking stats/public-date tracking.
    """
    active = list(bots_doc.get("bots") or [])
    active_ids = {str(bot.get("id")) for bot in active if bot.get("id")}
    archived_ids = {str(bot.get("id")) for bot in archived_doc.get("bots", []) if bot.get("id")}
    category_ids = {
        str(item.get("id")) for item in bots_doc.get("categories", [])
        if isinstance(item, dict) and item.get("id")
    }
    fallback_category = "other" if "other" in category_ids else (sorted(category_ids)[0] if category_ids else None)

    candidates: list[tuple[str, dict]] = []
    for bot_id, observed in creator_entries.items():
        if bot_id in active_ids or bot_id in archived_ids:
            continue
        if observed.get("source") not in PUBLIC_DISCOVERY_SOURCES:
            continue
        if str(observed.get("visibility") or "public").lower() != "public":
            continue
        if not str(observed.get("name") or "").strip():
            continue
        candidates.append((bot_id, observed))

    if not candidates:
        return []

    candidates.sort(
        key=lambda pair: (str(pair[1].get("createdAt") or now), str(pair[1].get("name") or "")),
        reverse=True,
    )

    shift = len(candidates)
    for index, bot in enumerate(active, start=1):
        try:
            bot["order"] = int(bot.get("order", index)) + shift
        except (TypeError, ValueError):
            bot["order"] = index + shift

    added: list[dict] = []
    matched_override_names: set[str] = set()
    for order, (bot_id, observed) in enumerate(candidates, start=1):
        name = str(observed.get("name") or "").strip()
        override = pending_override_for(bots_doc, name)
        category = override.get("category") if override.get("category") in category_ids else fallback_category
        origin = override.get("origin") if override.get("origin") in {"requested", "personal"} else "unknown"
        created_full = str(observed.get("createdAt") or now)
        image = normalize_avatar_url(observed.get("image"))
        tags = [str(tag).strip() for tag in (observed.get("tags") or []) if str(tag).strip()]

        bot = {
            "id": bot_id,
            "name": name,
            "category": category,
            "tags": tags,
            "title": str(observed.get("title") or name).strip(),
            "url": observed.get("chatUrl") or f"https://spicychat.ai/chat/{bot_id}",
            "order": order,
            "image": image,
            "origin": origin,
            "knownSince": created_full,
            "knownSinceSource": "typesense-created-at" if observed.get("createdAt") else f"{observed.get('source')}-first-seen",
            "firstSeenAt": now,
            "createdAt": date_only(observed.get("createdAt"), now),
            "createdAtSource": "typesense" if observed.get("source") == "typesense" and observed.get("createdAt") else "automatic-discovery",
            "visibility": "public",
            "needsReview": False,
            "visibilitySource": observed.get("source") or "automatic-discovery",
            "autoDiscoveredAt": now,
            "autoDiscoveredSource": observed.get("source") or "automatic-discovery",
        }
        if isinstance(observed.get("nsfw"), bool):
            bot["nsfw"] = observed["nsfw"]
        if isinstance(override.get("imageHidden"), bool):
            bot["imageHidden"] = override["imageHidden"]
        if origin != "unknown":
            bot["originSource"] = override.get("source") or "pending-override"
        if image is None:
            bot.pop("image", None)
        if category is None:
            bot.pop("category", None)

        added.append(bot)
        matched_override_names.add(name.casefold())

    bots_doc["bots"] = added + active
    bots_doc["updatedAt"] = now
    if matched_override_names and isinstance(bots_doc.get("pendingBotOverrides"), list):
        bots_doc["pendingBotOverrides"] = [
            item for item in bots_doc["pendingBotOverrides"]
            if str(item.get("name") or "").strip().casefold() not in matched_override_names
        ]
    return added


def typesense_entry(document: dict, creator: str) -> dict | None:
    bot_id = str(document.get("character_id") or document.get("id") or "").strip()
    if not bot_id:
        return None
    creator_name = str(document.get("creator_username") or "").strip()
    if creator_name and creator_name.casefold() != creator.casefold():
        return None
    visibility = str(document.get("visibility") or "public").strip().lower()
    if visibility and visibility not in {"public", "published"}:
        return None
    nsfw = bool_value(document.get("is_nsfw"))
    avatar_nsfw = bool_value(document.get("avatar_is_nsfw"))
    image = normalize_avatar_url(document.get("avatar_url"))
    return {
        "id": bot_id,
        "name": str(document.get("name") or "").strip(),
        "title": str(document.get("title") or "").strip(),
        "tags": document.get("tags") if isinstance(document.get("tags"), list) else [],
        "chatUrl": f"https://spicychat.ai/chat/{bot_id}",
        "profileUrl": f"https://spicychat.ai/chatbot/{bot_id}",
        "messages": metric_from_value(document.get("num_messages")),
        "tokens": metric_from_value(document.get("token_count")),
        "image": image,
        "nsfw": nsfw,
        "avatarIsNsfw": avatar_nsfw,
        "visibility": "public",
        "createdAt": document.get("createdAt") or None,
        "updatedAt": document.get("updatedAt") or None,
        "greeting": document.get("greeting") or None,
        "language": document.get("language") or None,
        "source": "typesense",
    }


def load_typesense_creator(
    creator: str,
    api_key: str,
    host: str = TYPESENSE_HOST_DEFAULT,
    collection: str = TYPESENSE_COLLECTION_DEFAULT,
) -> tuple[dict[str, dict], int]:
    """Read the same public Typesense creator index used by the SpicyChat frontend.

    Deliberately does NOT add the frontend's optional ``is_nsfw:false`` filter,
    so public NSFW bots remain discoverable.
    """
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "https://" + host
    base = f"{host}/collections/{collection}/documents/search"
    entries: dict[str, dict] = {}
    page = 1
    pages_checked = 0
    per_page = 48  # Matches the captured SpicyChat frontend creator search.

    while page <= 20:
        params = {
            "q": "*",
            "query_by": TYPESENSE_QUERY_BY,
            "filter_by": f"creator_username:={creator} && application_ids:=spicychat",
            "include_fields": TYPESENSE_INCLUDE_FIELDS,
            "page": page,
            "per_page": per_page,
            # Latest-first makes new-bot discovery deterministic and mirrors
            # SpicyChat's public Latest/creator-follow behavior.
            "sort_by": "createdAt:desc",
        }
        request = Request(
            base + "?" + urlencode(params),
            headers={
                "X-TYPESENSE-API-KEY": api_key,
                "Accept": "application/json",
                "User-Agent": "spicychat.drache.uk-stats-worker/1.0",
            },
        )
        try:
            with urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Typesense HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Typesense request failed: {exc.reason}") from exc

        hits = payload.get("hits") or []
        pages_checked += 1
        for hit in hits:
            document = hit.get("document") if isinstance(hit, dict) else None
            if not isinstance(document, dict):
                continue
            item = typesense_entry(document, creator)
            if item:
                entries[item["id"]] = item

        found = payload.get("found")
        if len(hits) < per_page:
            break
        if isinstance(found, int) and page * per_page >= found:
            break
        page += 1

    return entries, pages_checked


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

            # A real bot card has exactly one character-info link.  The old
            # code could keep climbing into the entire creator grid when a
            # review/loading card did not expose its normal chat link.  At
            # that level select_one() returned the FIRST message counter in
            # the grid, which could mirror another bot's stats.
            profile_links = ancestor.select('a[aria-label="character-info"][href*="/chatbot/"]')
            if len(profile_links) != 1:
                continue
            own_profile = PROFILE_RE.search(profile_links[0].get("href", ""))
            if not own_profile or own_profile.group(1) != bot_id:
                continue

            matching_chat_link = None
            for candidate in ancestor.select('a[href*="/chat/"]'):
                chat_match = CHAT_RE.search(candidate.get("href", ""))
                if chat_match and chat_match.group(1) == bot_id:
                    matching_chat_link = candidate
                    break

            if ancestor.select_one("svg.lucide-message-square-text") and matching_chat_link:
                card = ancestor
                break
        if card is None:
            # Never guess across card boundaries.  A missing/odd public card
            # can be checked by the direct-profile fallback later instead.
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


def rounded_metric_bounds(display: str | None):
    """Return the numeric interval represented by a rounded k/m/b display."""
    if not display:
        return None
    match = NUMBER_RE.search(str(display))
    if not match or not match.group(2):
        return None
    raw = match.group(1).replace(",", "")
    suffix = match.group(2).lower()
    try:
        numeric = float(raw)
    except ValueError:
        return None
    decimals = len(raw.split(".", 1)[1]) if "." in raw else 0
    multiplier = {"k": 1000, "m": 1_000_000, "b": 1_000_000_000}[suffix]
    center = numeric * multiplier
    quantum = multiplier / (10 ** decimals)
    return (center - quantum / 2, center + quantum / 2)


def latest_exact_history(history_doc: dict) -> dict[str, dict]:
    """Recover the most recent non-rounded message count for each bot."""
    recovered: dict[str, dict] = {}
    snapshots = sorted(history_doc.get("snapshots", []), key=lambda s: s.get("capturedAt", ""))
    for snapshot in snapshots:
        for row in snapshot.get("bots", []):
            bot_id = row.get("id")
            if not bot_id or row.get("messages") is None or bool(row.get("messagesApproximate")):
                continue
            recovered[bot_id] = {
                "value": int(row["messages"]),
                "observedAt": row.get("exactMessagesObservedAt") or row.get("statsUpdatedAt") or snapshot.get("capturedAt"),
                "source": row.get("exactMessagesSource") or row.get("statsSource") or snapshot.get("source") or "history",
            }
    return recovered


def seed_exact_message(row: dict, recovered: dict | None = None) -> bool:
    """Keep an exact total separate from the newest rounded public estimate."""
    before = (row.get("exactMessages"), row.get("exactMessagesObservedAt"), row.get("exactMessagesSource"))
    if row.get("exactMessages") is None:
        if row.get("messages") is not None and not bool(row.get("messagesApproximate")):
            row["exactMessages"] = int(row["messages"])
            row["exactMessagesObservedAt"] = row.get("statsUpdatedAt") or row.get("observedAt")
            row["exactMessagesSource"] = row.get("statsSource") or "exact-observation"
        elif recovered:
            row["exactMessages"] = int(recovered["value"])
            row["exactMessagesObservedAt"] = recovered.get("observedAt")
            row["exactMessagesSource"] = recovered.get("source") or "history"
    after = (row.get("exactMessages"), row.get("exactMessagesObservedAt"), row.get("exactMessagesSource"))
    return before != after


def record_exact_observation(row: dict, observed: dict, now: str) -> bool:
    metric = observed.get("messages")
    if not metric or bool(metric.get("approximate")):
        return False
    if row.get("messages") != metric.get("value") or bool(row.get("messagesApproximate")):
        return False
    before = (row.get("exactMessages"), row.get("exactMessagesObservedAt"), row.get("exactMessagesSource"))
    row["exactMessages"] = int(metric["value"])
    row["exactMessagesObservedAt"] = now
    row["exactMessagesSource"] = observed.get("source") or "exact-observation"
    after = (row.get("exactMessages"), row.get("exactMessagesObservedAt"), row.get("exactMessagesSource"))
    return before != after


def history_row(row: dict) -> dict:
    keys = [
        "id",
        "name",
        "visibility",
        "messages",
        "messagesDisplay",
        "messagesApproximate",
        "exactMessages",
        "exactMessagesObservedAt",
        "exactMessagesSource",
        "statsSource",
        "statsUpdatedAt",
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
        bounds = rounded_metric_bounds(old_row.get("messagesDisplay")) if old_approx and not new_approx else None
        allow_more_precise = bool(bounds and bounds[0] <= new_value < bounds[1])
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



def apply_stats_guard(
    bot: dict,
    row: dict,
    observed: dict,
    creator_entries: dict[str, dict],
    direct_entries: dict[str, dict],
    warnings: list[str],
) -> bool:
    """Reject a known mirrored scrape and restore the curated fallback."""
    guard = bot.get("statsGuard") or {}
    if guard.get("type") != "reject-mirrored-stats":
        return False

    mirror_id = guard.get("mirrorBotId")
    fallback = guard.get("fallback") or {}
    mirror = creator_entries.get(mirror_id) or direct_entries.get(mirror_id)
    if not mirror:
        return False

    observed_messages = (observed.get("messages") or {}).get("value")
    observed_tokens = (observed.get("tokens") or {}).get("value")
    mirror_messages = (mirror.get("messages") or {}).get("value")
    mirror_tokens = (mirror.get("tokens") or {}).get("value")
    fallback_messages = fallback.get("messages")

    if observed_messages is None or mirror_messages is None or fallback_messages is None:
        return False
    if observed_messages != mirror_messages:
        return False
    if observed_tokens is not None and mirror_tokens is not None and observed_tokens != mirror_tokens:
        return False
    if int(observed_messages) <= int(fallback_messages):
        return False

    for key in (
        "messages",
        "messagesDisplay",
        "messagesApproximate",
        "rawMessages",
        "tokens",
        "tokensDisplay",
        "tokensApproximate",
        "rawTokens",
    ):
        if key in fallback:
            row[key] = fallback[key]

    warnings.append(
        f"{bot.get('name', bot.get('id'))}: rejected mirrored stats "
        f"matching {mirror.get('name') or mirror_id}; restored curated fallback"
    )
    return True

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
        "exactMessages": None,
        "exactMessagesObservedAt": None,
        "exactMessagesSource": None,
        "tokens": None,
        "tokensDisplay": None,
        "tokensApproximate": False,
        "image": None if bot_image_hidden(bot) else bot.get("image"),
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
    archived_doc: dict,
    creator_entries: dict[str, dict],
    direct_entries: dict[str, dict],
    now: str,
):
    archived_ids = {bot.get("id") for bot in archived_doc.get("bots", []) if bot.get("id")}
    auto_added_bots = auto_add_public_bots(bots_doc, archived_doc, creator_entries, now)
    auto_added_ids = {bot["id"] for bot in auto_added_bots}
    curated_bots = bots_doc.get("bots", [])
    known_ids = {bot["id"] for bot in curated_bots} | archived_ids
    old_rows = {row["id"]: row for row in stats_doc.get("bots", []) if row.get("id")}
    recovered_exact = latest_exact_history(history_doc)
    warnings: list[str] = []
    changed_bot_ids: set[str] = set()
    milestones_added: list[str] = []
    visibility_changes: list[str] = []
    public_baselines_added: list[str] = []
    public_changed = False
    bots_changed = bool(auto_added_bots)
    nsfw_updates: list[str] = []
    public_doc["schemaVersion"] = max(2, int(public_doc.get("schemaVersion") or 1))
    public_doc["note"] = (
        "Public dates are confirmed from SpicyChat approval emails when publicSinceAccuracy is confirmed. "
        "Message baselines are kept separately because the first saved message count can be later than the approval time."
    )
    public_entries = public_doc.setdefault("bots", [])
    public_by_id = {item.get("id"): item for item in public_entries if item.get("id")}

    milestones = events_doc.get("milestones") or MILESTONES_DEFAULT
    new_rows = []

    for bot in curated_bots:
        bot_id = bot["id"]
        previous = copy.deepcopy(old_rows.get(bot_id) or make_base_stat(bot))
        row = copy.deepcopy(previous)
        exact_seeded = seed_exact_message(row, recovered_exact.get(bot_id))
        observed = creator_entries.get(bot_id) or direct_entries.get(bot_id)

        if observed and isinstance(observed.get("nsfw"), bool):
            if bot.get("nsfw") != observed["nsfw"]:
                bot["nsfw"] = observed["nsfw"]
                bots_changed = True
                nsfw_updates.append(f"{bot.get('name', bot_id)}: {'NSFW' if observed['nsfw'] else 'SFW'}")

        if observed:
            old_messages = previous.get("messages")
            guard_changed = apply_stats_guard(
                bot, row, observed, creator_entries, direct_entries, warnings
            )
            if guard_changed:
                message_changed = (
                    row.get("messages") != previous.get("messages")
                    or row.get("messagesDisplay") != previous.get("messagesDisplay")
                    or bool(row.get("messagesApproximate")) != bool(previous.get("messagesApproximate"))
                )
                token_changed = (
                    row.get("tokens") != previous.get("tokens")
                    or row.get("tokensDisplay") != previous.get("tokensDisplay")
                    or bool(row.get("tokensApproximate")) != bool(previous.get("tokensApproximate"))
                )
            else:
                row, message_changed = safe_message_update(row, observed, warnings)
                token_changed = update_token_metric(row, observed)

            exact_changed = record_exact_observation(row, observed, now)

            # Appearing on the public creator profile is enough to confirm public visibility.
            visibility_changed = False
            old_visibility = row.get("visibility", "unknown")
            if observed["source"] in PUBLIC_DISCOVERY_SOURCES and old_visibility != "public":
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
                        "source": observed["source"],
                    },
                )

            # Save the first public message baseline once. Direct chatbot pages can also
            # belong to unlisted bots, so only the creator listing confirms public status.
            # If publication was confirmed separately (for example by an approval email)
            # before we had a post-public message snapshot, fill that baseline on the
            # first observation at/after the confirmed publication time.
            existing_public = public_by_id.get(bot_id)
            if existing_public and existing_public.get("messagesAtBaseline") is None and row.get("messages") is not None:
                try:
                    public_at = datetime.fromisoformat(str(existing_public.get("publicSinceAt", "")).replace("Z", "+00:00"))
                    observed_at = datetime.fromisoformat(str(now).replace("Z", "+00:00"))
                except ValueError:
                    public_at = observed_at = None
                if public_at is not None and observed_at is not None and observed_at >= public_at:
                    lag_minutes = max(0, int(round((observed_at - public_at).total_seconds() / 60)))
                    existing_public.update({
                        "baselineAt": now,
                        "messagesAtBaseline": row.get("messages"),
                        "messagesDisplayAtBaseline": row.get("messagesDisplay") or str(row.get("messages")),
                        "messagesApproximateAtBaseline": bool(row.get("messagesApproximate")),
                        "baselineAccuracy": "first-post-public-observation",
                        "baselineLagMinutes": lag_minutes,
                        "baselineSource": observed["source"],
                    })
                    public_baselines_added.append(existing_public.get("name") or row.get("name", bot_id))
                    public_changed = True

            if observed["source"] in PUBLIC_DISCOVERY_SOURCES and bot_id not in public_by_id:
                was_non_public = old_visibility not in {None, "", "unknown", "public"}
                has_baseline = row.get("messages") is not None
                baseline = {
                    "id": bot_id,
                    "name": bot.get("name", row.get("name", bot_id)),
                    "publicSinceAt": now,
                    "publicSinceAccuracy": "first-observed",
                    "publicSinceSource": observed["source"],
                    "firstPublicObservedAt": now,
                    "previousNonPublicObservedAt": stats_doc.get("capturedAt") if was_non_public else None,
                    "baselineAt": now if has_baseline else None,
                    "messagesAtBaseline": row.get("messages") if has_baseline else None,
                    "messagesDisplayAtBaseline": (row.get("messagesDisplay") or str(row.get("messages"))) if has_baseline else None,
                    "messagesApproximateAtBaseline": bool(row.get("messagesApproximate")) if has_baseline else False,
                    "baselineAccuracy": "same-observation" if has_baseline else "pending-first-post-public-observation",
                    "baselineLagMinutes": 0 if has_baseline else None,
                    "baselineSource": observed["source"] if has_baseline else None,
                    "accuracy": "first-observed",
                    "source": observed["source"],
                }
                public_entries.append(baseline)
                public_by_id[bot_id] = baseline
                public_baselines_added.append(baseline["name"])
                public_changed = True

            if bot_id in auto_added_ids or (old_messages is None and row.get("messages") is not None):
                add_event(
                    events_doc,
                    {
                        "at": now,
                        "botId": bot_id,
                        "botName": row.get("name", bot.get("name")),
                        "type": "new",
                        "source": observed.get("source") or "automatic-check",
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

            if message_changed or token_changed or visibility_changed or exact_changed or exact_seeded:
                row["statsSource"] = "stats-guard" if guard_changed else observed["source"]
                row["profileUrl"] = observed.get("profileUrl") or f"https://spicychat.ai/chatbot/{bot_id}"
                row["statsUpdatedAt"] = now
                changed_bot_ids.add(bot_id)

        # Curated fields always win. The automatic updater never rewrites them.
        row["id"] = bot_id
        row["name"] = bot.get("name", row.get("name", bot_id))
        row["title"] = bot.get("title", row.get("title", ""))
        row["url"] = bot.get("url", row.get("url", f"https://spicychat.ai/chat/{bot_id}"))
        row["image"] = None if bot_image_hidden(bot) else row.get("image", bot.get("image"))
        new_rows.append(row)

    # Any public bot with enough identity data is auto-added above.  Keep a
    # discovery queue only for records that could not be promoted safely.
    discoveries = discoveries_doc.setdefault("discoveries", [])
    by_id = {item.get("id"): item for item in discoveries if item.get("id")}
    new_discoveries = []

    # Remove discoveries that have since been added to the curated bot list.
    cleaned_discoveries = [item for item in discoveries if item.get("id") not in known_ids]
    discoveries_changed = len(cleaned_discoveries) != len(discoveries)
    discoveries_doc["discoveries"] = cleaned_discoveries
    by_id = {item.get("id"): item for item in cleaned_discoveries if item.get("id")}

    discoveries_doc["schemaVersion"] = max(2, int(discoveries_doc.get("schemaVersion") or 1))
    for bot_id, observed in sorted(creator_entries.items()):
        if bot_id in known_ids:
            continue
        existing = by_id.get(bot_id)
        override = pending_override_for(bots_doc, observed.get("name"))
        derived_hidden = bool(observed.get("nsfw"))
        patch = {
            "id": bot_id,
            "name": observed.get("name") or "Unknown bot",
            "title": observed.get("title") or None,
            "profileUrl": observed.get("profileUrl"),
            "chatUrl": observed.get("chatUrl"),
            "messagesDisplay": observed.get("messages", {}).get("display") if observed.get("messages") else None,
            "tokensDisplay": observed.get("tokens", {}).get("display") if observed.get("tokens") else None,
            "image": observed.get("image"),
            "nsfw": observed.get("nsfw") if isinstance(observed.get("nsfw"), bool) else None,
            "avatarIsNsfw": observed.get("avatarIsNsfw") if isinstance(observed.get("avatarIsNsfw"), bool) else None,
            "imageHiddenDefault": derived_hidden,
            "source": observed.get("source"),
        }
        if override.get("origin") in {"requested", "personal"}:
            patch["origin"] = override["origin"]
            patch["originSource"] = override.get("source") or "pending-override"
        patch = {key: value for key, value in patch.items() if value is not None}

        if existing:
            changed = False
            for key, value in patch.items():
                if existing.get(key) != value:
                    existing[key] = value
                    changed = True
            if changed:
                discoveries_changed = True
            continue

        item = {"firstSeenAt": now, **patch}
        discoveries_doc["discoveries"].append(item)
        by_id[bot_id] = item
        new_discoveries.append(item)
        discoveries_changed = True

    meaningful_stats_change = bool(changed_bot_ids or auto_added_bots)
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
        "botsChanged": bots_changed,
        "nsfwUpdates": nsfw_updates,
        "discoveriesChanged": discoveries_changed,
        "publicChanged": public_changed,
        "publicBaselines": public_baselines_added,
        "changedBotIds": sorted(changed_bot_ids),
        "newDiscoveries": new_discoveries,
        "autoAddedBots": auto_added_bots,
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


def build_summary(
    result: dict,
    creator_count: int,
    pages_checked: int,
    direct_checked: int,
    unavailable: list[str],
    typesense_count: int = 0,
    typesense_pages: int = 0,
    typesense_status: str = "not configured",
) -> str:
    lines = [
        "## Bot stats update",
        "",
        f"- Creator-page bots seen: **{creator_count}** across **{pages_checked}** page(s)",
        f"- Typesense public bots seen: **{typesense_count}** across **{typesense_pages}** page(s) ({typesense_status})",
        f"- Direct profiles checked: **{direct_checked}**",
        f"- Known bots updated: **{len(result['changedBotIds'])}**",
        f"- New public bots auto-added: **{len(result.get('autoAddedBots', []))}**",
        f"- Discovery items still needing metadata: **{len(result['newDiscoveries'])}**",
    ]
    if result["changedBotIds"]:
        names = {row.get("id"): row.get("name", row.get("id")) for row in result.get("newRows", [])}
        changed_names = [names.get(bot_id, bot_id) for bot_id in result["changedBotIds"]]
        lines.append(f"- Updated: **{', '.join(changed_names)}**")
    if result.get("nsfwUpdates"):
        lines.append(f"- NSFW metadata refreshed: **{', '.join(result['nsfwUpdates'])}**")
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
    if result.get("autoAddedBots"):
        lines += ["", "### Auto-added public bots"] + [
            f"- {item['name']} (`{item['id']}`){' · NSFW image hidden by default' if item.get('nsfw') else ''}"
            for item in result["autoAddedBots"]
        ]
    if result["newDiscoveries"]:
        lines += ["", "### Discovery items still needing metadata"] + [
            f"- {item['name']} (`{item['id']}`){' · NSFW' if item.get('nsfw') else ''}"
            for item in result["newDiscoveries"]
        ]
    if not result["statsChanged"] and not result["discoveriesChanged"] and not result.get("publicChanged") and not result.get("botsChanged"):
        lines += ["", "No repository data changed this run."]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creator", default="dragongraf1312")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-file")
    parser.add_argument("--fixture-creator", type=Path)
    parser.add_argument("--fixture-profile", action="append", default=[])
    parser.add_argument("--disable-typesense", action="store_true")
    parser.add_argument("--typesense-host", default=os.environ.get("SPICYCHAT_TYPESENSE_HOST", TYPESENSE_HOST_DEFAULT))
    parser.add_argument("--typesense-collection", default=os.environ.get("SPICYCHAT_TYPESENSE_COLLECTION", TYPESENSE_COLLECTION_DEFAULT))
    args = parser.parse_args()

    bots_doc = read_json(BOTS_PATH)
    stats_doc = read_json(STATS_PATH)
    history_doc = read_json(HISTORY_PATH)
    events_doc = read_json(EVENTS_PATH, {"schemaVersion": 1, "milestones": MILESTONES_DEFAULT, "events": []})
    discoveries_doc = read_json(DISCOVERIES_PATH, {"schemaVersion": 1, "discoveries": []})
    public_doc = read_json(PUBLIC_PATH, {"schemaVersion": 1, "bots": []})
    archived_doc = read_json(ARCHIVED_PATH, {"schemaVersion": 1, "bots": []})

    known_ids = {bot["id"] for bot in bots_doc.get("bots", [])}
    creator_url = f"https://spicychat.ai/creator/{args.creator}"
    playwright = browser = None

    try:
        creator_warning = None
        if args.fixture_creator:
            html = args.fixture_creator.read_text(encoding="utf-8", errors="ignore")
            page_creator_entries = parse_creator_html(html, creator_url)
            pages_checked = 1
            if len(page_creator_entries) < 5:
                raise RuntimeError(f"Fixture creator page only contained {len(page_creator_entries)} bots")
        else:
            playwright, browser = launch_browser()
            try:
                page_creator_entries, pages_checked = load_live_creator(args.creator, browser)
            except Exception as exc:
                # Typesense is a fully independent public source. If the creator
                # page has a temporary rendering/login problem, the worker can
                # still continue from Typesense instead of losing the whole run.
                page_creator_entries = {}
                pages_checked = 0
                creator_warning = str(exc)

        typesense_entries: dict[str, dict] = {}
        typesense_pages = 0
        typesense_status = "disabled" if args.disable_typesense else "not configured"
        typesense_warning = None
        typesense_key = os.environ.get("SPICYCHAT_TYPESENSE_API_KEY", "").strip()
        if not args.disable_typesense and typesense_key and not args.fixture_creator:
            try:
                typesense_entries, typesense_pages = load_typesense_creator(
                    args.creator, typesense_key, args.typesense_host, args.typesense_collection
                )
                typesense_status = "ok"
            except Exception as exc:
                typesense_status = "failed; creator-page fallback used"
                typesense_warning = str(exc)

        if not args.fixture_creator and not page_creator_entries and not typesense_entries:
            details = []
            if creator_warning:
                details.append(f"creator page: {creator_warning}")
            if typesense_warning:
                details.append(f"Typesense: {typesense_warning}")
            if not typesense_key and not args.disable_typesense:
                details.append("Typesense key is not configured")
            raise RuntimeError("No public discovery source succeeded. " + "; ".join(details))

        # Typesense is the discovery source because it includes public NSFW bots.
        # Normal creator-page rows remain a fallback and can fill anything the index omits.
        creator_entries = dict(page_creator_entries)
        for bot_id, item in typesense_entries.items():
            if bot_id in creator_entries:
                # Prefer Typesense's exact message total whenever it is available.
                # The creator page often rounds values to strings such as 3.1k;
                # keeping the rounded value just because 3100 is numerically above
                # an exact 3097 would throw away the more precise observation.
                # The normal regression guard below still protects against genuinely
                # stale/lower exact values.
                creator_item = creator_entries[bot_id]
                merged = {**creator_item, **item}
                creator_messages = creator_item.get("messages")
                typesense_messages = item.get("messages")
                if typesense_messages and not typesense_messages.get("approximate"):
                    merged["messages"] = typesense_messages
                elif creator_messages and (
                    not typesense_messages
                    or creator_messages.get("value", -1) > typesense_messages.get("value", -1)
                ):
                    merged["messages"] = creator_messages
                if not item.get("tokens") and creator_item.get("tokens"):
                    merged["tokens"] = creator_item["tokens"]
                creator_entries[bot_id] = merged
            else:
                creator_entries[bot_id] = item

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
            archived_doc,
            creator_entries,
            direct_entries,
            now,
        )

        if creator_warning:
            result["warnings"].append(f"Creator page: {creator_warning}; Typesense data used where available")
        if typesense_warning:
            result["warnings"].append(f"Typesense: {typesense_warning}")

        summary = build_summary(
            result, len(page_creator_entries), pages_checked, direct_checked, unavailable,
            len(typesense_entries), typesense_pages, typesense_status,
        )
        print(summary)
        for warning in result["warnings"]:
            print(f"::warning::{warning}")
        for bot_id in unavailable:
            print(f"::notice::Direct profile unavailable: {bot_id}")

        if args.summary_file:
            Path(args.summary_file).write_text(summary, encoding="utf-8")

        if not args.dry_run:
            if result.get("botsChanged"):
                write_json(BOTS_PATH, bots_doc)
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
