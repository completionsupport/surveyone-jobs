import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobs.collector.feed_contract import encode_feed, save_feed, cache_bytes


class FeedContractTests(unittest.TestCase):
    def test_ten_thousand_small_fixture_rows_are_accepted_without_count_inflation(self):
        rows = [dict(id=str(index), title='Surveyor') for index in range(10000)]
        value = dict(version=1,totalJobs=len(rows),jobs=rows)
        self.assertEqual(value,json.loads(encode_feed(value)))

    def test_over_ten_thousand_rows_does_not_replace_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'jobs.json';path.write_text('previous','utf-8')
            with self.assertRaises(ValueError):
                save_feed(path,dict(version=1,totalJobs=10001,jobs=[{}]*10001))
            self.assertEqual('previous',path.read_text('utf-8'))

    def test_compaction_is_lossless_and_accounts_for_android_cache_escaping(self):
        value=dict(version=1,totalJobs=100,jobs=[dict(id=str(i),title='Surveyor',description='رصد "موقع"'*5) for i in range(100)])
        compact=json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n'
        limit=cache_bytes(compact)
        with patch('jobs.collector.feed_contract.MAX_FEED_BYTES',limit):
            actual=encode_feed(value)
        self.assertEqual(compact,actual)
        self.assertEqual(value,json.loads(actual))

    def test_oversized_content_is_never_silently_truncated(self):
        value=dict(version=1,totalJobs=1,jobs=[dict(id='1',description='x'*5000)])
        with patch('jobs.collector.feed_contract.MAX_FEED_BYTES',1000),self.assertRaises(ValueError):
            encode_feed(value)

    def test_inconsistent_count_is_rejected(self):
        with self.assertRaises(ValueError):encode_feed(dict(version=1,totalJobs=3,jobs=[{}]))


if __name__=='__main__':unittest.main()
