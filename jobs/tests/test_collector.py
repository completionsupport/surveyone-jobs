import json
import unittest
from datetime import datetime, timezone, timedelta
from jobs.collector.parsers import greenhouse, html, icims, jsonld, kwsc, lever, nextjs_jobs, njp, oracle, orbital_careers, plra, rss, sitemap, smartrecruiters_html, stantec_sitemap, workday, xml_root
from jobs.collector.model import normalize_url, relevant, make_job, expired, deduplicate
from jobs.collector.main import load, ROOT

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
SOURCE = {
    "name": "Test careers",
    "url": "https://careers.example.org",
    "country": "UAE",
}


class CollectorTests(unittest.TestCase):
    def test_pakistan_national_job_portal_searches_are_bounded(self):
        source = dict(
            url="https://njp.gov.pk/jobs/search?q=surveyor",
            searchTerms=["surveyor", "GIS"],
        )
        body = '''<html><body><div class="job-card">
          <h2><a href="https://njp.gov.pk/jobs/99">GIS Surveyor</a></h2>
          <p>by Survey of Pakistan</p>
          <p class="text-gray-400">Field mapping and control survey.</p>
        </div></body></html>'''
        jobs, links = njp(body, source["url"], source)
        self.assertEqual("GIS Surveyor", jobs[0]["title"])
        self.assertEqual("Survey of Pakistan", jobs[0]["company"])
        self.assertEqual("Pakistan", jobs[0]["country"])
        self.assertEqual(["https://njp.gov.pk/jobs/search?q=GIS"], links)

    def test_kwsc_public_careers_api(self):
        body = json.dumps({"data": {"openings": [{
            "status": "PUBLISHED", "title": "GIS Analyst",
            "location": "Karachi, Sindh, Pakistan", "department": "KWSSIP",
            "publishAt": "2026-10-01T12:00:00Z",
            "expireAt": "2026-10-16T17:00:00Z",
        }, {"status": "DRAFT", "title": "Hidden Surveyor"}]}})
        jobs = kwsc(body, "https://www.kwsc.gos.pk/api/careers?lang=en")
        self.assertEqual(1, len(jobs))
        self.assertEqual("GIS Analyst", jobs[0]["title"])
        self.assertEqual("Pakistan", jobs[0]["country"])
        self.assertEqual("https://www.kwsc.gos.pk/careers#career-openings",
                         jobs[0]["applyUrl"])

    def test_static_career_page_can_use_its_https_page_as_apply_url(self):
        jobs = html('<details><h3>Senior GIS Engineer</h3></details>',
                    'https://example.org/careers',
                    {'job': 'details', 'title': 'h3'},
                    'https://example.org/careers')
        self.assertEqual('https://example.org/careers', jobs[0]['applyUrl'])

    def test_workday_search_is_bounded_and_preserves_public_location(self):
        source = dict(
            type="workday", company="Example Engineering",
            url="https://example.wd1.myworkdayjobs.com/wday/cxs/example/Careers/jobs?search=land+surveyor&offset=0",
            publicBaseUrl="https://example.wd1.myworkdayjobs.com/en-US/Careers",
            searchTerms=["land surveyor", "GIS"], maxPagesPerTerm=2,
        )
        body = json.dumps(dict(total=25, jobPostings=[dict(
            title="Land Surveyor", externalPath="/job/AE---Dubai/Land-Surveyor_R1",
            locationsText="AE - Dubai", bulletFields=["R1"],
        )]))
        jobs, links = workday(body, source["url"], source)
        self.assertEqual("AE - Dubai", jobs[0]["location"])
        self.assertTrue(jobs[0]["applyUrl"].endswith("/job/AE---Dubai/Land-Surveyor_R1"))
        self.assertEqual(2, len(links))
        self.assertIn("offset=20", links[0])
        self.assertIn("search=GIS", links[1])
        with self.assertRaises(ValueError):
            workday(body, source["url"], dict(source, publicBaseUrl="https://evil.example/job"))

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

    def test_rss_extracts_country_from_stantec_metadata(self):
        records = rss(
            "<rss><channel><item><title>Quantity Surveyor</title>"
            "<link>https://stantec.jobs/dubai-ae/job/1</link>"
            "<description>**City:** Dubai\n**Country:** United Arab Emirates\n"
            "**Job Category:** Civil Engineering</description></item></channel></rss>",
            SOURCE["url"],
        )
        self.assertEqual("Dubai, United Arab Emirates", records[0]["location"])
        self.assertEqual("United Arab Emirates", records[0]["country"])

    def test_oracle_public_feed_is_bounded(self):
        source = dict(
            type="oracle", company="GHD",
            url=("https://example.oraclecloud.com/hcmRestApi/resources/latest/"
                 "recruitingCEJobRequisitions?onlyData=true&finder="
                 "findReqs%3BsiteNumber%3DCX%2Climit%3D25%2Coffset%3D0%2Ckeyword%3Dsurveyor"),
            publicBaseUrl=("https://example.oraclecloud.com/hcmUI/"
                           "CandidateExperience/en/sites/CX"),
            searchTerms=["surveyor", "GIS"], maxPagesPerTerm=2, siteNumber="CX",
        )
        body = json.dumps({"items": [{"TotalJobsCount": 26, "requisitionList": [{
            "Id": "42", "Title": "Geodetic Surveyor",
            "PrimaryLocation": "Manila, Philippines",
            "PrimaryLocationCountry": "PH", "PostedDate": "2026-10-01",
        }]}]})
        jobs, links = oracle(body, source["url"], source)
        self.assertEqual("PH", jobs[0]["country"])
        self.assertTrue(jobs[0]["applyUrl"].endswith("/job/42"))
        self.assertEqual(2, len(links))
        self.assertIn("offset%3D25", links[0])

    def test_plra_spa_discovers_and_parses_current_jobs(self):
        records, links = plra(
            '<script src="/static/js/main.123abc.js"></script>',
            "https://www.punjab-zameen.gov.pk/Careers",
        )
        self.assertFalse(records)
        self.assertEqual("https://www.punjab-zameen.gov.pk/static/js/main.123abc.js", links[0])
        bundle = ('Xa=[{id:1,title:{en:"Surveyor",ur:"x"},'
                  'link:"https://jobs.punjab.gov.pk/job/1",'
                  'department:{en:"Survey & Geospatial",ur:"x"}}]')
        records, links = plra(bundle, links[0])
        self.assertEqual("Surveyor", records[0]["title"])
        self.assertEqual("Pakistan", records[0]["country"])
        self.assertFalse(links)

    def test_nextjs_jobs_list(self):
        payload = {"props": {"pageProps": {"jobsList": [{
            "date": "2026-10-01T00:00:00", "slug": "land-surveyor",
            "acf": {"job": {"title": "Land Surveyor", "code": "Cairo, Egypt",
                              "description": "Field survey"}},
        }]}}}
        page = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + '</script>'
        jobs = nextjs_jobs(page, "https://www.example.org/careers", {"company": "Example"})
        self.assertEqual("Cairo, Egypt", jobs[0]["location"])
        self.assertEqual("https://www.example.org/jobs-items/land-surveyor/", jobs[0]["applyUrl"])

    def test_orbital_africa_shared_hr_portal_keeps_distinct_titles(self):
        page = '''<div class="vc_toggle_content">
        <p>1. Full Stack GIS Software Engineer <a href="https://hr.example.org/jobs">Please click here for more details ++</a></p>
        <p>4. We’re looking for An Assistant Land Surveyor. <a href="https://hr.example.org/jobs">For more details, please click here ++</a></p>
        </div>'''
        jobs = orbital_careers(page, "https://orbital.example/careers")
        self.assertEqual(["Full Stack GIS Software Engineer", "Assistant Land Surveyor"],
                         [job["title"] for job in jobs])
        self.assertTrue(all(job["country"] == "Kenya" for job in jobs))

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

    def test_stantec_sitemap_filters_and_preserves_country_code(self):
        source = {"company": "Stantec", "slugKeywords": ["surveyor", "geospatial"]}
        page = """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
        <url><loc>https://stantec.jobs/abu-dhabi-are/senior-quantity-surveyor/ABC/job/</loc><lastmod>2026-10-01</lastmod></url>
        <url><loc>https://stantec.jobs/dubai-are/accountant/DEF/job/</loc></url>
        </urlset>"""
        jobs, links = stantec_sitemap(page, "https://stantec.jobs/sitemaps/jobs_1.xml", source)
        self.assertEqual(1, len(jobs))
        self.assertEqual("Abu Dhabi, ARE", jobs[0]["location"])
        self.assertEqual("Senior Quantity Surveyor", jobs[0]["title"])
        self.assertFalse(links)

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
