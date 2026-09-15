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
        """Memastikan pesan WhatsApp penambahan saldo admin ramah, rapi, dan mencakup saldo awal, nominal, saldo akhir."""
        msg_user_add = _build_adjustment_message_user(
            store_name="GarudaTel",
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
        self.assertIn("GarudaTel", msg_user_add)
        self.assertIn("DITAMBAHKAN", msg_user_add)
        self.assertIn("Rp 100.000", msg_user_add)   # Saldo awal
        self.assertIn("+Rp 50.000", msg_user_add)   # Nominal masuk
        self.assertIn("Rp 150.000", msg_user_add)  # Saldo sekarang
        self.assertIn("TRX-TEST-001", msg_user_add)
        self.assertIn("Bonus Promo Agen", msg_user_add)

        msg_upline_add = _build_adjustment_message_upline(
            store_name="GarudaTel",
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
        self.assertIn("Rp 100.000", msg_upline_add)
        self.assertIn("+Rp 50.000", msg_upline_add)
        self.assertIn("Rp 150.000", msg_upline_add)

    def test_build_deduction_messages_format(self):
        """Memastikan pesan WhatsApp pengurangan/sinkronisasi saldo admin ramah dan jelas."""
        msg_user_deduct = _build_adjustment_message_user(
            store_name="GarudaTel",
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
        self.assertIn("Rp 200.000", msg_user_deduct)  # Saldo awal
        self.assertIn("-Rp 50.000", msg_user_deduct)  # Nominal penyesuaian
        self.assertIn("Rp 150.000", msg_user_deduct)  # Saldo sekarang
        self.assertIn("Koreksi Transaksi Dobel", msg_user_deduct)

    def test_low_balance_alert_messages_format(self):
        """Memastikan format pesan peringatan saldo minim ramah & profesional."""
        msg_user_low = _build_low_balance_message_user("GarudaTel", "Toko Berkah", 45000)
        self.assertIn("PERINGATAN SISA SALDO MINIM", msg_user_low)
        self.assertIn("Rp 45.000", msg_user_low)
        self.assertIn("Rp 100.000", msg_user_low)
        self.assertIn("Deposit Saldo", msg_user_low)

        msg_upline_low = _build_low_balance_message_upline("GarudaTel", "Bos Agen", "Toko Berkah", "6282222222222", 45000)
        self.assertIn("Bos Agen", msg_upline_low)
        self.assertIn("Toko Berkah", msg_upline_low)
        self.assertIn("Rp 45.000", msg_upline_low)
        self.assertIn("bonus komisi kemitraan", msg_upline_low)

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

if __name__ == '__main__':
    unittest.main()
