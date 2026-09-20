"""Offline integration coverage: collection, persistence and notification reservation."""

import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from jobs.collector import main, notify
from jobs.collector.model import make_job, iso


class FakeFetcher:
    def __init__(self, source, *args):
        self.remaining = 12
        self.source = source

    def request(self, url):
        if self.source["name"] == "Broken":
            raise TimeoutError()
        self.remaining -= 1
        return (
            200,
            '<script type="application/ld+json">{"@type":"JobPosting","title":"Land Surveyor","url":"https://example.org/job/1"}</script>',
        )


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = {
            "enabled": True,
            "name": "Careers",
            "url": "https://example.org",
            "type": "auto",
            "country": "United Arab Emirates",
        }
        main.save(
            self.root / "jobs/config/sources.json",
            {"sources": [self.source], "checkLinksPerRun": 0},
        )
        main.save(
            self.root / "jobs/config/keywords.json",
            {"include": ["Land Surveyor"], "exclude": ["Quantity Surveyor"]},
        )
        self.root_patch = patch.object(main, "ROOT", self.root)
        self.root_patch.start()
        self.fetch_patch = patch.object(main, "Fetcher", FakeFetcher)
        self.fetch_patch.start()

    def tearDown(self):
        self.fetch_patch.stop()
        self.root_patch.stop()
        self.temp.cleanup()

    def test_second_run_does_not_change_feed_or_repeat_reservation(self):
        main.collect()
        feed_path = self.root / "public/jobs/jobs.json"
        first = feed_path.read_bytes()
        main.collect()
        self.assertEqual(first, feed_path.read_bytes())
        with patch.object(notify, "ROOT", self.root), patch.object(
            notify, "BATCH", self.root / "jobs/notification.json"
        ):
            notify.reserve()
            self.assertEqual(1, len(main.load(notify.BATCH, {})["ids"]))
            self.assertEqual(
                "ae", main.load(notify.BATCH, {})["batches"][0]["countryCode"]
            )
            notify.reserve()
            self.assertEqual([], main.load(notify.BATCH, {})["ids"])

    def test_country_topic_mapping_never_broadcasts_known_country_globally(self):
        self.assertEqual("ae", notify.country_code("United Arab Emirates"))
        self.assertEqual("sa", notify.country_code("SA"))
        self.assertIsNone(notify.country_code(""))

    def test_old_undated_job_does_not_reappear_after_expiry(self):
        now = datetime.now(timezone.utc)
        job = make_job(
            {"title": "Land Surveyor", "applyUrl": "https://example.org/job/1"},
            self.source,
            now,
        )
        main.save(
            self.root / "jobs/state.json",
            {"firstDiscovered": {job["id"]: iso(now - timedelta(days=60))}},
        )
        main.collect()
        self.assertEqual(
            [], main.load(self.root / "public/jobs/jobs.json", {"jobs": []})["jobs"]
        )

    def test_one_broken_source_does_not_block_other_sources(self):
        main.save(
            self.root / "jobs/config/sources.json",
            {
                "sources": [dict(self.source, name="Broken"), self.source],
                "checkLinksPerRun": 0,
            },
        )
        main.collect()
        self.assertEqual(
            1, len(main.load(self.root / "public/jobs/jobs.json", {})["jobs"])
        )
