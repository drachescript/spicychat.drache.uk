"""Offline regression tests for the incremental public-date worker."""
import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gmail_sync", ROOT / "scripts/update-public-dates-from-gmail.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Request:
    def __init__(self, result):
        self.result = result

    def execute(self, **kwargs):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Gmail:
    def __init__(self, ids, fail=None):
        self.ids = ids
        self.fail = fail
        self.reads = []
        self.queries = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        self.queries.append(kwargs["q"])
        return Request({"messages": [{"id": i} for i in self.ids]})

    def get(self, **kwargs):
        mid = kwargs["id"]
        self.reads.append(mid)
        if mid == self.fail:
            return Request(RuntimeError("simulated transport error"))
        raw = ("From: support@spicychat.ai\r\nSubject: Your character is live\r\n"
               "Date: Tue, 1 Sep 2026 12:00:00 +0000\r\n"
               "Content-Type: text/plain; charset=utf-8\r\n\r\n"
               f"Great news - your character Bot {mid} has been approved and is now live on SpicyChat")
        return Request({"raw": base64.urlsafe_b64encode(raw.encode()).decode()})


class SyncTests(unittest.TestCase):
    def setUp(self):
        from cryptography.fernet import Fernet
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.enc"
        self.cipher = Fernet(Fernet.generate_key())
        self.now = 1790000000

    def tearDown(self):
        self.temp.cleanup()

    def store(self, **kwargs):
        return m.StateStore(self.path, self.cipher, **kwargs)

    def budget(self, raw=40):
        return m.RequestBudget(max_raw=raw, interval=0, sleep=lambda _: None)

    def test_bootstrap_resume_and_overlap_no_rereads(self):
        store = self.store()
        gmail = Gmail(["a", "b", "c"])
        self.assertFalse(m.sync(gmail, store, self.budget(2), self.now))
        self.assertEqual(gmail.reads, ["a", "b"])
        self.assertNotIn(b"Bot a", self.path.read_bytes())
        store = self.store()
        self.assertTrue(m.sync(gmail, store, self.budget(), self.now + 21600))
        self.assertEqual(gmail.reads, ["a", "b", "c"])
        self.assertIn("after:", gmail.queries[-1])
        self.assertEqual(len(m.cached_approvals(store.data)), 3)
        self.assertTrue(m.sync(gmail, self.store(), self.budget(), self.now + 43200))
        self.assertEqual(gmail.reads, ["a", "b", "c"])

    def test_error_keeps_pending_and_cached_approvals(self):
        gmail = Gmail(["a", "b"], fail="b")
        with self.assertRaises(RuntimeError):
            m.sync(gmail, self.store(), self.budget(), self.now)
        resumed = self.store()
        self.assertIn("a", resumed.data["messages"])
        self.assertIn("b", resumed.data["pending"])
        gmail.fail = None
        self.assertTrue(m.sync(gmail, resumed, self.budget(), self.now + 21600))
        self.assertEqual(gmail.reads.count("a"), 1)

    def test_readonly_does_not_write(self):
        m.sync(Gmail(["a"]), self.store(readonly=True), self.budget(), self.now)
        self.assertFalse(self.path.exists())

    def test_wrong_key_fails_closed(self):
        from cryptography.fernet import Fernet
        m.sync(Gmail(["a"]), self.store(), self.budget(), self.now)
        with self.assertRaises(RuntimeError):
            m.StateStore(self.path, Fernet(Fernet.generate_key()))

    def test_cached_approval_waits_for_public_observation(self):
        store = self.store()
        gmail = Gmail(["a"])
        self.assertTrue(m.sync(gmail, store, self.budget(), self.now))
        approvals = m.cached_approvals(store.data)
        bots = {"bots": [{"id": "bot-a", "name": "Bot a"}]}
        public = {"bots": []}
        self.assertFalse(m.evaluate(approvals, bots, public)[1])
        public["bots"].append({"id": "bot-a", "name": "Bot a",
                               "publicSinceAt": "2026-09-02T12:00:00+00:00",
                               "publicSinceAccuracy": "first-observed",
                               "firstPublicObservedAt": "2026-09-02T12:00:00+00:00"})
        updates = m.evaluate(m.cached_approvals(self.store().data), bots, public)[1]
        self.assertEqual(m.apply_updates(public, updates), 1)
        self.assertEqual(public["bots"][0]["publicSinceAt"], "2026-09-01T12:00:00+00:00")
        self.assertFalse(m.evaluate(approvals, bots, public)[1])


if __name__ == "__main__":
    unittest.main()
