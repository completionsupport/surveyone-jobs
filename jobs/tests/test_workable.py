import json
import unittest
from datetime import datetime, timezone
from jobs.collector.parsers import parse
from jobs.collector.model import make_job, deduplicate
from jobs.collector.model import relevant
from pathlib import Path


class WorkableTests(unittest.TestCase):
    def test_arabic_titles_and_explicit_country_codes(self):
        keywords = json.loads((Path(__file__).parents[1] / "config/keywords.json").read_text("utf-8"))
        self.assertTrue(relevant("مطلوب مهندس مساحة في القاهرة", keywords))
        self.assertTrue(relevant("مساح طرق بالرياض", keywords))
        self.assertFalse(relevant("مساحة تخزين سحابية", keywords))
        source = dict(name="Employer", url="https://www.workable.com/api/accounts/test")
        for raw_country, expected in [("EG", "Egypt"), ("SA", "Saudi Arabia"), ("AE", "United Arab Emirates")]:
            job = make_job(dict(title="مساح", country=raw_country, applyUrl="https://apply.workable.com/j/1"), source, datetime.now(timezone.utc))
            self.assertEqual(expected, job["country"])
    def test_locations_are_separate_countries_and_hidden_locations_excluded(self):
        source = dict(type="workable", name="Employer", url="https://www.workable.com/api/accounts/test")
        payload = dict(name="Employer", jobs=[dict(title="Land Surveyor", url="https://apply.workable.com/j/123",
            published_on="2026-09-23", locations=[dict(country="Egypt", city="Cairo"),
            dict(country="Saudi Arabia", city="Riyadh"), dict(country="Qatar", hidden=True)])])
        records, links = parse(json.dumps(payload), source["url"], source)
        self.assertEqual([r["country"] for r in records], ["Egypt", "Saudi Arabia"])
        self.assertFalse(links)
        jobs = [make_job(r, source, datetime.now(timezone.utc)) for r in records]
        self.assertEqual(2, len(deduplicate(jobs + jobs)))

    def test_malformed_feed_is_not_a_healthy_empty_response(self):
        with self.assertRaises(ValueError):
            parse('{"error":"unavailable"}', "https://www.workable.com", {"type":"workable"})

    def test_flat_location_keeps_unknown_country_unknown(self):
        records, _ = parse(json.dumps(dict(jobs=[dict(title="GIS Analyst", url="https://apply.workable.com/j/1") ])),
            "https://www.workable.com", {"type":"workable"})
        self.assertEqual("", records[0]["country"])
