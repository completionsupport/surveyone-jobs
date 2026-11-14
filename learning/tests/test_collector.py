import datetime as dt
import json
import unittest
import urllib.error
from learning.collector import discover, verify, relevant, learning_tags

SOURCE = {"channelId": "UC1234567890123456789012", "name": "Teacher", "language": "en", "topic": "FIELD"}
def feed(title="How to set up a total station", video="abcdefghijk", channel=SOURCE["channelId"]):
    return f'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015"><yt:channelId>{channel}</yt:channelId><entry><yt:videoId>{video}</yt:videoId><title>{title}</title><published>2026-01-01T12:00:00Z</published></entry></feed>'''.encode()
class CollectorTest(unittest.TestCase):
    def test_realistic_rss_topic_and_original_title(self):
        rows = discover(feed(), SOURCE, dt.datetime(2026, 11, 14, tzinfo=dt.timezone.utc))
        self.assertEqual(rows[0]["titleAr"], rows[0]["titleEn"])
        self.assertEqual(rows[0]["language"], "en")
        self.assertEqual(rows[0]["url"], "https://www.youtube.com/watch?v=abcdefghijk")
    def test_unrelated_promotional_and_injected_ids_are_not_lessons(self):
        now = dt.datetime.now(dt.timezone.utc)
        for title, video in [("Our new product launch", "abcdefghijk"), ("How to cook dinner", "abcdefghijk"), ("RTK guide", "../../bad"), ("How many survey projects can it hold?", "abcdefghijk"), ("بدأت قناة اتعلم مساحة بثًا مباشرًا", "abcdefghijk")]:
            self.assertEqual([], discover(feed(title, video), SOURCE, now))
    def test_wrong_channel_and_entities_are_rejected(self):
        with self.assertRaises(ValueError): discover(feed(channel="wrong"), SOURCE, dt.datetime.now(dt.timezone.utc))
        with self.assertRaises(ValueError): discover(b'<!DOCTYPE x><feed/>', SOURCE, dt.datetime.now(dt.timezone.utc))
    def test_future_entries_are_not_published(self):
        self.assertEqual([], discover(feed(), SOURCE, dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)))
    def test_youtube_root_channel_omits_uc_prefix(self):
        self.assertEqual(1, len(discover(feed(channel=SOURCE["channelId"][2:]), SOURCE, dt.datetime.now(dt.timezone.utc))))
    def test_oembed_preserves_curated_translation(self):
        row={"videoId":"abcdefghijk", "url":"https://www.youtube.com/watch?v=abcdefghijk", "titleAr":"شرح معتمد"}
        result,status=verify(row, 1000, lambda _:json.dumps({"type":"video","provider_name":"YouTube","author_name":"Original teacher","title":"Original"}).encode())
        self.assertEqual(result["titleAr"],"شرح معتمد");self.assertEqual(status,"verified")
    def test_deleted_is_removed_and_outage_has_bounded_retention(self):
        row={"videoId":"abcdefghijk", "url":"https://www.youtube.com/watch?v=abcdefghijk", "verifiedAtMs":1000}
        def gone(_): raise urllib.error.HTTPError("public",404,"removed",{},None)
        def offline(_): raise OSError("offline")
        self.assertIsNone(verify(row,2000,gone)[0])
        self.assertIsNotNone(verify(row,2000,offline)[0])
        self.assertIsNone(verify(row,9*86400000,offline)[0])
    def test_unsafe_url_is_never_requested(self):
        self.assertEqual((None,"invalid-id"), verify({"videoId":"abcdefghijk","url":"https://evil.test/"},1000,lambda _:self.fail()))
    def test_product_ads_and_unrelated_training_do_not_become_lessons(self):
        for title in ['SLAM RTK in one workflow', 'GEODNET $695 RTK Receiver Is HERE', 'AutoCAD for mechanical engineers - Complete tutorial', 'How to Market a Land Surveying Business | Hawaii Surveying Case Study']:
            self.assertFalse(relevant(title), title)
        for title in ['X-PAD Tutorials: TOTAL STATION calibration', 'شرح سيفيل حساب كميات الحفر والردم', 'Surfer - Import and Export DWG Files']:
            self.assertTrue(relevant(title), title)
    def test_search_tags_link_arabic_and_english_subject_names(self):
        self.assertIn('Sokkia', learning_tags('شرح سوكيا توتال استيشن'))
        self.assertIn('توتال ستيشن', learning_tags('Sokkia total station tutorial'))
        self.assertIn('Civil 3D', learning_tags('شرح سيفيل'))
    def test_non_matching_language_feed_titles_are_not_mislabeled(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.assertEqual([], discover(feed('Total station tutorial in Hindi'), SOURCE, now))
        self.assertEqual([], discover(feed('Total station tutorial'), {**SOURCE,'language':'ar'}, now))
if __name__ == '__main__': unittest.main()
