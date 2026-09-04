#!/usr/bin/env python3
"""
================================================================================
TEST SUITE: TELEGRAM BOTS (BOT 2 & 3) + UNIVERSAL MANUAL OTP
================================================================================
Memverifikasi:
1. Pembuatan dan validasi Universal Manual OTP (bypass register/login/reset)
2. Normalisasi nomor handphone (08... vs 628...)
3. Snapshot & Gzip Database Backup untuk Bot 2 & Bot 3
4. Struktur Keyboard Inline & Respon Bot 3 Admin
5. Format Payload Notifikasi Transaksi Bot 2
================================================================================
"""

import sys
import os
import unittest
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.otp import OtpCode
from app.models.transaction import Transaction
from app.services.otp_service import create_otp, verify_otp, get_phone_variants
from app.services.telegram_service import (
    get_admin_inline_keyboard,
    get_back_button,
    perform_database_backup,
    send_trx_notification,
    async_send_trx_notification,
    send_backup_notification,
    handle_admin_callback,
    handle_admin_message
)

class TestTelegramAndOtp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_phone_variants_normalization(self):
        """Tes variasi format nomor HP 08 vs 628."""
        variants_08 = get_phone_variants('081234567890')
        self.assertIn('081234567890', variants_08)
        self.assertIn('6281234567890', variants_08)

        variants_62 = get_phone_variants('6281234567890')
        self.assertIn('081234567890', variants_62)
        self.assertIn('6281234567890', variants_62)

    def test_universal_manual_otp(self):
        """Tes OTP manual dapat memverifikasi registrasi atau reset password."""
        test_phone = '08999999999'
        
        # Bersihkan test OTP lama jika ada
        OtpCode.query.filter(OtpCode.phone.in_(get_phone_variants(test_phone))).delete()
        db.session.commit()

        # Buat OTP darurat manual oleh admin
        otp_code = create_otp(test_phone, action='manual', expiry_seconds=300)
        self.assertIsNotNone(otp_code)
        self.assertEqual(len(otp_code), 6)

        # 1. User registrasi mencoba memverifikasi dengan kode darurat ini
        ok, msg, udata = verify_otp(test_phone, otp_code, action='register')
        self.assertTrue(ok, f"OTP manual gagal memverifikasi registrasi: {msg}")

        # Buat lagi untuk uji variasi nomor 628...
        otp_code_2 = create_otp('08999999998', action='manual', expiry_seconds=300)
        # Verifikasi dengan format 628...
        ok2, msg2, udata2 = verify_otp('628999999998', otp_code_2, action='reset_password')
        self.assertTrue(ok2, f"OTP manual 628 varian gagal diverifikasi: {msg2}")

    def test_admin_inline_keyboard_structure(self):
        """Tes tombol inline keyboard admin terdefinisi dengan benar."""
        kb = get_admin_inline_keyboard()
        self.assertIn("inline_keyboard", kb)
        rows = kb["inline_keyboard"]
        self.assertGreaterEqual(len(rows), 5)

        # Cek tombol penting ada
        callback_datas = [btn["callback_data"] for row in rows for btn in row]
        self.assertIn("cmd_saldo", callback_datas)
        self.assertIn("cmd_stats", callback_datas)
        self.assertIn("cmd_pending", callback_datas)
        self.assertIn("cmd_tickets", callback_datas)
        self.assertIn("cmd_sync_digi", callback_datas)
        self.assertIn("cmd_sync_vip", callback_datas)
        self.assertIn("cmd_otp_info", callback_datas)
        self.assertIn("cmd_backup", callback_datas)
        self.assertIn("cmd_system", callback_datas)

    def test_database_backup_generation(self):
        """Tes pembuatan snapshot backup database SQLite dan gzip compression."""
        gz_file = perform_database_backup()
        self.assertTrue(os.path.exists(gz_file), "File backup gzip harus ada di storage/backups/")
        self.assertTrue(gz_file.endswith('.db.gz'))
        self.assertGreater(os.path.getsize(gz_file), 100, "Ukuran file backup harus valid")
        print(f"\n[OK] Database snapshot backup created at: {gz_file} ({os.path.getsize(gz_file)/1024:.2f} KB)")

    @patch('requests.post')
    def test_send_trx_notification_bot2(self, mock_post):
        """Tes format pesan pengiriman notifikasi transaksi ke Bot 2."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_post.return_value = mock_response

        # Buat dummy proxy trx
        class DummyTrx:
            ref_id = "GT-TEST-123456"
            product_name = "Telkomsel 50K"
            target_number = "081234567890"
            amount = 51200
            payment_method = "SALDO"
            payment_status = "PAID"
            status = "SUCCESS"
            user_id = 1
            sn = "081234567890/SN998877"

        # Simulasikan setting environment
        with patch.dict(os.environ, {'BOT_NOTIF_TOKEN': '123456:FAKE_TOKEN', 'BOT_NOTIF_CHAT_ID': '-100998877'}):
            ok, res = send_trx_notification(DummyTrx(), title="TRANSAKSI BERHASIL")
            self.assertTrue(ok)
            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs.get('json', {})
            self.assertIn("TRANSAKSI BERHASIL", payload.get('text', ''))
            self.assertIn("GT-TEST-123456", payload.get('text', ''))
            self.assertIn("Telkomsel 50K", payload.get('text', ''))

    @patch('requests.post')
    def test_admin_bot_command_otp(self, mock_post):
        """Tes perintah /otp <nomor> pada Bot 3 Admin."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {'BOT_ADMIN_TOKEN': '123456:FAKE_ADMIN_TOKEN', 'BOT_ADMIN_CHAT_ID': '12345678'}):
            msg = {
                'chat': {'id': '12345678'},
                'text': '/otp 081298765432'
            }
            handle_admin_message(self.app, msg)
            mock_post.assert_called()
            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs.get('json', {})
            self.assertIn("OTP DARURAT BERHASIL DICIPTAKAN", payload.get('text', ''))
            self.assertIn("081298765432", payload.get('text', ''))

if __name__ == '__main__':
    unittest.main()
