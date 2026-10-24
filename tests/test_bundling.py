import os
import sys
import unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models import User, Product, PromoBundle

class BundlingTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_bundle_model_and_calculation(self):
        # Ambil atau buat bundle
        bundle = PromoBundle.query.filter_by(sku_1='TSEL20', sku_2='PLN20').first()
        self.assertIsNotNone(bundle)
        p1, p2 = bundle.get_products()
        self.assertIsNotNone(p1)
        self.assertIsNotNone(p2)

        # Mock user
        class DummyUser:
            role = 'MEMBER'
        
        calc = bundle.calculate_prices(DummyUser())
        self.assertIn('total_normal', calc)
        self.assertIn('discount_amount', calc)
        self.assertIn('final_price', calc)
        self.assertEqual(calc['final_price'], calc['total_normal'] - calc['discount_amount'])
        self.assertEqual(calc['discount_amount'], bundle.discount_amount)

    def test_user_bundling_page(self):
        res = self.client.get('/bundling')
        # Harus merespon 200 OK
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Promo Bundling', res.data)

    def test_search_products_api(self):
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_id'] = 1

        res = self.client.get('/admin/bundling/api/search_products?q=TSEL')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['success'])
        self.assertIsInstance(data['products'], list)
