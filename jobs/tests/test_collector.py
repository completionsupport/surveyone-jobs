import unittest
from datetime import datetime, timezone, timedelta
from jobs.collector.parsers import greenhouse, jsonld, rss, sitemap, xml_root
from jobs.collector.model import normalize_url, relevant, make_job, expired, deduplicate
from jobs.collector.main import load, ROOT

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
SOURCE = {
    "name": "Test careers",
    "url": "https://careers.example.org",
    "country": "UAE",
}


class CollectorTests(unittest.TestCase):
    def test_greenhouse_public_board_response(self):
        payload = (
            '{"jobs":[{"title":"Land Surveyor",'
            '"absolute_url":"https://job-boards.greenhouse.io/acme/jobs/42",'
            '"location":{"name":"Dubai, UAE"},'
            '"updated_at":"2026-09-15T08:00:00Z"}]}'
        )
        jobs = greenhouse(payload)
        self.assertEqual("Land Surveyor", jobs[0]["title"])
        self.assertEqual("Dubai, UAE", jobs[0]["location"])
        self.assertEqual(
            "https://job-boards.greenhouse.io/acme/jobs/42",
            jobs[0]["applyUrl"],
        )

    def test_jsonld_graph(self):
        html = '<script type="application/ld+json">{"@graph":[{"@type":"JobPosting","title":"Land Surveyor","hiringOrganization":{"name":"Survey Ltd"},"jobLocation":{"address":{"addressLocality":"Dubai","addressCountry":"AE"}},"url":"/jobs/1"}]}</script>'
        job = jsonld(html, SOURCE["url"])[0]
        self.assertEqual(job["company"], "Survey Ltd")
        self.assertEqual(job["applyUrl"], "https://careers.example.org/jobs/1")
        self.assertEqual(job["city"], "Dubai")

    def test_rss(self):
        records = rss(
            "<rss><channel><item><title>Survey Engineer</title><link>https://careers.example.org/jobs/2</link><pubDate>Mon, 14 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>",
            SOURCE["url"],
        )
        self.assertEqual(records[0]["title"], "Survey Engineer")

    def test_atom(self):
        records = rss(
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Geomatics</title><link href="/job/3"/><published>2026-09-14</published></entry></feed>',
            SOURCE["url"],
        )
        self.assertEqual(records[0]["applyUrl"], "https://careers.example.org/job/3")

    def test_keywords(self):
        words = load(ROOT / "jobs/config/keywords.json", {})
        for title in (
            "Senior Land Surveyor",
            "GIS / Geomatics Survey Engineer",
            "Underground Utility Surveyor",
        ):
            self.assertTrue(relevant(title, words))
        for title in (
            "Quantity Surveyor",
            "Senior Quantity Surveyor",
            "MEP Quantity Surveyor",
            "Cost Surveyor",
        ):
            self.assertFalse(relevant(title, words))

    def test_normalize_urls_and_dedupe(self):
        a = make_job(
            {
                "title": "Land Surveyor",
                "applyUrl": "https://careers.example.org/job/1?utm_source=a&ref=2",
            },
            SOURCE,
            NOW,
        )
        b = make_job(
            {
                "title": "land   surveyor",
                "applyUrl": "https://careers.example.org/job/1?ref=2&utm_medium=b",
            },
            SOURCE,
            NOW,
        )
        self.assertEqual(a["id"], b["id"])
        self.assertEqual(len(deduplicate([a, b])), 1)

    def test_different_requisitions_remain(self):
        a = make_job(
            {
                "title": "Land Surveyor",
                "applyUrl": "https://careers.example.org/job?id=1",
            },
            SOURCE,
            NOW,
        )
        b = make_job(
            {
                "title": "Land Surveyor",
                "applyUrl": "https://careers.example.org/job?id=2",
            },
            SOURCE,
            NOW,
        )
        self.assertEqual(len(deduplicate([a, b])), 2)

    def test_expiry(self):
        job = {"discoveredAt": (NOW - timedelta(days=46)).isoformat()}
        self.assertTrue(expired(job, NOW))
        self.assertFalse(expired(job, NOW, 60))
        job["expiresAt"] = (NOW + timedelta(days=1)).isoformat()
        self.assertFalse(expired(job, NOW))
        job["expiresAt"] = (NOW - timedelta(seconds=1)).isoformat()
        self.assertTrue(expired(job, NOW))

    def test_sitemap(self):
        self.assertEqual(
            sitemap(
                "<urlset><url><loc>https://careers.example.org/1</loc></url></urlset>"
            ),
            ["https://careers.example.org/1"],
        )

    def test_unsafe_inputs(self):
        with self.assertRaises(ValueError):
            xml_root("<!DOCTYPE x><x/>")
        for value in (
            "file:///a",
            "http://example.org",
            "https://user:pass@example.org",
        ):
            with self.assertRaises(ValueError):
                normalize_url(value)


if __name__ == "__main__":
    unittest.main()
