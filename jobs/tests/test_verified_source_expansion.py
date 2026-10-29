"""Offline contracts for the regional employer cards verified on 29 October 2026."""

import unittest
from datetime import datetime, timezone

from jobs.collector.main import ROOT, load
from jobs.collector.model import make_job, relevant
from jobs.collector.parsers import parse
from jobs.collector.registry import enabled_sources, source_key


class VerifiedSourceExpansionTests(unittest.TestCase):
    def setUp(self):
        self.config = load(ROOT / "jobs/config/sources.json", {})
        self.sources = {source["name"]: source for source in self.config["sources"]}
        self.keywords = load(ROOT / "jobs/config/keywords.json", {})
        self.now = datetime(2026, 10, 29, tzinfo=timezone.utc)

    def test_verified_employers_are_enabled_distinct_boards(self):
        names = (
            "HanmiGlobal Saudi Careers", "Advanced Roads and Development Saudi Careers",
            "QSIT Egypt GIS Careers", "Oceangate Egypt Survey Careers",
            "BKF Engineers Survey Careers",
        )
        enabled = enabled_sources(self.config)
        keys = [source_key(source) for source in enabled]
        self.assertEqual(len(keys), len(set(keys)))
        for name in names:
            with self.subTest(name=name):
                self.assertTrue(self.sources[name]["enabled"])
                self.assertIn(source_key(self.sources[name]), keys)

    def test_saudi_card_uses_job_heading_without_generic_remote_location(self):
        source = self.sources["Advanced Roads and Development Saudi Careers"]
        body = '<div class="card"><a href="/jobs/surveyor-27"><div><h3>Surveyor | مسّاح</h3></div>' \
               '<span>1 vacancy</span><span>Remote</span></a></div>' \
               '<div class="card"><a href="/jobs/planning-23"><h3>Planning Engineer</h3></a></div>'
        rows, _ = parse(body, source["url"], source)
        eligible = [row for row in rows if relevant(row["title"], self.keywords)]
        self.assertEqual(1, len(eligible))
        job = make_job(eligible[0], source, self.now)
        self.assertEqual("Surveyor | مسّاح", job["title"])
        self.assertEqual("Saudi Arabia", job["country"])
        self.assertEqual("", job["location"])
        self.assertFalse(job["remote"])
        self.assertEqual("https://www.ardco.sa/jobs/surveyor-27", job["applyUrl"])

    def test_qsit_preserves_profession_country_and_employment_fields(self):
        source = self.sources["QSIT Egypt GIS Careers"]
        body = '<div class="awsm-job-item"><div class="awsm-list-left-col">' \
               '<h2 class="awsm-job-post-title"><a href="/jobs/gis-engineer/">GIS Solution Engineer</a></h2></div>' \
               '<div class="awsm-job-specification-job-category">GIS Solution Engineer</div>' \
               '<div class="awsm-job-specification-job-location">Egypt</div>' \
               '<div class="awsm-job-specification-job-type">Full Time</div></div>' \
               '<div class="awsm-job-item"><h2 class="awsm-job-post-title">' \
               '<a href="/jobs/consultation/">Head of Consultation Services</a></h2>' \
               '<div class="awsm-job-specification-job-category">GIS Consultancy</div></div>'
        rows, _ = parse(body, source["url"], source)
        self.assertEqual(1, len(rows))
        self.assertTrue(relevant(rows[0]["title"] + " " + rows[0]["category"], self.keywords))
        job = make_job(rows[0], source, self.now)
        self.assertEqual("QSIT", job["company"])
        self.assertEqual("Egypt", job["country"])
        self.assertEqual("Full Time", job["employmentType"])
        self.assertEqual("https://qsitint.com/jobs/gis-engineer/", job["applyUrl"])

    def test_oceangate_card_keeps_location_description_and_shared_application(self):
        source = self.sources["Oceangate Egypt Survey Careers"]
        body = '<div class="e-grid"><div class="e-con"><div><h5>GIS Specialist</h5></div>' \
               '<div class="elementor-widget-heading"><div class="elementor-heading-title">Spatial mapping and database work.</div></div>' \
               '<span class="elementor-icon-list-text">Alexandria, Egypt</span>' \
               '<a href="https://oceangatefz.com/apply">Apply Now</a></div></div>'
        rows, _ = parse(body, source["url"], source)
        self.assertEqual(1, len(rows))
        job = make_job(rows[0], source, self.now)
        self.assertEqual("GIS Specialist", job["title"])
        self.assertEqual("Alexandria, Egypt", job["location"])
        self.assertEqual("Egypt", job["country"])
        self.assertEqual("Spatial mapping and database work.", job["description"])
        self.assertEqual("https://oceangatefz.com/apply", job["applyUrl"])


if __name__ == "__main__":
    unittest.main()
