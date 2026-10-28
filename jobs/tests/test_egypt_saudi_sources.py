"""Offline regressions for regional public boards and field-survey filtering."""

import json
import unittest
from datetime import datetime, timezone

from jobs.collector.main import ROOT, load
from jobs.collector.model import date, deduplicate, make_job, normalize_url, relevant
from jobs.collector.parsers import dar_al_riyadh, gis_career_hub, html, jibe, parse


class EgyptSaudiSourcesTests(unittest.TestCase):
    def setUp(self):
        self.keywords = load(ROOT / "jobs/config/keywords.json", {})
        self.now = datetime(2026, 10, 28, tzinfo=timezone.utc)

    def test_quantity_roles_never_match_field_survey_keywords(self):
        for title in (
            "Senior Quantity Surveyor", "Quantity Surveying Engineer",
            "Quantity-Surveyors", "quntity surveyor", "Qty Surveyor",
            "Cost Surveyor", "Land Surveyor / QS", "Quantity Surveying",
            "مساح كميات", "مسّاح الكميات", "مساح الكمية", "مهندس حصر كميات",
        ):
            with self.subTest(title=title):
                self.assertFalse(relevant(title, self.keywords))

    def test_land_survey_gis_and_mining_roles_remain_eligible(self):
        for title in (
            "Land Surveyor", "Site Surveyor", "Senior Surveying Engineer",
            "Mine Surveyor", "GIS Specialist", "Head of Survey & Planning Department",
            "Senior Photogrammetry Specialist", "Senior Digital Cartography Specialist",
            "GIS Developer - QSIT", "مساح إنشائي",
        ):
            with self.subTest(title=title):
                self.assertTrue(relevant(title, self.keywords))

    def test_public_card_keeps_unambiguous_written_date(self):
        rows = html('<article><h2>Mine Surveyor</h2><a href="/job/42">Apply</a>'
                    '<time>Posted - 27 October 2026</time><p>Control surveys</p></article>',
                    "https://example.org/jobs/", dict(job="article", title="h2", link="a",
                                                     postedAt="time", description="p"))
        job = make_job(rows[0], dict(name="Mine", url="https://example.org/jobs/"), self.now)
        self.assertEqual("2026-10-27T00:00:00Z", job["postedAt"])
        self.assertEqual("Control surveys", job["description"])
        self.assertIsNone(date("10/11/2026"))

    def test_ecg_city_mapping_is_source_scoped_and_never_overrides_country(self):
        source = dict(name="ECG", url="https://example.org", locationCountryMap={
            "alexandria": "Egypt", "nasr city": "Egypt"})
        raw = dict(title="Site Surveyor", location="Alexandria", applyUrl="https://example.org/1")
        self.assertEqual("Egypt", make_job(raw, source, self.now)["country"])
        self.assertEqual("United States", make_job(dict(raw, country="United States"), source, self.now)["country"])
        self.assertEqual("", make_job(raw, dict(source, locationCountryMap={}), self.now)["country"])
        self.assertEqual("Saudi Arabia", make_job(dict(raw, location="KSA"), source, self.now)["country"])
        self.assertEqual("", make_job(dict(raw, location="All Sites"), source, self.now)["country"])

    def test_jibe_country_dates_and_bounded_pagination(self):
        payload = dict(totalCount=125, jobs=[dict(data=dict(
            slug="12758", title="Land Surveyor", city="Al Madinah", country="Saudi Arabia",
            posted_date="2026-09-14T11:27:00+0000", applyable=True)),
            dict(data=dict(slug="12345", title="Surveyor", applyable=False)),
            dict(data=None)])
        url = "https://careers.keo.com/api/jobs?keywords=surveyor&limit=100&page=1"
        rows, links = jibe(json.dumps(payload), url)
        self.assertEqual(1, len(rows))
        self.assertEqual("Saudi Arabia", rows[0]["country"])
        self.assertEqual("https://careers.keo.com/jobs/12758", rows[0]["applyUrl"])
        self.assertIn("page=2", links[0])
        _, last_links = jibe(json.dumps(payload), links[0])
        self.assertEqual([], last_links)
        with self.assertRaises(ValueError):
            jibe('{"jobs":{}}', url)

    def test_dar_only_reads_public_job_fields_and_preserves_spa_job_identity(self):
        payload = [dict(Id=2321, Position="Land Surveyor", JobLocation="Riyadh",
                        PostedDate="2026-09-19T22:00:00", IsExpired=False,
                        EmailCVs="not-exported@example.org", UserId="not-exported", PayScaleFrom=100),
                   dict(Id=2322, Position="Land Surveyor", JobLocation="Riyadh"),
                   dict(Id=2323, Position="Land Surveyor", IsExpired=True)]
        url = "https://careers.daralriyadh.com/Api/PublishedOpportnitiesAPI/GetPublishedOpportunities"
        rows = dar_al_riyadh(json.dumps(payload), url)
        source = dict(name="Dar", url=url)
        jobs = [make_job(row, source, self.now) for row in rows]
        self.assertEqual(2, len(deduplicate(jobs)))
        self.assertTrue(jobs[0]["applyUrl"].endswith("/#/JobDetails/2321"))
        self.assertNotIn("not-exported", json.dumps(rows))
        self.assertNotIn("PayScaleFrom", json.dumps(rows))
        self.assertEqual("https://example.org/", normalize_url("https://example.org/#tracking"))
        with self.assertRaises(ValueError):
            dar_al_riyadh('{}', url)

    def test_gis_hub_reads_data_without_executing_scripts_and_keeps_source_attribution(self):
        row = dict(slug="gis-specialist", title="GIS Specialist", company_name="Geo Co",
                   country="Egypt", city="Cairo", posted_at="2026-10-15T10:00:00Z",
                   closes_at="2026-11-15T00:00:00Z", summary="Field GIS", location_type="Remote",
                   application_url="https://elsewhere.example/apply")
        packet = json.dumps([1, '1c:' + json.dumps({"job": row, "duplicate": {"job": row}})])
        body = '<script>self.__next_f.push(' + packet + ')</script><script>alert("never run")</script>'
        rows = gis_career_hub(body, "https://giscareerhub.com/gis-jobs/location/egypt")
        self.assertEqual(1, len(rows))
        self.assertEqual("Egypt", rows[0]["country"])
        self.assertEqual(row["posted_at"], rows[0]["postedAt"])
        self.assertTrue(rows[0]["remote"])
        self.assertEqual("https://giscareerhub.com/jobs/gis-specialist", rows[0]["applyUrl"])
        with self.assertRaises(ValueError):
            gis_career_hub('<script>self.__next_f.push(broken)</script>', "https://example.org")
        self.assertEqual([], gis_career_hub('<script type="application/ld+json">'
                         '{"@type":"ItemList","numberOfItems":0}</script>', "https://example.org"))

    def test_empty_smartrecruiters_search_is_valid_but_blank_career_page_is_not(self):
        source = dict(type="smartrecruiters_html")
        self.assertEqual(([], []), parse("", "https://careers.smartrecruiters.com/Board/api/groups?search=GIS", source))
        with self.assertRaises(ValueError):
            parse("", "https://careers.smartrecruiters.com/Board", source)

    def test_anonymous_ats_company_uses_the_known_recruitment_source(self):
        raw = dict(title="GIS Engineer", company="Company", applyUrl="https://example.org/1")
        job = make_job(raw, dict(name="Talent360", company="Talent360", url="https://example.org"), self.now)
        self.assertEqual("Talent360", job["company"])


if __name__ == "__main__":
    unittest.main()
