import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Ensure root dir is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.services.balance_service import adjust_user_balance_manual
from app.services.balance_notification_service import (
    _build_adjustment_message_user,
    _build_adjustment_message_upline,
    _build_low_balance_message_user,
    _build_low_balance_message_upline,
    check_and_notify_low_balance,
    scan_and_notify_all_low_balance_users,
    LOW_BALANCE_THRESHOLD,
    format_rupiah
)

class TestWABalanceNotifications(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Buat Upline User
        self.upline = User(
            name="Bos Agen Upline",
            phone="6281111111111",
            role="vip",
            balance=500000.0
        )
        self.upline.set_password("password123")
        db.session.add(self.upline)
        db.session.commit()

        # Buat Downline User
        self.user = User(
            name="Toko Berkah Mitra",
            phone="6282222222222",
            role="user",
            balance=150000.0,
            upline_id=self.upline.id
        )
        self.user.set_password("password123")
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_build_adjustment_messages_format(self):
        """Memastikan pesan WhatsApp penambahan saldo admin ramah, rapi, dan mencakup saldo awal, nominal, saldo akhir dengan nama profil toko dinamis."""
        msg_user_add = _build_adjustment_message_user(
            store_name="iPay",
            user_name="Toko Berkah",
            old_balance=100000,
            amount=50000,
            new_balance=150000,
            action='add',
            note='Bonus Promo Agen',
            admin_source='Web Admin',
            ref_id='TRX-TEST-001',
            wib_str='15/09/2026 18:00'
        )
        self.assertIn("Toko Berkah", msg_user_add)
        self.assertIn("iPay", msg_user_add)
        self.assertNotIn("GarudaTel", msg_user_add)
        self.assertIn("DITAMBAHKAN", msg_user_add)
        self.assertIn("Rp 100.000", msg_user_add)   # Saldo awal
        self.assertIn("+Rp 50.000", msg_user_add)   # Nominal masuk
        self.assertIn("Rp 150.000", msg_user_add)  # Saldo sekarang
        self.assertIn("TRX-TEST-001", msg_user_add)
        self.assertIn("Bonus Promo Agen", msg_user_add)

        msg_upline_add = _build_adjustment_message_upline(
            store_name="iPay",
            upline_name="Bos Agen Upline",
            user_name="Toko Berkah",
            user_phone="6282222222222",
            old_balance=100000,
            amount=50000,
            new_balance=150000,
            action='add',
            ref_id='TRX-TEST-001',
            wib_str='15/09/2026 18:00'
        )
        self.assertIn("Bos Agen Upline", msg_upline_add)
        self.assertIn("Toko Berkah", msg_upline_add)
        self.assertIn("6282222222222", msg_upline_add)
        self.assertIn("iPay", msg_upline_add)
        self.assertNotIn("GarudaTel", msg_upline_add)
        self.assertIn("Rp 100.000", msg_upline_add)
        self.assertIn("+Rp 50.000", msg_upline_add)
        self.assertIn("Rp 150.000", msg_upline_add)

    def test_build_deduction_messages_format(self):
        """Memastikan pesan WhatsApp pengurangan/sinkronisasi saldo admin ramah dan jelas."""
        msg_user_deduct = _build_adjustment_message_user(
            store_name="iPay",
            user_name="Toko Berkah",
            old_balance=200000,
            amount=50000,
            new_balance=150000,
            action='deduct',
            note='Koreksi Transaksi Dobel',
            admin_source='Web Admin',
            ref_id='TRX-TEST-002',
            wib_str='15/09/2026 18:00'
        )
        self.assertIn("PENYESUAIAN SALDO", msg_user_deduct)
        self.assertIn("iPay", msg_user_deduct)
        self.assertNotIn("GarudaTel", msg_user_deduct)
        self.assertIn("Rp 200.000", msg_user_deduct)  # Saldo awal
        self.assertIn("-Rp 50.000", msg_user_deduct)  # Nominal penyesuaian
        self.assertIn("Rp 150.000", msg_user_deduct)  # Saldo sekarang
        self.assertIn("Koreksi Transaksi Dobel", msg_user_deduct)

    def test_low_balance_alert_messages_format(self):
        """Memastikan format pesan peringatan saldo minim ramah & profesional tanpa Pengingat ramah GarudaTel dan tanpa Cara Top Up Praktis."""
        msg_user_low = _build_low_balance_message_user("iPay", "Toko Berkah", 45000)
        self.assertIn("PERINGATAN SISA SALDO MINIM", msg_user_low)
        self.assertIn("Rp 45.000", msg_user_low)
        self.assertIn("Rp 100.000", msg_user_low)
        # Memastikan teks yang diminta dihapus benar-benar tidak ada
        self.assertNotIn("Pengingat ramah", msg_user_low)
        self.assertNotIn("Cara Top Up Praktis", msg_user_low)
        self.assertNotIn("Deposit Saldo", msg_user_low)
        self.assertNotIn("GarudaTel", msg_user_low)

        msg_upline_low = _build_low_balance_message_upline("iPay", "Bos Agen", "Toko Berkah", "6282222222222", 45000)
        self.assertIn("Bos Agen", msg_upline_low)
        self.assertIn("Toko Berkah", msg_upline_low)
        self.assertIn("Rp 45.000", msg_upline_low)
        self.assertIn("bonus komisi kemitraan", msg_upline_low)
        self.assertNotIn("Pengingat ramah", msg_upline_low)
        self.assertNotIn("GarudaTel", msg_upline_low)

    @patch('app.services.balance_notification_service.kirim_wa')
    def test_low_balance_trigger_and_cooldown(self, mock_kirim_wa):
        """Menguji transisi saldo ke < 100k, mekanisme cooldown 12 jam, dan reset otomatis saat >= 100k."""
        mock_kirim_wa.return_value = True

        # 1. Saldo turun dari 150k ke 80k (First dip) -> Harus kirim alert
        triggered = check_and_notify_low_balance(self.user.id, old_balance=150000, new_balance=80000)
        self.assertTrue(triggered)

        # Cek database kolom last_low_balance_notified_at terisi
        user_db = User.query.get(self.user.id)
        self.assertIsNotNone(user_db.last_low_balance_notified_at)
        initial_notified_at = user_db.last_low_balance_notified_at

        # 2. Transaksi berikutnya saldo turun lagi dari 80k ke 60k dalam waktu dekat (< 12 jam) -> TIDAK boleh spam
        triggered_again = check_and_notify_low_balance(self.user.id, old_balance=80000, new_balance=60000)
        self.assertFalse(triggered_again)
        self.assertEqual(user_db.last_low_balance_notified_at, initial_notified_at)

        # 3. User melakukan Topup sehingga saldo kembali >= 100k (misal 160k) -> Harus RESET flag
        check_and_notify_low_balance(self.user.id, old_balance=60000, new_balance=160000)
        user_db = User.query.get(self.user.id)
        self.assertIsNone(user_db.last_low_balance_notified_at)

        # 4. Saldo turun lagi nanti dari 160k ke 90k -> Langsung terpicu lagi karena sudah direset!
        triggered_after_reset = check_and_notify_low_balance(self.user.id, old_balance=160000, new_balance=90000)
        self.assertTrue(triggered_after_reset)
        user_db = User.query.get(self.user.id)
        self.assertIsNotNone(user_db.last_low_balance_notified_at)

    @patch('app.services.balance_notification_service.kirim_wa')
    def test_adjust_user_balance_manual_triggers_notifications(self, mock_kirim_wa):
        """Menguji bahwa adjust_user_balance_manual memanggil worker WA dengan nomor user dan upline."""
        mock_kirim_wa.return_value = True

        # Tambah Saldo Rp 50.000 via adjust_user_balance_manual
        ok, new_bal, msg, trx = adjust_user_balance_manual(
            user_id=self.user.id,
            amount=50000,
            action='add',
            note='Top Up Resmi Admin',
            admin_source='Web Admin'
        )
        self.assertTrue(ok)
        self.assertEqual(new_bal, 200000.0)

        # Tunggu sejenak agar background thread selesai
        import time
        time.sleep(0.5)

        # Verifikasi bahwa kirim_wa dipanggil untuk user dan upline
        calls = mock_kirim_wa.call_args_list
        called_numbers = [call[0][0] for call in calls]
        self.assertIn(self.user.phone, called_numbers)
        self.assertIn(self.upline.phone, called_numbers)

    @patch('app.services.balance_notification_service.kirim_wa')
    def test_scan_and_notify_all_low_balance_users(self, mock_kirim_wa):
        """Menguji pemindaian proaktif seluruh akun toko dengan saldo < Rp 100.000 dan cooldown."""
        mock_kirim_wa.return_value = True

        # Set user balance < 100k
        self.user.balance = 45000.0
        self.user.last_low_balance_notified_at = None
        db.session.commit()

        # 1. Pemindaian pertama (normal) -> Harus terkirim ke user dan upline
        res1 = scan_and_notify_all_low_balance_users(force_all=False)
        self.assertEqual(res1['total_low'], 1)
        self.assertEqual(res1['notified_users'], 1)
        self.assertEqual(res1['notified_uplines'], 1)
        self.assertEqual(len(res1['details']), 1)
        self.assertEqual(res1['details'][0]['user_id'], self.user.id)

        # 2. Pemindaian kedua langsung sesudahnya (cooldown 12 jam masih aktif) -> Tidak dikirim lagi
        res2 = scan_and_notify_all_low_balance_users(force_all=False)
        self.assertEqual(res2['total_low'], 1)
        self.assertEqual(res2['notified_users'], 0)
        self.assertEqual(res2['notified_uplines'], 0)

        # 3. Pemindaian paksa (force_all=True) -> Melewati cooldown dan langsung terkirim
        res3 = scan_and_notify_all_low_balance_users(force_all=True)
        self.assertEqual(res3['total_low'], 1)
        self.assertEqual(res3['notified_users'], 1)
        self.assertEqual(res3['notified_uplines'], 1)

    @patch('app.services.telegram_service.send_sync_report_to_admin_bot')
    @patch('app.services.digiflazz.get_price_list')
    def test_digiflazz_sync_reports_to_telegram_bot3(self, mock_get_price_list, mock_send_report):
        """Memastikan sync_products memanggil send_sync_report_to_admin_bot dengan format total produk."""
        from app.services.digiflazz import sync_products
        from app.models.product import Product

        mock_send_report.return_value = (True, "OK")
        mock_get_price_list.return_value = (True, [
            {
                'buyer_sku_code': 'TESTSKU01',
                'product_name': 'Paket Data Test 1GB',
                'category': 'Data',
                'brand': 'TELKOMSEL',
                'price': 10000,
                'buyer_product_status': True,
                'seller_product_status': False  # Ini terdeteksi gangguan
            }
        ], "OK")

        # Jalankan sync_products
        ok, msg = sync_products(force=True, notify_admin_bot=True)
        self.assertTrue(ok)
        self.assertIn("Sukses!", msg)
        self.assertIn("total produk", msg)
        self.assertIn("terdeteksi gangguan", msg)

        # Pastikan send_sync_report_to_admin_bot dipanggil
        self.assertTrue(mock_send_report.called)
        sent_msg = mock_send_report.call_args[0][0]
        self.assertIn("total produk", sent_msg)
        self.assertIn("terdeteksi gangguan", sent_msg)

    @patch('app.services.balance_notification_service.kirim_wa')
    def test_cron_and_web_routes_for_scan_low_balance(self, mock_kirim_wa):
        """Menguji endpoint cron /api/cron/check-low-balance dan route web admin /admin/users/scan_low_balance."""
        mock_kirim_wa.return_value = True
        client = self.app.test_client()

        # 1. Cron check low balance tanpa key -> 403
        resp_unauth = client.get('/api/cron/check-low-balance')
        self.assertEqual(resp_unauth.status_code, 403)

        # 2. Cron check low balance dengan key valid -> 200
        cron_secret = os.getenv('CRON_SECRET_KEY', 'ipay-cron-secret-2026').strip()
        resp_auth = client.get(f'/api/cron/check-low-balance?key={cron_secret}&force=1')
        self.assertEqual(resp_auth.status_code, 200)
        data = resp_auth.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('total_low', data['data'])

        # 3. Web Admin scan low balance (dengan session login admin)
        with client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        resp_admin = client.post('/admin/users/scan_low_balance', data={'force': '1'}, follow_redirects=True)
        self.assertEqual(resp_admin.status_code, 200)

if __name__ == '__main__':
    unittest.main()
