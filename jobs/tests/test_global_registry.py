import json
import unittest
from pathlib import Path

from jobs.collector.registry import enabled_sources, source_key


class GlobalRegistryTests(unittest.TestCase):
    def test_global_registry_has_500_distinct_enabled_boards_and_bounded_runs(self):
        root=Path(__file__).resolve().parents[2]
        config=json.loads((root/'jobs/config/sources.json').read_text('utf-8'))
        sources=enabled_sources(config)
        self.assertGreaterEqual(len(sources),500)
        self.assertEqual(len(sources),len({source_key(source) for source in sources}))
        self.assertGreaterEqual(config['maxSourcesPerRun'],500)
        self.assertLessEqual(config['maxRunSeconds'],900)
        for source in sources:
            self.assertTrue(source['url'].startswith('https://'))
            self.assertLessEqual(source.get('maxRequestsPerSource',config['maxRequestsPerSource']),24)

    def test_collected_feed_remains_within_published_android_contract(self):
        path=Path(__file__).resolve().parents[2]/'public/jobs/jobs.json'
        payload=path.read_bytes()
        feed=json.loads(payload)
        self.assertEqual(1,feed['version'])
        self.assertEqual(feed['totalJobs'],len(feed['jobs']))
        self.assertEqual(len(feed['jobs']),len({j['id'] for j in feed['jobs']}))
        self.assertLessEqual(len(feed['jobs']),10000)
        self.assertLessEqual(len(payload),4*1024*1024)
        for job in feed['jobs']:
            if job.get('countryCode'):
                self.assertRegex(job['countryCode'],r'^[A-Z]{2}$')
                self.assertEqual(job['countryCode'],job['country'])


if __name__=='__main__':unittest.main()
