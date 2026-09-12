#!/usr/bin/env python3
"""One-time safety patch for scripts/update-public-stats.py.

Fixes two failure modes seen on SpicyChat creator pages:
1. A card lookup could climb into the whole grid and read another bot's metrics.
2. bots.json statsGuard entries were not enforced by the GitHub updater.

Run from the repository root:
    python tools/patch-public-updater-card-safety.py

The patch is idempotent and compiles the updater before writing it.
"""
from pathlib import Path

path = Path("scripts/update-public-stats.py")
if not path.exists():
    raise SystemExit("Could not find scripts/update-public-stats.py. Run this from the repository root.")

text = path.read_text(encoding="utf-8")
changed = False

old_card = '''        card = None
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
'''

new_card = '''        card = None
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
'''

if old_card in text:
    text = text.replace(old_card, new_card, 1)
    changed = True
elif "A real bot card has exactly one character-info link" not in text:
    raise SystemExit("Updater layout changed: could not find creator-card lookup. No file was changed.")

helper = '''\n\ndef apply_stats_guard(\n    bot: dict,\n    row: dict,\n    observed: dict,\n    creator_entries: dict[str, dict],\n    direct_entries: dict[str, dict],\n    warnings: list[str],\n) -> bool:\n    \"\"\"Reject a known mirrored scrape and restore the curated fallback.\"\"\"\n    guard = bot.get("statsGuard") or {}\n    if guard.get("type") != "reject-mirrored-stats":\n        return False\n\n    mirror_id = guard.get("mirrorBotId")\n    fallback = guard.get("fallback") or {}\n    mirror = creator_entries.get(mirror_id) or direct_entries.get(mirror_id)\n    if not mirror:\n        return False\n\n    observed_messages = (observed.get("messages") or {}).get("value")\n    observed_tokens = (observed.get("tokens") or {}).get("value")\n    mirror_messages = (mirror.get("messages") or {}).get("value")\n    mirror_tokens = (mirror.get("tokens") or {}).get("value")\n    fallback_messages = fallback.get("messages")\n\n    if observed_messages is None or mirror_messages is None or fallback_messages is None:\n        return False\n    if observed_messages != mirror_messages:\n        return False\n    if observed_tokens is not None and mirror_tokens is not None and observed_tokens != mirror_tokens:\n        return False\n    if int(observed_messages) <= int(fallback_messages):\n        return False\n\n    for key in (\n        "messages",\n        "messagesDisplay",\n        "messagesApproximate",\n        "rawMessages",\n        "tokens",\n        "tokensDisplay",\n        "tokensApproximate",\n        "rawTokens",\n    ):\n        if key in fallback:\n            row[key] = fallback[key]\n\n    warnings.append(\n        f"{bot.get('name', bot.get('id'))}: rejected mirrored stats "\n        f"matching {mirror.get('name') or mirror_id}; restored curated fallback"\n    )\n    return True\n'''

marker = "\ndef make_base_stat(bot: dict) -> dict:\n"
if "def apply_stats_guard(" not in text:
    if marker not in text:
        raise SystemExit("Updater layout changed: could not find make_base_stat(). No file was changed.")
    text = text.replace(marker, helper + marker, 1)
    changed = True

old_update = '''        if observed:
            old_messages = previous.get("messages")
            row, message_changed = safe_message_update(row, observed, warnings)
            token_changed = update_token_metric(row, observed)
'''
new_update = '''        if observed:
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
'''
if old_update in text:
    text = text.replace(old_update, new_update, 1)
    changed = True
elif "guard_changed = apply_stats_guard(" not in text:
    raise SystemExit("Updater layout changed: could not find stats update block. No file was changed.")

old_source = '                row["statsSource"] = observed["source"]\n'
new_source = '                row["statsSource"] = "stats-guard" if guard_changed else observed["source"]\n'
if old_source in text:
    text = text.replace(old_source, new_source, 1)
    changed = True
elif new_source not in text:
    raise SystemExit("Updater layout changed: could not find statsSource assignment. No file was changed.")

compile(text, str(path), "exec")
if changed:
    path.write_text(text, encoding="utf-8")
    print("Patched scripts/update-public-stats.py: strict card boundaries + statsGuard support.")
else:
    print("scripts/update-public-stats.py already contains this safety fix.")
