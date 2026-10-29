"""Portable offline government-parser regressions; no network or external caches."""
import json
import unittest
from urllib.parse import parse_qs, urlsplit
from jobs.collector import government


def france_card(ident, title, place='74 - Annecy', company='GEOFIT', description='Levé topographique et implantation GNSS.'):
    return (f'<li class="result" data-id-offre="{ident}"><a class="media"><h2><span class="media-heading-title">{title}</span></h2>'
        f'<p class="subtext">{company} - <span>{place}</span></p><p class="description">{description}</p>'
        '<p class="contrat">CDI - Temps plein</p><p class="date">Publié il y a 17 jours</p></a></li>')


class GovernmentParserTests(unittest.TestCase):
    def setUp(self):
        self.se = dict(searchTerms=['lantmätare', 'GIS'], maxPagesPerTerm=2)
        self.se_url = 'https://jobsearch.api.jobtechdev.se/search?q=lantm%C3%A4tare&limit=100&offset=0'
        self.fr = dict(searchTerms=['geometre', 'SIG'], maxPagesPerTerm=15)
        self.fr_url = 'https://candidat.francetravail.fr/offres/recherche?motsCles=geometre&offresPartenaires=false&range=0-19&tri=1'
        self.ca = dict(occupationCodes=['21203', '22213', '22214'])
        self.ca_url = 'https://www.jobbank.gc.ca/jobsearch/feed/jobSearchRSSfeed?fn21=22213&fsrc=16&sort=D&rows=100&fage=30'

    def test_sweden_numeric_country_code_is_not_iso_and_removed_ad_is_ignored(self):
        hit = dict(id='31660084', headline='Handläggare Lantmäteri', removed=False,
            employer={'name': 'Jämtkraft Aktiebolag'}, occupation={'label': 'Lantmätare/Förrättningslantmätare'},
            workplace_address={'country': 'Sverige', 'country_code': '199', 'city': 'Östersund'},
            publication_date='2026-10-29T10:47:47', application_deadline='2026-11-23T23:59:59',
            webpage_url='https://arbetsformedlingen.se/platsbanken/annonser/31660084')
        body = json.dumps({'total': {'value': 201}, 'hits': [hit, {**hit, 'id': '2', 'removed': True}]})
        rows, links = government.parse_jobtech(body, self.se_url, self.se)
        self.assertEqual(1, len(rows))
        self.assertEqual('Sweden', rows[0]['country'])
        self.assertEqual('Östersund, Sweden', rows[0]['location'])
        self.assertEqual('2026-10-29', rows[0]['postedAt'])
        self.assertEqual('2026-11-23T00:00:00Z', rows[0]['expiresAt'])
        self.assertEqual('2026-11-23T23:59:59', rows[0]['originalApplicationDeadline'])
        self.assertTrue(any('offset=100' in link for link in links))
        self.assertTrue(any('q=GIS' in link for link in links))

    def test_sweden_invalid_schema_and_unapproved_term_are_rejected(self):
        with self.assertRaises(ValueError):
            government.parse_jobtech('{}', self.se_url, self.se)
        with self.assertRaises(ValueError):
            government.parse_jobtech('{"total":{"value":0},"hits":[]}', self.se_url.replace('lantm%C3%A4tare', 'anything'), self.se)

    def test_sweden_broad_occupation_and_category_hint_do_not_admit_valuation_or_generic_jobs(self):
        base = dict(id='31660084', employer={'name': 'Employer'},
            occupation={'label': 'Civilingenjör, lantmäteri'},
            workplace_address={'country': 'Sverige'},
            webpage_url='https://arbetsformedlingen.se/platsbanken/annonser/31660084')
        hits = [{**base, 'headline': 'Fastighetsvärderare till Svefa i Göteborg',
                 'description': {'text': 'Fastighetsvärdering och rådgivning.'}},
                {**base, 'headline': 'General administrator',
                 'description': {'text': 'Office administration and payroll.'}},
                {**base, 'headline': 'Skoglig underhållsingenjör',
                 'description': {'text': 'Arbetat med GIS. ArcGIS och Field Maps för fältbesök.'}}]
        rows, _ = government.parse_jobtech(json.dumps({'total': {'value': 3}, 'hits': hits}), self.se_url, self.se)
        self.assertEqual(['Skoglig underhållsingenjör'], [row['title'] for row in rows])

    def test_france_territories_and_unknown_employer_preserve_facts(self):
        body = '<h1>5 offres</h1><ul class="result-list">' + ''.join(
            france_card(str(2000000 + i), 'Géomètre topographe (H/F)', place, '') for i, place in enumerate([
                '974 - Saint-Denis', '976 - Mamoudzou', '973 - Cayenne', '971 - Pointe-à-Pitre', '99 - Suisse'])) + '</ul>'
        rows, _ = government.parse_france_travail(body, self.fr_url, self.fr)
        self.assertEqual(['Réunion', 'Mayotte', 'French Guiana', 'Guadeloupe', 'Switzerland'], [row['country'] for row in rows])
        self.assertTrue(all(row['company'] == 'Employeur non précisé' for row in rows))
        self.assertTrue(all(row['postedAt'] is None and row['postedDateUnknown'] for row in rows))

    def test_france_admin_quantity_and_process_mapping_do_not_become_survey_jobs(self):
        body = '<h1>5 offres</h1><ul class="result-list">' + ''.join([
            france_card('2150001', 'SECRETAIRE DE GEOMETRE EXPERT (H/F)'),
            france_card('2150002', 'Dessinateur métreur (H/F)'),
            france_card('2150003', 'Cartographe des processus (H/F)', description='Cartographie applicative du système financier.'),
            france_card('2150004', 'Chef de projet SIG (H/F)', description='Gestion commerciale et comptabilité ERP.'),
            france_card('2150005', 'Technicien SIG (H/F)', description='Base ArcGIS et données géographiques.'),
        ]) + '</ul>'
        rows, _ = government.parse_france_travail(body, self.fr_url, self.fr)
        self.assertEqual(['Technicien SIG (H/F)'], [row['title'] for row in rows])

    def test_france_pagination_is_bounded_and_search_terms_are_whitelisted(self):
        body = '<h1>274 offres pour geometre</h1><ul class="result-list"></ul>'
        _, links = government.parse_france_travail(body, self.fr_url, self.fr)
        self.assertEqual(2, len(links))
        self.assertEqual('20-39', parse_qs(urlsplit(links[0]).query)['range'][0])
        _, final_links = government.parse_france_travail(body, self.fr_url.replace('0-19', '260-279'), self.fr)
        self.assertEqual([], final_links)
        with self.assertRaises(ValueError):
            government.parse_france_travail(body, self.fr_url.replace('geometre', 'anything'), self.fr)

    def test_canadian_atom_keeps_employer_timestamp_and_removes_session_id(self):
        body = '''<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>land survey technician</title>
          <link rel="alternate" href="https://www.jobbank.gc.ca/jobsearch/jobposting/50608624;jsessionid=PUBLIC?source=searchresults"/>
          <updated>2026-10-29T05:29:00Z</updated><summary type="html"><![CDATA[
          <strong>Job number:</strong> 3705562<br/><strong>Location:</strong> Mont-Tremblant (QC)<br/>
          <strong>Employer:</strong> Boréal-arpenteurs-géomètres inc.<br/><strong>Salary:</strong> $36 hourly]]></summary></entry></feed>'''
        rows, _ = government.parse_canada_jobbank(body, self.ca_url, self.ca)
        self.assertEqual(1, len(rows))
        self.assertEqual('Boréal-arpenteurs-géomètres inc.', rows[0]['company'])
        self.assertEqual('Canada', rows[0]['country'])
        self.assertEqual('2026-10-29T05:29:00Z', rows[0]['postedAt'])
        self.assertEqual('https://www.jobbank.gc.ca/jobsearch/jobposting/50608624', rows[0]['applyUrl'])

    def test_canadian_html_first_party_only_and_non_geospatial_weather_is_ignored(self):
        def card(title, publisher, ident):
            return f'<a class="resultJobItem" href="/jobsearch/jobposting/{ident}"><span class="noctitle">{title}</span><li class="business">Employer</li><li class="location">Location Langley (BC)</li><li class="date">October 23, 2026</li><li class="source"><span class="wb-inv">{publisher}</span></li></a>'
        body = '<div class="results-jobs">' + card('instrument man/woman - surveying', 'Job Bank', '1001') + card('land surveyor', 'CareerBeacon', '1002') + card('weather observer', 'Job Bank', '1003') + '</div>'
        rows, _ = government.parse_canada_jobbank(body, self.ca_url, self.ca)
        self.assertEqual(['instrument man/woman - surveying'], [row['title'] for row in rows])
        self.assertEqual('2026-10-23', rows[0]['postedAt'])

    def test_canadian_untrusted_sources_and_xml_entities_are_rejected(self):
        with self.assertRaises(ValueError):
            government.parse_canada_jobbank('<feed/>', self.ca_url.replace('fsrc=16', 'fsrc=1'), self.ca)
        with self.assertRaises(ValueError):
            government.parse_canada_jobbank('<!DOCTYPE feed [<!ENTITY a SYSTEM "https://example.org/">]><feed/>', self.ca_url, self.ca)


if __name__ == '__main__':
    unittest.main()
