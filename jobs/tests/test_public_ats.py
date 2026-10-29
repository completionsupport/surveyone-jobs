import json
import unittest
from datetime import datetime, timezone

from jobs.collector.model import make_job, relevant, date
from jobs.collector.parsers import parse
from jobs.collector.public_ats import workday_location


class PublicAtsTests(unittest.TestCase):
    def test_workday_requisition_bullet_is_not_a_location(self):
        job = dict(locationsText='2 Locations', bulletFields=['R-00181012'],
                   externalPath='/job/Canberra-Australian-Capital-Territory-Australia/GIS-Production-Engineer_R-00181012')
        location, city, country = workday_location(job)
        self.assertIn('Canberra', location)
        self.assertEqual('', city)
        self.assertEqual('Australia', country)
        self.assertNotIn('R-00181012', location)

    def test_workday_state_or_office_is_not_claimed_as_a_city(self):
        self.assertEqual(('Texas', '', 'United States'), workday_location(dict(locationsText='Texas')))
        self.assertEqual(('HDB HUB', '', ''), workday_location(dict(locationsText='HDB HUB')))
        self.assertEqual(('AE - Dubai', 'Dubai', 'United Arab Emirates'), workday_location(dict(locationsText='AE - Dubai')))
        self.assertEqual(('CA ON Toronto', '', 'Canada'), workday_location(dict(locationsText='2 Locations',externalPath='/job/CA-ON-Toronto/GIS_R1')))

    def test_workday_missing_geography_stays_unknown(self):
        self.assertEqual(('', '', ''),workday_location(dict(locationsText='3 Locations',bulletFields=['JR26556'])))

    def test_bamboohr_retains_job_locations_not_hq_and_separate_departments(self):
        source = dict(type='bamboohr', name='Civil Engineers', company='Civil Engineers',
                      url='https://civil.bamboohr.com/careers/list')
        rows = [dict(id='1', jobOpeningName='Surveyor', departmentLabel='Engineering',
                     location=dict(city='Vancouver', state='British Columbia')),
                dict(id='2', jobOpeningName='GIS Technician',
                     location=dict(city='Albany', state='New York')),
                dict(id='3', jobOpeningName='Survey Assistant', location=dict(city='All Sites'))]
        found, links = parse(json.dumps(dict(meta=dict(totalCount=3), result=rows)), source['url'], source)
        self.assertEqual([], links)
        self.assertEqual(['Canada', 'United States', ''], [j['country'] for j in found])
        self.assertEqual('Engineering', found[0]['category'])
        self.assertEqual('https://civil.bamboohr.com/careers/1', found[0]['applyUrl'])
        self.assertNotIn('postedAt', found[0])
        self.assertEqual('Canada', make_job(found[0], source, datetime.now(timezone.utc))['country'])

    def test_bamboohr_incomplete_or_malformed_responses_are_not_healthy_empty(self):
        source = dict(type='bamboohr')
        for value in ({}, {'result': []}, {'meta': {'totalCount': 2}, 'result': []}):
            with self.assertRaises(ValueError):
                parse(json.dumps(value), 'https://civil.bamboohr.com/careers/list', source)

    def test_recruitee_multiple_countries_dates_and_no_private_endpoints(self):
        value = dict(offers=[dict(title='GIS Specialist', company_name='GIS Company', status='published',
            locations=[dict(city='Cairo',country_code='EG'), dict(city='Riyadh',country_code='SA')],
            published_at='2026-10-29 10:00:00 UTC', close_at='2026-11-10T00:00:00Z',
            careers_url='https://geo.recruitee.com/o/gis-specialist',
            careers_apply_url='https://geo.recruitee.com/o/gis-specialist/c/new'),
            dict(title='Closed surveyor',status='closed',careers_url='https://geo.recruitee.com/o/closed')])
        found, links = parse(json.dumps(value),'https://geo.recruitee.com/api/offers/',dict(type='recruitee'))
        self.assertEqual(['Egypt', 'Saudi Arabia'], [j['country'] for j in found])
        self.assertEqual(datetime(2026,10,29,10,tzinfo=timezone.utc),date(found[0]['postedAt']))
        self.assertTrue(all('/c/new' not in j['applyUrl'] for j in found))
        self.assertEqual([], links)

    def test_recruitee_requires_actual_offers_shape(self):
        with self.assertRaises(ValueError):
            parse('{"message":"unauthorized"}', 'https://geo.recruitee.com/api/offers', dict(type='recruitee'))

    def test_personio_does_not_use_internal_created_date_or_guess_country(self):
        body = '<workzag-jobs><position><id>42</id><name>GIS Analyst</name><office>Berlin</office>' \
               '<createdAt>2020-01-01T00:00:00Z</createdAt><subcompany>Geo GmbH</subcompany>' \
               '<jobDescriptions><jobDescription><value><![CDATA[<p>Geospatial analysis.</p>]]></value>' \
               '</jobDescription></jobDescriptions></position></workzag-jobs>'
        found, links = parse(body,'https://geo.jobs.personio.de/xml?language=en',dict(type='personio'))
        self.assertEqual('https://geo.jobs.personio.de/job/42?language=en',found[0]['applyUrl'])
        self.assertEqual('',found[0]['country'])
        self.assertNotIn('postedAt',found[0])
        self.assertEqual('Geospatial analysis.',found[0]['description'])
        self.assertEqual([],links)

    def test_personio_rejects_entities_and_non_position_xml(self):
        for body in ('<!DOCTYPE x [<!ENTITY y "value">]><workzag-jobs/>','<error/>'):
            with self.assertRaises(ValueError):
                parse(body,'https://geo.jobs.personio.de/xml',dict(type='personio'))


if __name__ == '__main__':
    unittest.main()
