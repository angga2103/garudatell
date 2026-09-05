"""
VIP-RESELLER INTEGRATION VERIFICATION SUITE
Menguji:
1. VIPReseller Class & Signature generation (md5(api_id + api_key))
2. VIP Profile, Prepaid, & Game Feature methods
3. Admin test_connection('vipreseller') with balance & whitelist diagnostics
4. Admin sync_vipreseller with error propagation & product insertion
5. Webhook callback /api/callback/vipreseller, /callback/vipreseller, /trx/callback/vipreseller
   (Success, Idempotency, and Failure with Auto-Refund)
"""

import os
import sys
import unittest
import json
import hashlib
from unittest.mock import patch, MagicMock

# Pastikan root direktori ada di sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app, db
from app.models.user import User
from app.models.admin import Admin
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.margin import MarginTier
from app.services.vip_reseller import VIPReseller, clean_str

class TestVIPResellerSuite(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

    def tearDown(self):
        self.app_context.pop()

    def test_01_signature_and_clean_str(self):
        """Menguji formula signature VIP-Reseller: md5(api_id + api_key) dan sanitasi clean_str."""
        self.assertEqual(clean_str("  'my_api_key'  "), "my_api_key")
        self.assertEqual(clean_str(' "12345" '), "12345")

        with patch.dict(os.environ, {'VIP_API_ID': 'VIP123', 'VIP_API_KEY': 'SECRET456'}):
            vip = VIPReseller()
            self.assertEqual(vip.api_id, 'VIP123')
            self.assertEqual(vip.api_key, 'SECRET456')
            expected_sign = hashlib.md5("VIP123SECRET456".encode()).hexdigest()
            self.assertEqual(vip._get_sign(), expected_sign)
        print("  [OK] Test 1: Signature & sanitasi clean_str valid 100%.")

    @patch('requests.post')
    def test_02_get_profile(self, mock_post):
        """Menguji pemanggilan method get_profile() ke endpoint profile resmi."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "result": True,
            "data": {
                "username": "vip_user",
                "name": "Garuda Telco Member",
                "balance": 250000
            },
            "message": "Data profil berhasil didapatkan"
        }
        mock_post.return_value = mock_resp

        with patch.dict(os.environ, {'VIP_API_ID': 'VIP123', 'VIP_API_KEY': 'SECRET456'}):
            vip = VIPReseller()
            res = vip.get_profile()
            self.assertTrue(res['result'])
            self.assertEqual(res['data']['balance'], 250000)
            self.assertEqual(mock_post.call_args[0][0], "https://vip-reseller.co.id/api/profile")
        print("  [OK] Test 2: VIP get_profile() memanggil endpoint resmi dan parsing saldo sukses.")

    @patch('requests.post')
    def test_03_admin_test_connection_vipreseller(self, mock_post):
        """Menguji route admin test_connection('vipreseller') dengan mock response sukses dan error whitelist."""
        # A. Skenario Sukses
        mock_resp_success = MagicMock()
        mock_resp_success.json.return_value = {
            "result": True,
            "data": {"username": "vip_boss", "name": "VIP Boss", "balance": 1750000}
        }
        mock_post.return_value = mock_resp_success

        with patch.dict(os.environ, {'VIP_API_ID': 'VIP123', 'VIP_API_KEY': 'SECRET456'}):
            res = self.client.get('/admin/test_connection/vipreseller', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn("Koneksi VIP-Reseller Sukses", res.get_data(as_text=True))
            self.assertIn("1,750,000", res.get_data(as_text=True))

        # B. Skenario Ditolak karena Whitelist IP
        mock_resp_whitelist = MagicMock()
        mock_resp_whitelist.json.return_value = {
            "result": False,
            "message": "IP Address Anda (203.194.115.182) tidak terdaftar di whitelist"
        }
        mock_post.return_value = mock_resp_whitelist

        with patch.dict(os.environ, {'VIP_API_ID': 'VIP123', 'VIP_API_KEY': 'SECRET456'}):
            res = self.client.get('/admin/test_connection/vipreseller', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn("VIP-Reseller Menolak", res.get_data(as_text=True))
            self.assertIn("Whitelist IP", res.get_data(as_text=True))
        print("  [OK] Test 3: Admin test_connection('vipreseller') sukses menampilkan saldo & deteksi whitelist IP.")

    @patch('app.services.vip_reseller.VIPReseller.get_game_services')
    @patch('app.services.vip_reseller.VIPReseller.get_services')
    def test_04_sync_vipreseller_diagnostics(self, mock_get_services, mock_get_games):
        """Menguji sync_vipreseller() menampilkan pesan diagnostik error asli jika server VIP menolak."""
        mock_get_services.return_value = {
            "result": False,
            "message": "IP Address Anda (203.194.115.182) tidak terdaftar di whitelist"
        }
        mock_get_games.return_value = {
            "result": False,
            "message": "API Key tidak valid"
        }

        with patch.dict(os.environ, {'VIP_API_ID': 'VIP123', 'VIP_API_KEY': 'SECRET456'}):
            res = self.client.post('/admin/sync_vipreseller', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            html = res.get_data(as_text=True)
            self.assertIn("Gagal menarik data dari VIP-Reseller", html)
            self.assertIn("Prepaid: IP Address Anda", html)
            self.assertIn("Games: API Key tidak valid", html)
            self.assertIn("Whitelist IP di Panel VIP-Reseller", html)
        print("  [OK] Test 4: sync_vipreseller() menampilkan detail diagnostik penolakan server secara transparan.")

    def test_05_webhook_vipreseller_lifecycle(self):
        """Menguji Webhook callback VIP-Reseller: Success, Idempotency, dan Failure dengan Auto-Refund."""
        # Siapkan test user dan test transaksi
        test_user = User.query.filter_by(phone='089999999999').first()
        if not test_user:
            test_user = User(name='Test VIP User', phone='089999999999', balance=50000.0, password_hash='dummy_hash')
            db.session.add(test_user)
            db.session.commit()
        else:
            test_user.balance = 50000.0
            db.session.commit()

        initial_balance = test_user.balance

        # 1. Buat Transaksi VIP-1
        ref_id_1 = "VIP-TEST-001"
        provider_ref_1 = "VIPTRX-8881"
        trx1 = Transaction.query.filter_by(ref_id=ref_id_1).first()
        if trx1:
            db.session.delete(trx1)
            db.session.commit()

        trx1 = Transaction(
            user_id=test_user.id,
            ref_id=ref_id_1,
            provider_ref=provider_ref_1,
            product_name="[VIP] Mobile Legends 86 Diamonds",
            sku_code="MLBB-86",
            target_number="12345678(1234)",
            amount=20000.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING'
        )
        db.session.add(trx1)
        db.session.commit()

        # A. Uji Webhook Sukses melalui alias /api/callback/vipreseller
        payload_success = {
            "trxid": provider_ref_1,
            "status": "success",
            "sn": "SN-VIP-MLBB-998877",
            "service": "MLBB-86",
            "data_no": "12345678(1234)"
        }
        res = self.client.post('/api/callback/vipreseller', json=payload_success)
        self.assertEqual(res.status_code, 200)
        json_res = res.get_json()
        self.assertTrue(json_res.get('result'))

        db.session.refresh(trx1)
        self.assertEqual(trx1.status, 'SUCCESS')
        self.assertEqual(trx1.sn, "SN-VIP-MLBB-998877")

        # B. Uji Idempotensi: Callback kedua pada status SUCCESS tidak boleh memicu efek ganda
        res_dup = self.client.post('/callback/vipreseller', json=payload_success)
        self.assertEqual(res_dup.status_code, 200)
        self.assertIn("sudah berstatus SUCCESS", res_dup.get_json().get('message'))

        # C. Buat Transaksi VIP-2 untuk pengujian Gagal & Auto-Refund
        ref_id_2 = "VIP-TEST-002"
        provider_ref_2 = "VIPTRX-8882"
        trx2 = Transaction.query.filter_by(ref_id=ref_id_2).first()
        if trx2:
            db.session.delete(trx2)
            db.session.commit()

        # Potong saldo user untuk simulasi transaksi
        test_user.balance -= 15000.0
        db.session.commit()
        bal_before_fail = test_user.balance

        trx2 = Transaction(
            user_id=test_user.id,
            ref_id=ref_id_2,
            provider_ref=provider_ref_2,
            product_name="[VIP] Genshin Impact Blessing",
            sku_code="GENSHIN-WELKIN",
            target_number="80012345",
            amount=15000.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING'
        )
        db.session.add(trx2)
        db.session.commit()

        # Kirim callback gagal melalui alias /trx/callback/vipreseller
        payload_fail = {
            "trxid": provider_ref_2,
            "status": "error",
            "note": "User ID tidak ditemukan",
            "service": "GENSHIN-WELKIN"
        }
        res_fail = self.client.post('/trx/callback/vipreseller', json=payload_fail)
        self.assertEqual(res_fail.status_code, 200)

        db.session.refresh(trx2)
        db.session.refresh(test_user)
        self.assertEqual(trx2.status, 'FAILED')
        self.assertEqual(trx2.sn, "User ID tidak ditemukan")
        # Pastikan saldo user telah dikembalikan (Auto-Refund)
        self.assertEqual(test_user.balance, bal_before_fail + 15000.0)

        # Cleanup data pengujian
        from app.models.point_log import PointLog
        PointLog.query.filter_by(user_id=test_user.id).delete()
        Transaction.query.filter_by(user_id=test_user.id).delete()
        User.query.filter_by(id=test_user.id).delete()
        db.session.commit()
        print("  [OK] Test 5: Webhook VIP-Reseller (Success, Idempotensi, & Auto-Refund) lulus 100% pada semua alias route.")

if __name__ == '__main__':
    print("======================================================================")
    print("      VIP-RESELLER INTEGRATION VERIFICATION TEST SUITE                ")
    print("======================================================================")
    suite = unittest.TestLoader().loadTestsFromTestCase(TestVIPResellerSuite)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    if not result.wasSuccessful():
        sys.exit(1)
