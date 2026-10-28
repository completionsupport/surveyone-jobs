"""Fast publication tests use isolated files and never call a live service."""

import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from jobs.collector import sync_editorial as fast
from jobs.collector.main import load, save
from jobs.collector.model import iso


class FastEditorialPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.feed = self.root / "public/jobs/jobs.json"
        self.state = self.root / "jobs/state.json"
        self.now = datetime.now(timezone.utc)
        self.employer = dict(id="source-job", title="Surveyor", company="Original employer",
                             discoveredAt=iso(self.now - timedelta(days=1)),
                             applyUrl="https://careers.example.org/job", extra={"keep": True})
        self.job = dict(id="editorial_" + "a" * 32, revision=2, origin="EDITORIAL",
                        title="Admin vacancy", postedAt=iso(self.now), discoveredAt=iso(self.now),
                        expiresAt=iso(self.now + timedelta(days=30)), phoneE164="+201234567890")
        self.initial_state = dict(seen=["source-job"], pending=["source-job"], notified=["older"],
                                  sourceCursor="employer", sourceHealth={"employer": {"status": "healthy"}},
                                  deliveryReservations={"private": "keep"})
        save(self.feed, dict(version=1, totalJobs=1, generatedAt=iso(self.now), expiryDays=45,
                             extraFeedMetadata="keep", jobs=[self.employer]))
        save(self.state, self.initial_state)

    def tearDown(self):
        self.temp.cleanup()

    def run_sync(self, jobs=None, status="healthy"):
        values = jobs if jobs is not None else [self.job]
        with patch.object(fast, "load_editorial", return_value=(values, dict(status=status, activeJobs=len(values)))):
            return fast.sync(self.root)

    def test_publish_preserves_all_employer_fields_metadata_and_notification_state(self):
        summary = self.run_sync()
        feed = load(self.feed, {})
        self.assertEqual([self.job, self.employer], feed["jobs"])
        self.assertEqual(2, feed["totalJobs"])
        self.assertEqual("keep", feed["extraFeedMetadata"])
        self.assertEqual(45, feed["expiryDays"])
        state = load(self.state, {})
        state.pop("editorialFeed")
        self.assertEqual(self.initial_state, state)
        self.assertFalse(summary["notificationsSent"])

    def test_edit_pause_and_republish_replace_the_authoritative_record(self):
        self.run_sync()
        changed = {**self.job, "title": "Updated vacancy", "revision": 3}
        self.run_sync([changed])
        self.assertEqual([changed, self.employer], load(self.feed, {})["jobs"])
        self.run_sync([])
        self.assertEqual([self.employer], load(self.feed, {})["jobs"])
        self.run_sync([changed])
        self.assertEqual([changed, self.employer], load(self.feed, {})["jobs"])

    def test_repeat_snapshot_does_not_rewrite_the_feed_or_change_generated_time(self):
        self.run_sync()
        before = self.feed.read_bytes()
        with patch.object(fast, "save", wraps=fast.save) as write:
            self.assertFalse(self.run_sync()["changed"])
        self.assertEqual(before, self.feed.read_bytes())
        self.assertEqual([self.state], [call.args[0] for call in write.call_args_list])

    def test_unavailable_or_disabled_feed_does_not_restore_cached_contacts(self):
        for status in ["unavailable", "disabled"]:
            with self.subTest(status=status):
                self.run_sync()
                self.run_sync([], status)
                self.assertEqual([self.employer], load(self.feed, {})["jobs"])
                self.assertEqual(status, load(self.state, {})["editorialFeed"]["status"])

    def test_malformed_base_feed_fails_before_network_or_writes(self):
        original = load(self.feed, {})
        for change in [dict(version=2), dict(totalJobs=99), dict(jobs=[None], totalJobs=1), dict(jobs=[{}], totalJobs=1)]:
            with self.subTest(change=change):
                save(self.feed, {**original, **change})
                before = self.feed.read_bytes(), self.state.read_bytes()
                with patch.object(fast, "load_editorial") as network, self.assertRaises(ValueError):
                    fast.sync(self.root)
                network.assert_not_called()
                self.assertEqual(before, (self.feed.read_bytes(), self.state.read_bytes()))

    def test_large_merge_is_refused_without_changing_either_file(self):
        before = self.feed.read_bytes(), self.state.read_bytes()
        with patch.object(fast, "MAX_FEED_BYTES", self.feed.stat().st_size + 10), self.assertRaises(ValueError):
            self.run_sync()
        self.assertEqual(before, (self.feed.read_bytes(), self.state.read_bytes()))
        with self.assertRaises(ValueError):
            self.run_sync([{**self.job, "id": f"editorial_{i:032x}"} for i in range(10001)])
        self.assertEqual(before, (self.feed.read_bytes(), self.state.read_bytes()))

    def test_missing_base_feed_or_invalid_state_never_creates_replacement_feed(self):
        self.feed.unlink()
        with patch.object(fast, "load_editorial") as network, self.assertRaises(ValueError):
            fast.sync(self.root)
        network.assert_not_called()
        self.assertFalse(self.feed.exists())
        save(self.feed, dict(version=1, totalJobs=0, jobs=[]))
        save(self.state, [])
        with patch.object(fast, "load_editorial") as network, self.assertRaises(ValueError):
            fast.sync(self.root)
        network.assert_not_called()

    def test_editorial_jobs_never_enter_automatic_notification_pending_or_seen(self):
        self.run_sync()
        state = load(self.state, {})
        self.assertNotIn(self.job["id"], state["pending"])
        self.assertNotIn(self.job["id"], state["seen"])
        self.assertNotIn(self.job["id"], state["notified"])


if __name__ == "__main__":
    unittest.main()
