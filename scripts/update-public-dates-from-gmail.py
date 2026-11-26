#!/usr/bin/env python3
"""Incrementally confirm public dates using the existing conservative scanner."""
from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import os
import random
import sys
import time
from datetime import datetime
from email import policy
from email.parser import BytesParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.scan_gmail_public_dates import (
    Approval, apply_updates, dedupe_approvals, evaluate,
    extract_message_approval, load_json,
)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
GMAIL_QUERY = 'from:support@spicychat.ai subject:"Your character is live"'
STATE_PATH = ".github/gmail-public-date-state.enc"
OVERLAP = 48 * 3600
RECONCILE_INTERVAL = 30 * 86400
INDEX_DELAY = 120
MAX_RAW = 40
MAX_LIST = 10
REQUEST_INTERVAL = 3.25
MAX_PARSE_ATTEMPTS = 3


def require_env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def gmail_service():
    import httplib2
    from google.oauth2.credentials import Credentials
    from google_auth_httplib2 import AuthorizedHttp
    from googleapiclient.discovery import build

    creds = Credentials(
        token=None,
        refresh_token=require_env("GMAIL_REFRESH_TOKEN"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=require_env("GMAIL_CLIENT_ID"),
        client_secret=require_env("GMAIL_CLIENT_SECRET"),
        scopes=SCOPES,
    )
    return build("gmail", "v1", http=AuthorizedHttp(creds, http=httplib2.Http(timeout=25)),
                 cache_discovery=False)


def state_cipher():
    from cryptography.fernet import Fernet
    # An optional dedicated high-entropy secret avoids coupling state to OAuth
    # refresh-token rotation. Existing deployments work without a new secret.
    secret = os.environ.get("GMAIL_SYNC_STATE_KEY", "").strip() or require_env("GMAIL_REFRESH_TOKEN")
    key = hashlib.sha256(b"spicychat-public-date-state-v1\0" + secret.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def new_state():
    return {"schema": 1, "cursor": 0, "last_full": 0, "scan": None,
            "pending": {}, "messages": {}}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(temp, path)


class StateStore:
    def __init__(self, path, cipher, reset=False, readonly=False):
        self.path = path
        self.cipher = cipher
        self.readonly = readonly
        if path.exists() and not reset:
            try:
                self.data = json.loads(cipher.decrypt(path.read_bytes().strip()))
                if self.data.get("schema") != 1:
                    raise ValueError("Unsupported schema")
                if not isinstance(self.data["pending"], dict) or not isinstance(self.data["messages"], dict):
                    raise ValueError("Invalid state")
            except Exception:
                # Never silently discard a damaged or differently encrypted checkpoint.
                raise RuntimeError("Cannot decrypt or validate Gmail sync state; restore the key/state or explicitly reset it") from None
            self.saved = canonical(self.data)
        else:
            self.data = new_state()
            self.saved = None

    def save(self):
        payload = canonical(self.data)
        if not self.readonly and payload != self.saved:
            atomic_write(self.path, self.cipher.encrypt(payload) + b"\n")
            self.saved = payload


class BudgetExhausted(Exception):
    pass


def status_of(exc):
    return getattr(getattr(exc, "resp", None), "status", None)


def retryable(exc):
    status = status_of(exc)
    if status in (429, 500, 502, 503, 504):
        return True
    if status == 403:
        detail = str(exc).lower()
        return any(reason in detail for reason in ("ratelimit", "quota", "rate limit", "userratelimit"))
    return isinstance(exc, (TimeoutError, OSError))


class RequestBudget:
    def __init__(self, max_raw=MAX_RAW, max_list=MAX_LIST, interval=REQUEST_INTERVAL,
                 sleep=time.sleep, clock=time.monotonic):
        self.limits = {"raw": max_raw, "list": max_list}
        self.counts = {"raw": 0, "list": 0}
        self.interval, self.sleep, self.clock = interval, sleep, clock
        self.last = None
        self.retries = 0

    def call(self, kind, request):
        for attempt in range(3):
            if self.counts[kind] >= self.limits[kind]:
                raise BudgetExhausted(kind)
            if self.last is not None:
                self.sleep(max(0, self.interval - (self.clock() - self.last)))
            self.last = self.clock()
            self.counts[kind] += 1
            try:
                return request().execute(num_retries=0)
            except Exception as exc:
                if not retryable(exc) or attempt == 2:
                    raise
                if self.counts[kind] >= self.limits[kind]:
                    raise BudgetExhausted(kind) from None
                self.retries += 1
                delay = min(30, 2 ** (attempt + 2)) + random.random()
                try:
                    delay = max(delay, float(exc.resp.get("retry-after", 0)))
                except (AttributeError, TypeError, ValueError):
                    pass
                # Long Retry-After: stop this run rather than holding the runner.
                if delay > 60:
                    raise
                self.sleep(delay)


def discover(service, store, budget, now, full=False):
    state = store.data
    if full and state["scan"] is not None and not state["scan"]["full"]:
        state["scan"] = None
    if state["scan"] is None:
        cutoff = max(0, now - INDEX_DELAY)
        if cutoff <= state["cursor"]:
            return True
        reconcile = full or not state["last_full"] or now - state["last_full"] >= RECONCILE_INTERVAL
        state["scan"] = {
            "lower": 0 if reconcile else max(0, state["cursor"] - OVERLAP - 1),
            "upper": cutoff, "full": reconcile, "page": None,
        }
        store.save()

    scan = state["scan"]
    query = GMAIL_QUERY + f" before:{scan['upper']}"
    if scan["lower"]:
        query += f" after:{scan['lower']}"
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500,
                  "fields": "messages(id),nextPageToken"}
        if scan["page"]:
            kwargs["pageToken"] = scan["page"]
        try:
            result = budget.call("list", lambda: service.users().messages().list(**kwargs))
        except BudgetExhausted:
            return False
        except Exception as exc:
            if status_of(exc) == 400 and scan["page"]:
                # Expired/invalid token: repeat the fixed window. Cached IDs
                # ensure already discovered/fetched messages aren't downloaded again.
                scan["page"] = None
                store.save()
                return False
            raise
        for item in result.get("messages", []):
            message_id = str(item.get("id") or "")
            if message_id and message_id not in state["messages"]:
                state["pending"].setdefault(message_id, {"attempts": 0})
        scan["page"] = result.get("nextPageToken")
        if not scan["page"]:
            state["cursor"] = scan["upper"]
            if scan["full"]:
                state["last_full"] = scan["upper"]
            state["scan"] = None
            store.save()
            return True
        store.save()


def read_approval(service, message_id, budget):
    item = budget.call("raw", lambda: service.users().messages().get(
        userId="me", id=message_id, format="raw", fields="raw"))
    raw = item.get("raw")
    if not raw:
        return []
    try:
        data = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        message = BytesParser(policy=policy.default).parsebytes(data)
        # Preserve the existing parser, including its Date-header semantics.
        return extract_message_approval(message, Path("gmail-api.eml"), "gmail-api")
    except (ValueError, TypeError, LookupError, UnicodeError, binascii.Error):
        return []


def process_pending(service, store, budget, now):
    state = store.data
    for message_id, pending in list(state["pending"].items()):
        if pending.get("retry_after", 0) > now:
            continue
        try:
            found = read_approval(service, message_id, budget)
        except BudgetExhausted:
            return
        except Exception as exc:
            if status_of(exc) != 404:
                # Do not advance past a failed API read. Retain the ID and stop
                # on quota/auth/network errors instead of hammering Gmail.
                raise
            found = []
        if found:
            state["messages"][message_id] = {
                "approvals": [{"name": a.character_name, "date": a.iso} for a in found]
            }
            del state["pending"][message_id]
        else:
            pending["attempts"] = pending.get("attempts", 0) + 1
            if pending["attempts"] >= MAX_PARSE_ATTEMPTS:
                # Visible, recoverable quarantine; never claim a failed parse
                # was a valid approval. Manual retry is available.
                state["messages"][message_id] = {"unresolved": True}
                del state["pending"][message_id]
            else:
                pending["retry_after"] = now + 6 * 3600
        store.save()


def cached_approvals(state):
    rows = []
    for record in state["messages"].values():
        for a in record.get("approvals", []):
            rows.append(Approval(a["name"], datetime.fromisoformat(a["date"]),
                                 "gmail-api.eml", "gmail-api"))
    return dedupe_approvals(rows)


def retry_unresolved(store):
    state = store.data
    for message_id, record in list(state["messages"].items()):
        if record.get("unresolved"):
            state["pending"][message_id] = {"attempts": 0}
            del state["messages"][message_id]
    store.save()


def sync(service, store, budget, now, full=False):
    complete = discover(service, store, budget, now, full)
    process_pending(service, store, budget, now)
    # Don't select a later approval while an earlier historical candidate
    # could still be in the discovery queue.
    return complete and not store.data["pending"]


def write_summary(path, state, budget, approvals, report, applied, complete, error):
    counts = {}
    for row in report:
        counts[row.status] = counts.get(row.status, 0) + 1
    unresolved = sum(bool(r.get("unresolved")) for r in state["messages"].values())
    lines = [
        "## Gmail public-date sync", "",
        f"- Gmail list requests (including retries): **{budget.counts['list']}**",
        f"- Gmail raw reads (including retries): **{budget.counts['raw']}**",
        f"- Retried API calls: **{budget.retries}**",
        f"- Cached distinct approvals: **{len(approvals)}**",
        f"- Pending messages: **{len(state['pending'])}**",
        f"- Quarantined messages (manual retry available): **{unresolved}**",
        f"- Discovery window still open: **{state['scan'] is not None}**",
        f"- Ready to evaluate: **{complete}**",
        f"- Updates applied: **{applied}**",
    ]
    if error:
        lines.append("- Sync stopped with an API/state error; saved progress will be retried.")
    if unresolved:
        lines.append("- Warning: unresolved matching messages could not be parsed or were unavailable. Review before relying on complete historical coverage.")
    if counts:
        lines += ["", "### Matching results"]
        lines += [f"- {key}: {counts[key]}" for key in sorted(counts)]
    output = "\n".join(lines) + "\n"
    print(output, end="")
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--repo", default=str(ROOT))
    p.add_argument("--scan-only", action="store_true", help="Do not write public data or sync state")
    p.add_argument("--summary-file")
    p.add_argument("--full-rescan", action="store_true", help="Reconcile all historical IDs without rereading cached messages")
    p.add_argument("--retry-unresolved", action="store_true")
    p.add_argument("--reset-state", action="store_true", help="Explicitly rebuild encrypted state; confirmed dates are preserved")
    return p.parse_args()


def main():
    args = parse_args()
    root = Path(args.repo).expanduser().resolve()
    public_path = root / "assets/data/bot-public.json"
    bots_path = root / "assets/data/bots.json"
    if not public_path.is_file() or not bots_path.is_file():
        print("Missing bot data")
        return 2
    budget = RequestBudget()
    summary_path = Path(args.summary_file) if args.summary_file else None
    store = None
    approvals, report, applied, complete = [], [], 0, False
    error = False
    try:
        store = StateStore(root / STATE_PATH, state_cipher(), args.reset_state, args.scan_only)
        if args.retry_unresolved:
            retry_unresolved(store)
        # Checkpoint is retained even if a subsequent API call fails.
        complete = sync(gmail_service(), store, budget, int(time.time()), args.full_rescan)
        approvals = cached_approvals(store.data)
        if complete:
            bots_data, public_data = load_json(bots_path), load_json(public_path)
            report, updates = evaluate(approvals, bots_data, public_data)
            if updates and not args.scan_only:
                applied = apply_updates(public_data, updates)
                if applied:
                    atomic_write(public_path, (json.dumps(public_data, indent=2, ensure_ascii=False) + "\n").encode())
    except Exception as exc:
        error = True
        # Public Actions logs must not contain Gmail IDs, bodies, URLs or names.
        print(f"Sync stopped: {type(exc).__name__}; HTTP status: {status_of(exc) or 'n/a'}")
        if store is not None:
            store.save()
    write_summary(summary_path, store.data if store else new_state(), budget,
                  approvals, report, applied, complete, error)
    return 3 if error else 0


if __name__ == "__main__":
    raise SystemExit(main())
