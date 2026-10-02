import json
import unittest
from datetime import datetime, timezone, timedelta
from jobs.collector.parsers import greenhouse, icims, jsonld, lever, rss, sitemap, smartrecruiters_html, xml_root
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

    def test_lever_public_postings_response(self):
        payload = '[{"text":"Survey Engineer","hostedUrl":"https://jobs.lever.co/acme/42","createdAt":1789459200000,"categories":{"location":"Dubai","team":"Survey","commitment":"Full-time"},"descriptionPlain":"Set out works"}]'
        jobs = lever(payload)
        self.assertEqual("Survey Engineer", jobs[0]["title"])
        self.assertEqual("Full-time", jobs[0]["employmentType"])
        self.assertEqual("https://jobs.lever.co/acme/42", jobs[0]["applyUrl"])

    def test_smartrecruiters_public_career_page(self):
        page = '''<h1>ABEC</h1><div class="js-openings"><section class="js-group">
        <h3>Cairo, Egypt</h3><li class="opening-job"><a href="https://jobs.smartrecruiters.com/ABEC1/42">
        <h4 class="job-title">Senior Land Surveyor</h4><p class="job-desc">Full-time</p>
        </a></li></section></div>'''
        jobs = smartrecruiters_html(page)
        self.assertEqual("Senior Land Surveyor", jobs[0]["title"])
        self.assertEqual("Cairo, Egypt", jobs[0]["location"])
        self.assertEqual("https://jobs.smartrecruiters.com/ABEC1/42", jobs[0]["applyUrl"])

    def test_icims_sitemap_is_filtered_before_fetching_job_pages(self):
        source = {"linkKeywords": ["surveyor", "gis"]}
        sitemap_page = '''<urlset><url><loc>https://careers.example/jobs/1/accountant/job</loc></url>
        <url><loc>https://careers.example/jobs/2/senior-surveyor/job</loc></url></urlset>'''
        records, links = icims(sitemap_page, source)
        self.assertFalse(records)
        self.assertEqual(["https://careers.example/jobs/2/senior-surveyor/job"], links)

    def test_icims_public_job_metadata(self):
        page = '''<script>var icimsSD = {"companyName":"SYSTRA","job":{"title":"Surveyor",
        "location":"Cairo, Egypt","jobUrls":[{"url":"https://careers.example/jobs/2/job"}]}};</script>'''
        records, links = icims(page, {})
        self.assertEqual("Surveyor", records[0]["title"])
        self.assertEqual("Cairo, Egypt", records[0]["location"])
        self.assertFalse(links)

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
            "Quantity Surveyor",
            "Senior Quantity Surveyor",
            "MEP Quantity Surveyor",
            "Cost Surveyor",
            "Senior GIS Specialist",
        ):
            self.assertTrue(relevant(title, words))
        self.assertFalse(relevant("Customer Support Specialist", words))
        self.assertFalse(relevant("Logistics Operations Supervisor", words))

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

    def test_cross_source_duplicate_requires_strong_description_match(self):
        first = make_job(
            {"title": "Land Surveyor", "city": "Dubai", "country": "UAE",
             "description": "Set out roads and verify control points with GNSS and total station.",
             "applyUrl": "https://careers.example.org/job/77"}, SOURCE, NOW,
        )
        second = make_job(
            {"title": "Land Surveyor", "city": "Dubai", "country": "UAE",
             "description": "Set out roads and verify control points with GNSS and total station.",
             "applyUrl": "https://board.example.org/openings/77"}, SOURCE, NOW,
        )
        self.assertEqual(1, len(deduplicate([first, second])))

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
