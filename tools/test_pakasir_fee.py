import sys
import os
import unittest
from unittest.mock import patch, MagicMock

# Pastikan root workspace terdaftar di sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.services.pakasir_service import calculate_pakasir_fee, PakasirService

class TestPakasirFeeSuite(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Buat user dummy untuk pengujian
        self.user = User.query.filter_by(phone='081775700114').first()
        if not self.user:
            self.user = User(
                name='Test Fee User',
                phone='081775700114',
                balance=50000,
                role='MEMBER'
            )
            self.user.set_password('password123')
            db.session.add(self.user)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_01_calculate_pakasir_fee_formula(self):
        """Uji perhitungan formula tarif resmi Pakasir (https://pakasir.com/p/pricing)"""
        print("\n[1/4] Menguji fungsi calculate_pakasir_fee...")

        # 1. Kasus nyata pengguna: Rp 7.805 (7805 * 0.007 + 310 = 364.635 -> 365)
        fee_7805 = calculate_pakasir_fee(7805, 'qris')
        total_7805 = 7805 + fee_7805
        self.assertEqual(fee_7805, 365)
        self.assertEqual(total_7805, 8170)
        print(f"  [OK] Produk Rp 7.805 -> Fee: Rp {fee_7805}, Total: Rp {total_7805} (Sesuai GoPay Review Rp 8.170!)")

        # 2. Kasus resmi dokumentasi Pakasir: Rp 99.000 (99000 * 0.007 + 310 = 1003)
        fee_99k = calculate_pakasir_fee(99000, 'qris')
        total_99k = 99000 + fee_99k
        self.assertEqual(fee_99k, 1003)
        self.assertEqual(total_99k, 100003)
        print(f"  [OK] Produk Rp 99.000 -> Fee: Rp {fee_99k}, Total: Rp {total_99k} (Sesuai Docs Pakasir!)")

        # 3. Kasus batas Rp 105.000 (105000 * 0.007 + 310 = 1045)
        fee_105k = calculate_pakasir_fee(105000, 'qris')
        self.assertEqual(fee_105k, 1045)
        print(f"  [OK] Produk Rp 105.000 -> Fee: Rp {fee_105k}")

        # 4. Kasus di atas Rp 105.000: 1% + Rp 0
        fee_150k = calculate_pakasir_fee(150000, 'qris')
        self.assertEqual(fee_150k, 1500)
        print(f"  [OK] Produk Rp 150.000 (> 105k) -> Fee: Rp {fee_150k} (1% flat)")

        # 5. Kasus Virtual Account
        self.assertEqual(calculate_pakasir_fee(50000, 'bri_va'), 3500)
        self.assertEqual(calculate_pakasir_fee(50000, 'artha_graha_va'), 2000)
        print("  [OK] Kasus Virtual Account terhitung sesuai tabel tarif!")

    @patch('requests.post')
    def test_02_pakasir_service_create_qris_returns_fee_and_total(self, mock_post):
        """Uji PakasirService.create_qris mengembalikan fee dan total_payment"""
        print("\n[2/4] Menguji PakasirService.create_qris payload parsing...")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "payment": {
                "project": "Ansor",
                "order_id": "TEST-FEE-01",
                "amount": 7805,
                "fee": 365,
                "total_payment": 8170,
                "payment_method": "qris",
                "payment_number": "00020101021226610016ID.CO.QRIS...",
                "expired_at": "2026-09-17T20:00:00Z"
            }
        }
        mock_post.return_value = mock_resp

        service = PakasirService({'project': 'Ansor', 'api_key': 'fake_key'})
        res = service.create_qris("TEST-FEE-01", 7805)
        self.assertTrue(res.get('status'))
        self.assertEqual(res.get('fee'), 365)
        self.assertEqual(res.get('total_payment'), 8170)
        self.assertEqual(res.get('amount'), 7805)
        print(f"  [OK] create_qris sukses mem-parsing fee={res.get('fee')} dan total_payment={res.get('total_payment')}")

    def test_03_invoice_html_displays_fee_and_total(self):
        """Uji tampilan halaman barcode invoice (/trx/invoice/<ref_id>) memuat informasi fee & breakdown"""
        print("\n[3/4] Menguji rendering HTML invoice (/trx/invoice/<ref_id>)...")
        os.environ['ACTIVE_PAYMENT_GATEWAY'] = 'pakasir'

        # Buat transaksi QRIS
        ref_id = f"GT-TEST-FEE-{int(os.getpid())}"
        trx = Transaction(
            user_id=self.user.id,
            ref_id=ref_id,
            product_name="XL Xtra Edukasi 15 GB 7 Hari",
            sku_code="xledu15",
            target_number="081775700114",
            amount=7805.0,
            payment_method="QRIS",
            payment_status="UNPAID",
            status="UNPAID"
        )
        db.session.add(trx)
        db.session.commit()

        # Login user
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)

        res = self.client.get(f'/trx/invoice/{ref_id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)

        # Verifikasi elemen edukasi fee
        self.assertIn("Informasi Nominal Bayar Scan QRIS", html)
        self.assertIn("8.170", html)
        self.assertIn("365", html)
        self.assertIn("Tarif Pakasir (0.7% + Rp 310)", html)
        self.assertIn("Biaya Gateway (QRIS)", html)
        self.assertIn("Harga Produk", html)
        self.assertIn("7.805", html)
        print("  [OK] Halaman invoice sukses menampilkan kotak edukasi, rincian biaya gateway Rp 365, dan total bayar scan Rp 8.170!")

    @patch('app.services.pakasir_service.PakasirService.create_qris')
    def test_04_generate_qris_endpoint_returns_fee_json(self, mock_create):
        """Uji respons JSON /trx/generate_qris/<ref_id> menyertakan fee dan total_payment"""
        print("\n[4/4] Menguji endpoint /trx/generate_qris/<ref_id>...")
        os.environ['ACTIVE_PAYMENT_GATEWAY'] = 'pakasir'

        mock_create.return_value = {
            'status': True,
            'qr_url': 'https://api.qrserver.com/test',
            'qr_string': '000201...',
            'fee': 365,
            'total_payment': 8170,
            'amount': 7805
        }

        ref_id = f"GT-TEST-GQ-{int(os.getpid())}"
        trx = Transaction(
            user_id=self.user.id,
            ref_id=ref_id,
            product_name="XL Xtra Edukasi 15 GB 7 Hari",
            sku_code="xledu15",
            target_number="081775700114",
            amount=7805.0,
            payment_method="QRIS",
            payment_status="UNPAID",
            status="UNPAID"
        )
        db.session.add(trx)
        db.session.commit()

        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)

        res = self.client.get(f'/trx/generate_qris/{ref_id}')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('status'), 'success')
        self.assertEqual(data.get('fee'), 365)
        self.assertEqual(data.get('total_payment'), 8170)
        print("  [OK] Endpoint /trx/generate_qris merespons JSON dengan fee dan total_payment yang valid!")

if __name__ == '__main__':
    unittest.main()
