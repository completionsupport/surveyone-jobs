import unittest
from jobs.collector.countries import country_code, country_name, internal_job, published_job
from jobs.collector.taxonomy import filter_job


class PublicCountryFilterTests(unittest.TestCase):
    def test_source_country_values_equal_the_published_android_country_filter(self):
        for source_country, iso in [("Egypt","EG"),("Saudi Arabia","SA"),("مصر","EG"),("KSA","SA"),
                                    ("United Arab Emirates","AE"),("AU","AU"),("Nigeria","NG"),("Kenya","KE"),("Georgia","GE")]:
            row=published_job(dict(id="same-job",country=source_country))
            self.assertEqual(iso,row["country"])
            self.assertEqual(iso,row["countryCode"])
            self.assertEqual(country_name(iso),row["countryName"])
            self.assertEqual("same-job",row["id"])
            self.assertEqual(row,published_job(row))

    def test_internal_cached_feed_is_read_without_country_identity_churn(self):
        legacy=dict(id="x",country="Egypt",city="Cairo")
        self.assertEqual(legacy,internal_job(published_job(legacy)))
        self.assertEqual("",country_code("Worldwide"))
        self.assertEqual("",country_code("ZZ"))
        self.assertNotEqual("EG",published_job(dict(country=""))["country"])

    def test_city_and_category_aliases_match_the_same_source_and_user_filters(self):
        for country,first,second in [("EG","القاهرة","Cairo"),("SA","الرياض","Riyadh"),("SA","Al Madinah","Medina"),("SA","Tabūk","Tabuk")]:
            a=filter_job(dict(country=country,city=first,category="مساحة"))
            b=filter_job(dict(country=country,city=second,category="Land Surveying"))
            self.assertEqual(a,b)
        self.assertEqual("",filter_job(dict(country="EG",city="",location="All Sites"))["city"])
        self.assertEqual("Alexandria",filter_job(dict(country="EG",city="",location="Alexandria"))["city"])
