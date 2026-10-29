"""Actual unrelated title collisions found while verifying global employer boards."""
import json
import unittest
from pathlib import Path

from jobs.collector.model import relevant, quantity_surveying_role


class GlobalRelevanceTests(unittest.TestCase):
    def setUp(self):
        self.keywords = json.loads((Path(__file__).resolve().parents[1] / 'config/keywords.json').read_text('utf-8'))

    def test_unrelated_inspection_valuation_and_quantity_roles_are_excluded(self):
        titles = ('Senior Quanity Surveyor', 'DATEP Surveyor- Atlanta', 'Lead NTP Surveyor- Atlanta',
            'Community Living Arrangements (CLA) Licensure Surveyor- Atlanta', 'Guest Surveyor',
            'Assisted Living Surveyor', 'Nurse Consultant I (Nursing Home Surveyor)',
            'Facility Compliance Consultant I (Nursing Home Surveyor - LPNs, Dietitians, Social Workers)',
            'Housing Surveyor', 'Residential Surveyor and Valuer', 'Senior Estates Surveyor',
            'Stock Condition Surveyor', '5871 - Principal Valuation Surveyor - Lanarkshire Valuation Joint Board',
            'Electrical Surveyor', 'Gas Installation Surveying Engineer', 'Junior Cargo Surveyor | Taranto')
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(relevant(title, self.keywords))

    def test_valid_field_and_geospatial_titles_still_match(self):
        for title in ('Land Surveyor', 'Boundary Surveyor', 'County Surveyor', 'GIS Analyst',
                      'Geospatial Engineer', 'Utility Surveyor', 'Chief Mine Surveyor',
                      'Hydrographic Surveyor', 'Survey Technician', 'Survey Party Chief'):
            with self.subTest(title=title):
                self.assertTrue(relevant(title, self.keywords))

    def test_quantity_typo_cannot_reenter_from_cached_feed(self):
        self.assertTrue(quantity_surveying_role('Senior Quanity Surveyor'))
        self.assertTrue(quantity_surveying_role('Quantitiy Surveyor'))
        self.assertFalse(quantity_surveying_role('Quantity control for survey data'))


if __name__ == '__main__':
    unittest.main()
