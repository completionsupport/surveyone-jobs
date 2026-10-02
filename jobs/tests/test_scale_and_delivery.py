import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from jobs.collector import main, notify
from jobs.collector.model import iso
from jobs.collector.model import infer_country
from jobs.collector.parsers import greenhouse
from jobs.collector.registry import enabled_sources, rotated_sources, source_key


class RegistryTests(unittest.TestCase):
    def test_middle_east_workday_country_codes_are_inferred(self):
        for location, expected in [("AE - Dubai", "United Arab Emirates"),
                                   ("SA.Riyadh", "Saudi Arabia"),
                                   ("Cairo, EGY", "Egypt"),
                                   ("QA - Doha", "Qatar"),
                                   ("Kuwait City, KWT", "Kuwait")]:
            self.assertEqual(expected, infer_country(location))

    def test_thousand_unique_boards_round_robin_without_starvation(self):
        # Synthetic offline fixture only; these are NOT counted as real sources.
        sources = [dict(enabled=True, name=f"Fixture {i}", url=f"https://example.org/board/{i}") for i in range(1000)]
        self.assertEqual(1000, len(enabled_sources(dict(sources=sources))))
        visited, cursor = [], None
        for _ in range(10):
            batch = rotated_sources(sources, cursor)[:100]
            visited.extend(source_key(s) for s in batch)
            cursor = source_key(batch[-1])
        self.assertEqual(1000, len(set(visited)))
        self.assertEqual(source_key(sources[0]), source_key(rotated_sources(sources, cursor)[0]))

    def test_same_board_country_filters_do_not_inflate_source_count(self):
        with self.assertRaises(ValueError):
            enabled_sources(dict(sources=[dict(enabled=True, name="Egypt", url="https://example.org/jobs?country=eg"),
                                         dict(enabled=True, name="Saudi", url="https://example.org/jobs?country=sa")]))

    def test_invalid_greenhouse_response_is_not_a_healthy_empty_feed(self):
        for body in ('{}', '{"error":"Not found"}', '[]'):
            with self.assertRaises(ValueError):
                greenhouse(body)
        self.assertEqual([], greenhouse('{"jobs":[]}'))

    def test_http_404_source_reported_failed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            main.save(root / "jobs/config/sources.json", {"sources": [dict(enabled=True, name="Gone", url="https://example.org/jobs")], "checkLinksPerRun": 0})
            main.save(root / "jobs/config/keywords.json", {"include": ["Land Surveyor"], "exclude": []})
            fetcher = Mock(remaining=12)
            fetcher.request.return_value = (404, "")
            with patch.object(main, "ROOT", root), patch.object(main, "Fetcher", return_value=fetcher):
                main.collect()
            self.assertEqual("failed", main.load(root / "jobs/state.json", {})["sourceHealth"]["Gone"]["status"])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root_patch = patch.object(notify, "ROOT", self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()

    def test_test_mode_refuses_production_topics_and_tokens(self):
        for topic in ("survey_jobs_eg", "survey_jobs_all", "a-device-token", "surveyone_jobs_qa_not-random"):
            with self.assertRaises(ValueError):
                notify.send(topic, "eg")

    def test_test_mode_requires_a_real_current_country_job(self):
        with self.assertRaises(ValueError):
            notify.send("surveyone_jobs_qa_" + "a" * 32, "eg")

    def test_qa_payload_is_isolated_and_does_not_touch_production_state(self):
        job = dict(id="real-job", country="Saudi Arabia", discoveredAt=iso(datetime.now(timezone.utc)))
        main.save(self.root / "public/jobs/jobs.json", {"jobs": [job]})
        main.save(self.root / "jobs/state.json", {"pending": ["real-job"], "notified": []})
        before = (self.root / "jobs/state.json").read_bytes()
        credentials = Mock(token="test-only-fake-token")
        with patch("google.oauth2.service_account.Credentials.from_service_account_info", return_value=credentials), \
             patch.dict(os.environ, FIREBASE_SERVICE_ACCOUNT=json.dumps({"project_id": "test-project"})), \
             patch("requests.post", return_value=Mock(status_code=200)) as post:
            notify.send("surveyone_jobs_qa_" + "a" * 32, "sa")
        message = post.call_args.kwargs["json"]["message"]
        self.assertEqual("surveyone_jobs_qa_" + "a" * 32, message["topic"])
        self.assertEqual("survey_jobs", message["data"]["destination"])
        self.assertEqual("real-job", message["data"]["job_id"])
        self.assertEqual(before, (self.root / "jobs/state.json").read_bytes())
        report = main.load(self.root / "jobs/notification-delivery.json", {})
        self.assertEqual("accepted_by_fcm", report["outcomes"][0]["status"])
        self.assertNotIn("test-only-fake-token", json.dumps(report))

    def test_country_groups_never_fall_back_to_global(self):
        for country, expected in [("Egypt", "eg"), ("Saudi Arabia", "sa"), ("Poland", "pl"), ("Unknown", None), ("مص", None)]:
            self.assertEqual(expected, notify.country_code(country))


if __name__ == "__main__":
    unittest.main()
