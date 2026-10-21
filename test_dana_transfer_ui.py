import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.services.setting_service import set_setting_value, invalidate_setting_cache

class TestDanaTransferUiFlow(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # User dummy
        self.user = User.query.filter_by(phone="08777777777").first()
        if not self.user:
            self.user = User(
                name="DANA UI Tester",
                phone="08777777777",
                email="danaui_tester@example.com",
                balance=100000.0,
                role="MEMBER",
                is_active=True
            )
            db.session.add(self.user)
        self.user.set_password("pass1234")
        self.user.is_active = True
        db.session.commit()

        # Product dummy
        self.product = Product.query.filter_by(sku_code="TEST_DANA_UI_SKU").first()
        if not self.product:
            self.product = Product(
                sku_code="TEST_DANA_UI_SKU",
                name="Pulsa DANA UI Test",
                category="Pulsa",
                brand="TELKOMSEL",
                sell_price=10500.0,
                base_price=10000.0,
                is_active=True,
            )
            db.session.add(self.product)
            db.session.commit()

    def tearDown(self):
        # Kembalikan setting default ke DANA
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()
        self.app_context.pop()

    def _login(self):
        res = self.client.post("/auth/api/auth_ajax", json={
            "action": "login",
            "phone": self.user.phone,
            "password": "pass1234"
        })
        self.assertEqual(res.status_code, 200, f"Login failed: {res.get_json()}")

    def test_dynamic_ui_when_dana_active(self):
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()

        res = self.client.get('/kategori/pulsa')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('Transfer Tunai DANA Otomatis', html)
        self.assertIn('0% Fee / Instan', html)
        self.assertNotIn('QRIS (Scan Otomatis)', html)

    def test_dynamic_ui_when_pakasir_active(self):
        set_setting_value("active_payment_gateway", "pakasir")
        invalidate_setting_cache()

        res = self.client.get('/kategori/pulsa')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('QRIS (Scan Otomatis)', html)
        self.assertIn('Semua E-Wallet & Bank', html)
        self.assertNotIn('Transfer Tunai DANA Otomatis', html)

    def test_dynamic_ui_when_pg_disabled(self):
        # Setting gateway ke 'off'
        set_setting_value("active_payment_gateway", "off")
        invalidate_setting_cache()

        res = self.client.get('/kategori/pulsa')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertNotIn('<label class="pay-option" id="optQris">', html)
        self.assertIn('Saldo Akun', html)

    def test_checkout_and_invoice_dana(self):
        self._login()
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()

        checkout_res = self.client.post('/trx/checkout', json={
            'sku_code': self.product.sku_code,
            'target_number': '08777777777',
            'payment_method': 'qris'
        })
        self.assertEqual(checkout_res.status_code, 200, f"Checkout failed: {checkout_res.get_json()}")
        data = checkout_res.get_json()
        ref_id = data.get('ref_id')
        self.assertTrue(ref_id)

        # Cek database: method tersimpan sebagai DANA karena gateway aktif adalah DANA
        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        self.assertEqual(trx.payment_method, 'DANA')

        # Cek invoice page
        inv_res = self.client.get(f'/trx/invoice/{ref_id}')
        self.assertEqual(inv_res.status_code, 200)
        inv_html = inv_res.get_data(as_text=True)
        self.assertIn('Transfer Tunai DANA Otomatis', inv_html)
        self.assertIn('id="danaPaymentCard"', inv_html)
        self.assertIn('fa-wallet', inv_html)

if __name__ == '__main__':
    unittest.main()
