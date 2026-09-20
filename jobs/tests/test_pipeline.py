"""Offline integration coverage: collection, persistence and notification reservation."""

import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from jobs.collector import main, notify
from jobs.collector.model import make_job, iso, infer_country, category
from jobs.collector.parsers import jobicy, remotive


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
            self.assertEqual("ae", main.load(notify.BATCH, {})["batches"][0]["countryCode"])
            notify.reserve()
            self.assertEqual([], main.load(notify.BATCH, {})["ids"])

    def test_country_topic_mapping_never_broadcasts_known_country_globally(self):
        self.assertEqual("ae", notify.country_code("United Arab Emirates"))
        self.assertEqual("sa", notify.country_code("SA"))
        self.assertIsNone(notify.country_code(""))

    def test_country_notification_has_report_label_and_no_global_topic(self):
        payload = notify.fcm_payload({
            "countryCode": "ae", "country": "United Arab Emirates",
            "id": "batch-1", "ids": ["job-1"],
        })["message"]
        self.assertEqual("survey_jobs_ae", payload["topic"])
        self.assertEqual("survey_jobs_country", payload["fcm_options"]["analytics_label"])
        self.assertNotEqual("survey_jobs_all", payload["topic"])

    def test_country_is_inferred_only_from_strong_location_evidence(self):
        self.assertEqual("United Arab Emirates", infer_country("Dubai, UAE"))
        self.assertEqual("United States", infer_country("Raleigh, NC"))
        self.assertEqual("Canada", infer_country("Vancouver, BC"))
        self.assertEqual("Australia", infer_country("Brisbane, Australia"))
        self.assertEqual("", infer_country("Worldwide / APAC"))

    def test_quantity_surveyor_has_its_own_category(self):
        self.assertEqual("Quantity Surveying", category("Senior Quantity Surveyor"))

    def test_public_aggregator_parsers_keep_canonical_urls(self):
        jobicy_jobs = jobicy('{"jobs":[{"jobTitle":"GIS Surveyor","companyName":"Geo Co",'
            '"jobGeo":"Canada","jobIndustry":"Engineering","jobType":"full-time",'
            '"pubDate":"2026-09-20T00:00:00Z","url":"https://jobicy.com/jobs/1"}]}')
        remotive_jobs = remotive('{"jobs":[{"title":"Geospatial Engineer","company_name":"Map Co",'
            '"candidate_required_location":"United Kingdom","category":"All others",'
            '"job_type":"full_time","publication_date":"2026-09-20T00:00:00",'
            '"url":"https://remotive.com/remote-jobs/1"}]}')
        self.assertEqual("https://jobicy.com/jobs/1", jobicy_jobs[0]["applyUrl"])
        self.assertEqual("https://remotive.com/remote-jobs/1", remotive_jobs[0]["applyUrl"])

    def test_source_poll_interval_skips_recent_success(self):
        main.save(self.root / "jobs/config/sources.json", {
            "sources": [dict(self.source, pollIntervalHours=6)], "checkLinksPerRun": 0,
        })
        main.save(self.root / "jobs/state.json", {"sourceHealth": {
            "Careers": {"lastSuccess": iso(datetime.now(timezone.utc)), "status": "healthy"}
        }})
        main.collect()
        self.assertEqual(0, main.load(self.root / "public/jobs/jobs.json", {})["totalJobs"])
        health = main.load(self.root / "jobs/state.json", {})["sourceHealth"]
        self.assertEqual("healthy", health["Careers"]["status"])

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
        health = main.load(self.root / "jobs/state.json", {})["sourceHealth"]
        self.assertEqual("failed", health["Broken"]["status"])
        self.assertEqual("healthy", health["Careers"]["status"])
