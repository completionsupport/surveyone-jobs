"""Offline-only editorial jobs integration; never calls production or sends FCM."""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
from jobs.collector import editorial, main, notify
from jobs.collector.model import iso


def row(now, **changes):
    return dict(id="editorial_" + "a" * 32, revision=2, origin="EDITORIAL", title="Land Surveyor", company="Survey Co",
                city="Cairo", country="Egypt", countryCode="EG", category="Land Surveying", description="Survey works.",
                employmentType="Full-time", contactName="Recruiter", phoneE164="+201234567890", allowCall=True,
                allowWhatsApp=False, externalApplyUrl="", postedAt=iso(now), discoveredAt=iso(now),
                expiresAt=iso(now + timedelta(days=30)), **changes)


def snapshot(now, rows=None):
    rows = rows if rows is not None else [row(now)]
    return dict(version=1, origin="EDITORIAL", authoritative=True, totalJobs=len(rows), generatedAt=iso(now), jobs=rows)


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)

    def test_legacy_compatible_url_direct_contact_and_strict_whatsapp_opt_in(self):
        job = editorial.parse_snapshot(snapshot(self.now), self.now)[0]
        self.assertEqual("https://surveyone.app/en/job/?id=" + job["id"], job["applyUrl"])
        self.assertEqual("+201234567890", job["phoneE164"])
        self.assertIs(job["allowWhatsApp"], False)
        self.assertEqual("Cairo, Egypt", job["location"])

    def test_partial_stale_or_untrusted_snapshot_is_rejected(self):
        for change in [dict(version=2), dict(authoritative=False), dict(origin="OTHER"), dict(totalJobs=12),
                       dict(generatedAt=iso(self.now - timedelta(hours=1))), dict(generatedAt=iso(self.now + timedelta(hours=1)))]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                editorial.parse_snapshot({**snapshot(self.now), **change}, self.now)
        for change in [dict(origin="OTHER"), dict(id="random"), dict(revision=True), dict(status="PAUSED"),
                       dict(phoneE164="01000000000"), dict(allowWhatsApp="true"), dict(allowCall=False),
                       dict(countryCode="eg"), dict(expiresAt=""), dict(externalApplyUrl="javascript:alert(1)"),
                       dict(externalApplyUrl="https://127.0.0.1/"), dict(externalApplyUrl="https://a.local/"),
                       dict(externalApplyUrl="https://user:pw@example.org/")]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                editorial.parse_snapshot(snapshot(self.now, [{**row(self.now), **change}]), self.now)

    def test_unique_id_latest_revision_and_expiry(self):
        raw = row(self.now)
        jobs = editorial.parse_snapshot(snapshot(self.now, [raw, {**raw, "revision": 3, "title": "Updated Surveyor"}, raw]), self.now)
        self.assertEqual(1, len(jobs)); self.assertEqual(3, jobs[0]["revision"])
        self.assertEqual([], editorial.parse_snapshot(snapshot(self.now, [{**raw, "expiresAt": iso(self.now)}]), self.now))
        self.assertEqual([], editorial.parse_snapshot(snapshot(self.now, [raw, {**raw, "revision": 3, "expiresAt": iso(self.now)}]), self.now))

    def test_withdrawal_and_outage_replace_not_union_cached_editorial(self):
        ordinary = {"id": "scraped", "origin": "SCRAPED"}
        previous = [ordinary, row(self.now), {"id": "editorial_" + "b" * 32}]
        self.assertEqual([ordinary], editorial.replace_editorial(previous, []))
        updated = {**row(self.now), "revision": 3}
        self.assertEqual([ordinary, updated], editorial.replace_editorial(previous, [updated]))

    def test_loader_disabled_does_not_fetch_and_enabled_is_bounded_and_closed(self):
        with patch.dict(os.environ, {"SURVEYONE_EDITORIAL_JOBS_FEED_URL": ""}):
            jobs, health = editorial.load_editorial({}, self.now, lambda *a: self.fail("Unexpected network"))
            self.assertEqual([], jobs); self.assertEqual("disabled", health["status"])
            requested = []
            now = self.now
            class Fetcher:
                def __init__(self, source, budget, max_bytes):
                    requested.append((source, budget, max_bytes))
                def request(self, url): return 200, json.dumps(snapshot(now))
            config = {"editorialFeed": {"enabled": True, "url": "https://feed.example.org/editorialJobsFeed"}}
            jobs, health = editorial.load_editorial(config, self.now, Fetcher)
            self.assertEqual(1, len(jobs)); self.assertEqual("healthy", health["status"])
            self.assertEqual((4, editorial.MAX_BYTES), requested[0][1:])
            class Broken(Fetcher):
                def request(self, url): raise TimeoutError("Private data")
            jobs, health = editorial.load_editorial(config, self.now, Broken)
            self.assertEqual([], jobs); self.assertEqual({"status": "unavailable", "activeJobs": 0, "errorType": "TimeoutError"}, health)

    def test_environment_setting_can_enable_deployed_endpoint_without_code_change(self):
        now = self.now
        class Fetcher:
            def __init__(self, source, *args): self.source = source
            def request(self, url):
                self.assertion = url == "https://feed.example.org/editorialJobsFeed"
                if not self.assertion: raise ValueError("Wrong endpoint")
                return 200, json.dumps(snapshot(now))
        with patch.dict(os.environ, {"SURVEYONE_EDITORIAL_JOBS_FEED_URL": "https://feed.example.org/editorialJobsFeed"}):
            self.assertEqual("healthy", editorial.load_editorial({}, self.now, Fetcher)[1]["status"])


class EditorialPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.now = datetime.now(timezone.utc)
        main.save(self.root / "jobs/config/sources.json", {"sources": [], "checkLinksPerRun": 0})
        main.save(self.root / "jobs/config/keywords.json", {"include": [], "exclude": []})
        self.root_patch = patch.object(main, "ROOT", self.root); self.root_patch.start()
        self.ordinary = {"id": "scraped", "title": "Surveyor", "company": "Other", "applyUrl": "https://careers.example.org/role",
                         "country": "Egypt", "discoveredAt": iso(self.now), "sourceUrl": "https://careers.example.org/"}
        main.save(self.root / "public/jobs/jobs.json", dict(version=1, jobs=[self.ordinary]))

    def tearDown(self):
        self.root_patch.stop(); self.temp.cleanup()

    def collect(self, jobs, status="healthy"):
        with patch.object(main, "load_editorial", return_value=(jobs, {"status": status, "activeJobs": len(jobs)})):
            main.collect()
        return main.load(self.root / "public/jobs/jobs.json", {})["jobs"]

    def test_publish_edit_pause_republish_archive_do_not_restore_stale_entries(self):
        job = editorial.parse_snapshot(snapshot(self.now), self.now)[0]
        self.assertEqual(2, len(self.collect([job])))
        edited = {**job, "revision": 4, "title": "New title"}
        self.assertEqual(edited, next(j for j in self.collect([edited]) if editorial.is_editorial(j)))
        self.assertEqual([self.ordinary], self.collect([]))
        self.assertEqual([self.ordinary], self.collect([]))
        self.assertEqual(2, len(self.collect([{**edited, "revision": 6}])))
        self.assertEqual([self.ordinary], self.collect([]))
        self.assertEqual([self.ordinary], self.collect([]))

    def test_outage_or_disabled_feed_withdraws_editorial_only(self):
        job = editorial.parse_snapshot(snapshot(self.now), self.now)[0]
        self.collect([job]); self.assertEqual([self.ordinary], self.collect([], "unavailable"))
        self.collect([job]); self.assertEqual([self.ordinary], self.collect([], "disabled"))

    def test_repeat_snapshot_does_not_rewrite_feed_and_never_enqueues_automatic_notifications(self):
        job = editorial.parse_snapshot(snapshot(self.now), self.now)[0]
        self.collect([job]); feed = (self.root / "public/jobs/jobs.json").read_bytes()
        self.collect([job]); self.assertEqual(feed, (self.root / "public/jobs/jobs.json").read_bytes())
        state = main.load(self.root / "jobs/state.json", {})
        self.assertNotIn(job["id"], state["pending"])
        # Even a stale or manually edited pending list cannot make scraper FCM send an editorial job.
        state["pending"] = [job["id"]]; main.save(self.root / "jobs/state.json", state)
        with patch.object(notify, "ROOT", self.root), patch.object(notify, "BATCH", self.root / "jobs/notification.json"):
            notify.reserve()
            self.assertEqual([], main.load(notify.BATCH, {})["ids"])

    def test_long_collection_validates_snapshot_against_fresh_end_of_run_time(self):
        finished = self.now + timedelta(minutes=15)
        def live_feed(config, checked_at):
            jobs = editorial.parse_snapshot(snapshot(finished), checked_at)
            return jobs, {"status": "healthy", "activeJobs": len(jobs)}
        with patch.object(main, "datetime") as clock, patch.object(main, "load_editorial", side_effect=live_feed):
            clock.now.side_effect = [self.now, finished]
            main.collect()
        state = main.load(self.root / "jobs/state.json", {})
        self.assertEqual("healthy", state["editorialFeed"]["status"])
        self.assertEqual(iso(finished), state["editorialFeed"]["checkedAt"])
        self.assertEqual(2, len(main.load(self.root / "public/jobs/jobs.json", {})["jobs"]))


if __name__ == "__main__":
    unittest.main()
