import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from jobs.collector import main
from jobs.collector.model import deduplicate, make_job, iso, application_key
from jobs.collector.parsers import parse
from jobs.collector.registry import source_key


class WorldwideCollectionTests(unittest.TestCase):
    def flight(self, values, page=1, total=3):
        packet=[1,'payload:'+json.dumps(dict(initialJobs=values))]
        return f'<p>Page {page} of {total}</p><script>self.__next_f.push({json.dumps(packet)})</script>'

    def test_global_initial_jobs_keeps_platform_link_and_original_application_identity(self):
        source=dict(type='gis_career_hub',resumePagination=True,maxPagesPerQuery=20)
        raw=dict(slug='earth-observation-engineer',title='Earth Observation Engineer',company_name='Geo',
            country='Australia',city='Canberra',summary='EO processing.',posted_at='2026-10-01T00:00:00Z',
            application_url='https://careers.example.org/jobs/42')
        rows,links=parse(self.flight([raw]),'https://giscareerhub.com/jobs',source)
        self.assertEqual('https://giscareerhub.com/jobs/earth-observation-engineer',rows[0]['applyUrl'])
        self.assertEqual(raw['application_url'],rows[0]['canonicalApplyUrl'])
        self.assertEqual(['https://giscareerhub.com/jobs?page=2'],links)

    def test_repeated_public_page_is_rejected_instead_of_counted_again(self):
        source=dict(type='gis_career_hub',resumePagination=True,maxPagesPerQuery=20)
        raw=dict(slug='gis-engineer',title='GIS Engineer')
        with self.assertRaises(ValueError):
            parse(self.flight([raw],page=20,total=221),'https://giscareerhub.com/jobs?page=21',source)
        _,links=parse(self.flight([raw],page=20,total=221),'https://giscareerhub.com/jobs?page=20',source)
        self.assertEqual([],links)

    def test_http_200_rate_limit_page_is_not_a_successful_empty_board(self):
        with self.assertRaises(ValueError):
            parse('<h1>Too many requests</h1><p>Please wait 30 seconds.</p>',
                  'https://giscareerhub.com/jobs',dict(type='gis_career_hub'))

    def test_literal_underscore_slug_and_all_geographically_held_page(self):
        raw=dict(slug='arc_air-research',title='Remote Sensing Researcher',country='France')
        rows,_=parse(self.flight([raw]),'https://giscareerhub.com/jobs',dict(type='gis_career_hub'))
        self.assertEqual('https://giscareerhub.com/jobs/arc_air-research',rows[0]['applyUrl'])
        wrong=dict(slug='gis-ga',title='GIS Analyst',country='Georgia',city='Atlanta',
                   latitude=33.7,longitude=-84.3,region='GA')
        rows,links=parse(self.flight([wrong]),'https://giscareerhub.com/jobs',
                        dict(type='gis_career_hub',resumePagination=True))
        self.assertEqual([],rows)
        self.assertEqual(['https://giscareerhub.com/jobs?page=2'],links)

    def test_provider_state_country_geocoder_conflicts_are_held_without_guessing(self):
        good=dict(slug='georgia-country-gis',title='GIS Analyst',country='Georgia',city='Tbilisi',
                  latitude=41.71,longitude=44.8,region='Tbilisi')
        wrong=dict(slug='georgia-state-gis',title='GIS Analyst',country='Georgia',city='Atlanta',
                   latitude=33.7,longitude=-84.3,region='GA')
        wrong_sm=dict(slug='san-marino-city-gis',title='GIS Analyst',country='San Marino',city='Los Angeles',
                      latitude=34.05,longitude=-118.2,region='CA')
        no_coordinates={**wrong,'slug':'georgia-no-coordinates','latitude':None,'longitude':None}
        ambiguous_remote={**wrong_sm,'slug':'sm-remote','region':'','city':'','location_type':'Remote'}
        rows,_=parse(self.flight([good,wrong,wrong_sm,no_coordinates,ambiguous_remote]),
                     'https://giscareerhub.com/jobs',dict(type='gis_career_hub'))
        self.assertEqual(['georgia-country-gis'],[row['applyUrl'].rsplit('/',1)[-1] for row in rows])

    def test_canonical_application_deduplicates_platform_and_employer_without_losing_other_countries(self):
        def job(job_id,url,country='United States',title='Surveyor',**extra):
            return dict(id=job_id,title=title,company='Geo',country=country,city='Test',applyUrl=url,description='',**extra)
        platform=job('platform','https://board.example.org/vacancy',canonicalApplyUrl='https://careers.example.org/jobs/1')
        employer=job('employer','https://careers.example.org/jobs/1?utm_source=board')
        another_country=job('canada','https://careers.example.org/jobs/1',country='Canada')
        self.assertEqual(['platform','canada'],[j['id'] for j in deduplicate([platform,employer,another_country])])
        different_form_role=job('different','https://careers.example.org/jobs/1',title='GIS Analyst')
        self.assertEqual(2,len(deduplicate([employer,different_form_role])))

    def test_large_distinct_fixture_is_not_semantically_merged(self):
        # Synthetic offline performance/identity fixture, never counted as real vacancies.
        jobs=[dict(id=str(i),title='Surveyor',company=f'Employer {i}',city='Site',country='Egypt',
                   description='Survey work.',applyUrl=f'https://example.org/job/{i}') for i in range(10000)]
        with patch('jobs.collector.model.SequenceMatcher') as matcher:
            self.assertEqual(10000,len(deduplicate(jobs)))
            matcher.assert_not_called()

    def test_iso_and_display_country_do_not_create_two_copies_of_the_same_vacancy(self):
        first=dict(id='1',title='GIS Analyst',company='Geo',country='US',applyUrl='https://example.org/1')
        second={**first,'id':'2','country':'United States'}
        self.assertEqual(1,len(deduplicate([first,second])))

    def test_known_ats_aliases_do_not_inflate_counts(self):
        for first,second in (
            ('https://jobs.smartrecruiters.com/Geo/744000123-gis-analyst','https://jobs.smartrecruiters.com/geo/744000123-gis-analyst?utm_source=board'),
            ('https://apply.workable.com/j/CE094CB9F4','https://apply.workable.com/geo/j/CE094CB9F4/'),
            ('https://boards.greenhouse.io/geo/jobs/123','https://job-boards.greenhouse.io/geo/jobs/123'),
            ('https://jobs.lever.co/geo/11111111-2222-3333-4444-555555555555','https://jobs.lever.co/geo/11111111-2222-3333-4444-555555555555/apply')):
            self.assertEqual(application_key(first),application_key(second))
        self.assertNotEqual(application_key('https://example.org/1'),application_key('https://example.org/2'))

    def test_pagination_resumes_unread_urls_after_budget_without_reloading_first_page(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=dict(enabled=True,name='Large public board',type='auto',url='https://example.org/page/a',
                        resumePagination=True,maxRequestsPerSource=3,pollIntervalHours=12)
            main.save(root/'jobs/config/sources.json',dict(sources=[source],checkLinksPerRun=0))
            main.save(root/'jobs/config/keywords.json',dict(include=['Surveyor'],exclude=[]))
            requested=[]
            class Fetcher:
                def __init__(self,*args):self.remaining=3
                def request(self,url):
                    requested.append(url);self.remaining-=1
                    return 200,url
            def records(body,url,config):
                name=url.rsplit('/',1)[-1]
                links=['https://example.org/page/b','https://example.org/page/c'] if name=='a' else []
                return [dict(title='Surveyor',country='Egypt',applyUrl='https://example.org/job/'+name)],links
            with patch.object(main,'ROOT',root),patch.object(main,'Fetcher',Fetcher),patch.object(main,'parse',records):
                main.collect()
                state=main.load(root/'jobs/state.json',{})
                self.assertEqual(['https://example.org/page/c'],state['sourceContinuations'][source_key(source)])
                state['sourceHealth'][source['name']]['lastSuccess']=iso(datetime.now(timezone.utc))
                main.save(root/'jobs/state.json',state)
                main.collect()
            self.assertEqual(['https://example.org/page/a','https://example.org/page/b','https://example.org/page/c'],requested)
            self.assertNotIn(source_key(source),main.load(root/'jobs/state.json',{})['sourceContinuations'])
            self.assertEqual(3,main.load(root/'public/jobs/jobs.json',{})['totalJobs'])

    def test_new_exclusions_also_remove_cached_scraped_roles_without_requiring_a_new_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);now=datetime.now(timezone.utc)
            source=dict(name='Test',url='https://example.org/jobs')
            rows=[make_job(dict(title=title,applyUrl=f'https://example.org/job/{i}'),source,now)
                  for i,title in enumerate(('Land Surveyor','Singapore Geomatics Scholarship','Fire Surveyor'))]
            main.save(root/'jobs/config/sources.json',dict(sources=[]))
            main.save(root/'jobs/config/keywords.json',dict(include=['surveyor'],exclude=['geomatics scholarship','fire surveyor']))
            main.save(root/'public/jobs/jobs.json',dict(version=1,totalJobs=3,jobs=rows))
            with patch.object(main,'ROOT',root),patch.object(main,'Fetcher') as fetcher:
                main.collect();fetcher.assert_not_called()
            self.assertEqual(['Land Surveyor'],[j['title']for j in main.load(root/'public/jobs/jobs.json',{})['jobs']])


if __name__=='__main__':unittest.main()
