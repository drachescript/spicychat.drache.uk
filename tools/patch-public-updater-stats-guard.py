#!/usr/bin/env python3
"""One-time patch for scripts/update-public-stats.py.

Makes the public GitHub updater honor bots.json statsGuard entries of type
"reject-mirrored-stats" so a known mirrored scrape can be corrected back to
its curated fallback instead of being written as real growth.

Run from the repository root:
    python tools/patch-public-updater-stats-guard.py
"""
from pathlib import Path

path = Path("scripts/update-public-stats.py")
if not path.exists():
    raise SystemExit("Could not find scripts/update-public-stats.py. Run this from the repository root.")

text = path.read_text(encoding="utf-8")

helper = '''\n\ndef apply_stats_guard(\n    bot: dict,\n    row: dict,\n    observed: dict,\n    creator_entries: dict[str, dict],\n    direct_entries: dict[str, dict],\n    warnings: list[str],\n) -> bool:\n    """Reject a known mirrored scrape and restore the curated fallback."""\n    guard = bot.get("statsGuard") or {}\n    if guard.get("type") != "reject-mirrored-stats":\n        return False\n\n    mirror_id = guard.get("mirrorBotId")\n    fallback = guard.get("fallback") or {}\n    mirror = creator_entries.get(mirror_id) or direct_entries.get(mirror_id)\n    if not mirror:\n        return False\n\n    observed_messages = (observed.get("messages") or {}).get("value")\n    observed_tokens = (observed.get("tokens") or {}).get("value")\n    mirror_messages = (mirror.get("messages") or {}).get("value")\n    mirror_tokens = (mirror.get("tokens") or {}).get("value")\n    fallback_messages = fallback.get("messages")\n\n    if observed_messages is None or mirror_messages is None or fallback_messages is None:\n        return False\n    if observed_messages != mirror_messages:\n        return False\n    if observed_tokens is not None and mirror_tokens is not None and observed_tokens != mirror_tokens:\n        return False\n    if int(observed_messages) <= int(fallback_messages):\n        return False\n\n    for key in (\n        "messages",\n        "messagesDisplay",\n        "messagesApproximate",\n        "rawMessages",\n        "tokens",\n        "tokensDisplay",\n        "tokensApproximate",\n        "rawTokens",\n    ):\n        if key in fallback:\n            row[key] = fallback[key]\n\n    warnings.append(\n        f"{bot.get('name', bot.get('id'))}: rejected mirrored stats "\n        f"matching {mirror.get('name') or mirror_id}; restored curated fallback"\n    )\n    return True\n'''

marker = "\ndef make_base_stat(bot: dict) -> dict:\n"
if "def apply_stats_guard(" not in text:
    if marker not in text:
        raise SystemExit("Updater layout changed: could not find make_base_stat(). No file was changed.")
    text = text.replace(marker, helper + marker, 1)

old_block = '''        if observed:\n            old_messages = previous.get("messages")\n            row, message_changed = safe_message_update(row, observed, warnings)\n            token_changed = update_token_metric(row, observed)\n'''
new_block = '''        if observed:\n            old_messages = previous.get("messages")\n            guard_changed = apply_stats_guard(\n                bot, row, observed, creator_entries, direct_entries, warnings\n            )\n            if guard_changed:\n                message_changed = (\n                    row.get("messages") != previous.get("messages")\n                    or row.get("messagesDisplay") != previous.get("messagesDisplay")\n                    or bool(row.get("messagesApproximate")) != bool(previous.get("messagesApproximate"))\n                )\n                token_changed = (\n                    row.get("tokens") != previous.get("tokens")\n                    or row.get("tokensDisplay") != previous.get("tokensDisplay")\n                    or bool(row.get("tokensApproximate")) != bool(previous.get("tokensApproximate"))\n                )\n            else:\n                row, message_changed = safe_message_update(row, observed, warnings)\n                token_changed = update_token_metric(row, observed)\n'''
if old_block in text:
    text = text.replace(old_block, new_block, 1)
elif "guard_changed = apply_stats_guard(" not in text:
    raise SystemExit("Updater layout changed: could not find the stats-update block. No file was changed.")

old_source = '                row["statsSource"] = observed["source"]\n'
new_source = '                row["statsSource"] = "stats-guard" if guard_changed else observed["source"]\n'
if old_source in text:
    text = text.replace(old_source, new_source, 1)
elif new_source not in text:
    raise SystemExit("Updater layout changed: could not find statsSource assignment. No file was changed.")

# Compile check before writing.
compile(text, str(path), "exec")
path.write_text(text, encoding="utf-8")
print("Patched scripts/update-public-stats.py to honor statsGuard.")
