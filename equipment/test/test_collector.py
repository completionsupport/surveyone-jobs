import json
import unittest
from unittest.mock import patch
from equipment.collector import product, canonical, category, allowed

def html(p):return '<script type="application/ld+json">'+json.dumps(p)+'</script>'
def item(**kwargs):return {'@type':'Product','name':'Leica TS16 Total Station','url':'https://supplier.example.com/product/ts16','image':'https://supplier.example.com/images/ts16.jpg','offers':{'@type':'Offer','availability':'https://schema.org/InStock','price':'123.45','priceCurrency':'USD'},**kwargs}
URL='https://supplier.example.com/product/ts16'

class EquipmentCollectorTest(unittest.TestCase):
    def test_correct_product_image_and_exact_minor_price(self):
        p=product(html(item()),URL)
        self.assertEqual(p['priceMinor'],12345)
        self.assertEqual(p['imageUrl'],'https://supplier.example.com/images/ts16.jpg')
        self.assertEqual(p['availability'],'AVAILABLE')
    def test_unknown_stock_never_renews(self):
        self.assertEqual(product(html(item(offers={})),URL)['availability'],'UNKNOWN')
        self.assertIsNone(product('<html>Generic shop homepage</html>',URL))
    def test_out_of_stock_not_confused_with_other_products(self):
        p=item(offers={'availability':'https://schema.org/OutOfStock'})
        self.assertEqual(product(html([item(url=URL+'/related'),p]),URL)['availability'],'UNAVAILABLE')
    def test_ambiguous_related_products_not_used(self):
        self.assertIsNone(product(html([item(url='https://supplier.example.com/a'),item(url='https://supplier.example.com/b')]),URL))
    def test_variant_price_is_not_invented(self):
        p=item(offers=[{'availability':'https://schema.org/InStock','price':'10','priceCurrency':'USD'},{'availability':'https://schema.org/InStock','price':'20','priceCurrency':'USD'}])
        self.assertIsNone(product(html(p),URL)['priceMinor'])
    def test_malformed_structured_fields_do_not_stop_collection(self):
        self.assertIsNone(product(html({'@type':None}),URL))
        p=product(html(item(url={'wrong':'type'},image={'url':[]})),URL)
        self.assertEqual(p['availability'],'AVAILABLE')
        self.assertEqual(p['imageUrl'],'')
    def test_bad_or_negative_price_is_not_published(self):
        for amount in ['NaN','Infinity','-3','1,000.00','0.001']:
            p=item(offers={'availability':'https://schema.org/InStock','price':amount,'priceCurrency':'USD'})
            self.assertIsNone(product(html(p),URL)['priceMinor'])
    def test_classification_and_dedup(self):
        self.assertEqual(category('Battery for Trimble total station'),'ACCESSORIES')
        self.assertEqual(category('Leica TS16 Total Station'),'TOTAL_STATION')
        self.assertIsNone(category('Office chair'))
        self.assertEqual(canonical('https://supplier.example.com/collections/survey/products/x?utm_source=test#photo'),'https://supplier.example.com/products/x')
    def test_block_private_network_and_foreign_redirect_hosts(self):
        with patch('equipment.collector.socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            self.assertFalse(allowed(URL,['supplier.example.com']))
        self.assertFalse(allowed('https://unapproved.example.com/a',['supplier.example.com']))
        self.assertFalse(allowed('http://supplier.example.com/a',['supplier.example.com']))
        self.assertFalse(allowed('https://user:secret@supplier.example.com/a',['supplier.example.com']))

if __name__=='__main__':unittest.main()
