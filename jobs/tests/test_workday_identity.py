import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from jobs.collector import main
from jobs.collector.model import make_job, iso


class WorkdayIdentityTests(unittest.TestCase):
    def test_corrected_location_keeps_existing_id_discovery_and_notification_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=dict(enabled=True,name='Field Careers',company='Field',type='workday',
                url='https://field.wd1.myworkdayjobs.com/wday/cxs/field/Jobs/jobs?search=GIS&offset=0',
                publicBaseUrl='https://field.wd1.myworkdayjobs.com/en-US/Jobs',searchTerms=['GIS'],maxPagesPerTerm=1)
            instant=datetime.now(timezone.utc)
            apply='https://field.wd1.myworkdayjobs.com/en-US/Jobs/job/Canberra-Australia/GIS-Technician_R-123'
            old=make_job(dict(title='GIS Technician',location='R-123',city='123',applyUrl=apply),source,instant)
            main.save(root/'jobs/config/sources.json',dict(sources=[source],checkLinksPerRun=0))
            main.save(root/'jobs/config/keywords.json',dict(include=['GIS'],exclude=[]))
            main.save(root/'public/jobs/jobs.json',dict(version=1,totalJobs=1,jobs=[old],generatedAt=iso(instant)))
            main.save(root/'jobs/state.json',dict(seen=[old['id']],notified=[old['id']],pending=[]))
            fetcher=Mock(remaining=9)
            fetcher.request.return_value=(200,json.dumps(dict(total=1,jobPostings=[dict(title='GIS Technician',
                externalPath='/job/Canberra-Australia/GIS-Technician_R-123',locationsText='2 Locations',bulletFields=['R-123'])])))
            with patch.object(main,'ROOT',root),patch.object(main,'Fetcher',return_value=fetcher):
                main.collect()
            feed=main.load(root/'public/jobs/jobs.json',{})
            state=main.load(root/'jobs/state.json',{})
            self.assertEqual(1,feed['totalJobs'])
            self.assertEqual(old['id'],feed['jobs'][0]['id'])
            self.assertEqual(old['discoveredAt'],feed['jobs'][0]['discoveredAt'])
            self.assertEqual('AU',feed['jobs'][0]['countryCode'])
            self.assertEqual([],state['pending'])
            self.assertEqual([old['id']],state['notified'])


if __name__=='__main__':unittest.main()
