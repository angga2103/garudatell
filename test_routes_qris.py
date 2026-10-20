import os
import sys
import unittest
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.services.setting_service import set_setting_value, invalidate_setting_cache

class TestQrisRoutes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Set active gateway ke 'dana'
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()

        # User dummy
        self.user = User.query.filter_by(phone="08888888888").first()
        if not self.user:
            self.user = User(
                name="Route Tester",
                phone="08888888888",
                email="route_tester@example.com",
                balance=100000.0,
                role="MEMBER",
            )
            self.user.set_password("pass1234")
            db.session.add(self.user)
            db.session.commit()

        # Product dummy
        self.product = Product.query.filter_by(sku_code="TEST_ROUTE_SKU").first()
        if not self.product:
            self.product = Product(
                sku_code="TEST_ROUTE_SKU",
                name="Produk Uji Route",
                category="Pulsa",
                brand="TELKOMSEL",
                sell_price=15000.0,
                base_price=14500.0,
                is_active=True,
            )
            db.session.add(self.product)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_generate_qris_endpoint(self):
        # Buat transaksi QRIS
        ref_id = f"TEST-ROUTE-REF-{int(datetime.now().timestamp())}"
        trx = Transaction(
            ref_id=ref_id,
            user_id=self.user.id,
            sku_code=self.product.sku_code,
            product_name=self.product.name,
            target_number="08888888888",
            amount=15123.0,
            payment_method="QRIS",
            payment_status="UNPAID",
            status="UNPAID",
        )
        db.session.add(trx)
        db.session.commit()

        # Login via auth API
        login_res = self.client.post("/auth/api/auth_ajax", json={
            "action": "login",
            "phone": self.user.phone,
            "password": "pass1234"
        })
        self.assertEqual(login_res.status_code, 200)

        # Panggil endpoint /trx/generate_qris/<ref_id>
        res = self.client.get(f"/trx/generate_qris/{ref_id}")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("gateway"), "dana")
        self.assertEqual(data.get("fee"), 0)
        self.assertTrue(data.get("qr_string", "").startswith("000201010212"))
        self.assertIn("15123", data.get("qr_string"))

        # Panggil invoice
        res_inv = self.client.get(f"/trx/invoice/{ref_id}")
        self.assertEqual(res_inv.status_code, 200)
        html = res_inv.get_data(as_text=True)
        self.assertIn("DANA", html)
        self.assertIn("0% Fee", html)

        # Bersihkan
        db.session.delete(trx)
        db.session.commit()

if __name__ == "__main__":
    unittest.main()
