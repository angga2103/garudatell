#!/usr/bin/env python3
"""
================================================================================
TEST SUITE: EMERGENCY OTP FLOW (10-MINUTE EXPIRY) & TELEGRAM CS NOTIFICATION
================================================================================
Memverifikasi:
1. send_emergency_otp_request() di app/services/telegram_service.py:
   - Format pesan alert CS Telegram
   - Pembuatan direct wa.me link dengan teks OTP & masa berlaku 10 menit
2. /api/auth_ajax (action: 'request_emergency_otp') untuk user login/register
   - Pembuatan record OtpCode dengan masa berlaku 10 menit (600s)
   - Respon link WhatsApp CS dan konfirmasi
3. /admin/generate_otp_manual oleh Admin
   - Respon JSON dengan otp, expiry_minutes: 10, wa_link, dan telegram_sent
4. /admin/wa_restart dan /admin/wa_status
================================================================================
"""

import sys
import os
import time
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.otp import OtpCode
from app.services.otp_service import verify_otp, get_phone_variants
from app.services.telegram_service import send_emergency_otp_request


class TestEmergencyOtpFlow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

    def tearDown(self):
        self.ctx.pop()

    @patch('requests.post')
    def test_send_emergency_otp_request_format(self, mock_post):
        """Memastikan fungsi Telegram CS menghasilkan pesan 10 menit dan wa.me link yang valid."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'ok': True}
        mock_post.return_value = mock_response

        with patch.dict(os.environ, {'BOT_CS_TOKEN': '123456:FAKE_CS_TOKEN', 'BOT_CS_CHAT_ID': '987654321'}):
            ok, msg, wa_link = send_emergency_otp_request(
                phone='081234567890',
                otp_code='789456',
                user_name='Budi Darurat',
                action_type='Login / Masuk',
                expiry_minutes=10
            )

            self.assertTrue(ok)
            self.assertIn('https://wa.me/6281234567890', wa_link)
            self.assertIn('789456', wa_link)
            # Pesan harus menyebutkan 10 menit
            self.assertTrue('10' in wa_link)

            mock_post.assert_called_once()
            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs.get('json', {})
            text = payload.get('text', '')

            self.assertIn("PERMINTAAN BANTUAN OTP DARURAT", text)
            self.assertIn("6281234567890", text)
            self.assertIn("789456", text)
            self.assertIn("10 Menit", text)
            self.assertIn("Budi Darurat", text)

    @patch('requests.post')
    def test_auth_ajax_request_emergency_otp(self, mock_post):
        """Tes endpoint AJAX user /api/auth_ajax untuk meminta Bantuan OTP Darurat."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'ok': True}
        mock_post.return_value = mock_response

        test_phone = '081288887777'
        # Hapus OTP sebelumnya
        OtpCode.query.filter(OtpCode.phone.in_(get_phone_variants(test_phone))).delete()
        db.session.commit()

        with patch.dict(os.environ, {'BOT_CS_TOKEN': '123456:FAKE_CS_TOKEN', 'BOT_CS_CHAT_ID': '987654321', 'ADMIN_PHONE': '62811111111'}):
            res = self.client.post('/api/auth_ajax', json={
                'action': 'request_emergency_otp',
                'phone': test_phone,
                'name': 'Andi Member'
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get('status'), 'success')
            self.assertIn('10 menit', data.get('message').lower())
            self.assertTrue(data.get('cs_wa_url').startswith('https://wa.me/'))

            # Verifikasi OTP tersimpan di DB dengan masa berlaku sekitar 10 menit
            otp_record = OtpCode.query.filter(
                OtpCode.phone.in_(get_phone_variants(test_phone)),
                OtpCode.action == 'manual'
            ).order_by(OtpCode.created_at.desc()).first()

            self.assertIsNotNone(otp_record)
            now_ts = time.time()
            delta = otp_record.expires_at - now_ts
            # Harus sekitar 600 detik (antara 500 dan 620)
            self.assertGreater(delta, 500)
            self.assertLessEqual(delta, 620)

            # Kode OTP manual ini harus bisa diverifikasi untuk login atau register
            ok, v_msg, _ = verify_otp(test_phone, otp_record.otp_code, action='login')
            self.assertTrue(ok, f"OTP darurat harus valid: {v_msg}")

    @patch('requests.post')
    def test_admin_generate_otp_manual_endpoint(self, mock_post):
        """Tes endpoint /admin/generate_otp_manual oleh Admin."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'ok': True}
        mock_post.return_value = mock_response

        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        test_phone = '081299990000'
        with patch.dict(os.environ, {'BOT_CS_TOKEN': '123456:FAKE_CS_TOKEN', 'BOT_CS_CHAT_ID': '987654321'}):
            res = self.client.post('/admin/generate_otp_manual', json={
                'number': test_phone,
                'name': 'Admin User Test'
            })
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get('status'), 'success')
            self.assertEqual(data.get('expiry_minutes'), 10)
            self.assertEqual(data.get('phone'), '6281299990000')
            self.assertIn('https://wa.me/6281299990000', data.get('wa_link'))
            self.assertTrue(data.get('telegram_sent'))

    def test_admin_wa_status_and_restart(self):
        """Tes endpoint /admin/wa_status dan /admin/wa_restart."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        # Test status
        with patch('requests.get') as mock_get:
            mock_res = MagicMock()
            mock_res.json.return_value = {'connected': True}
            mock_res.status_code = 200
            mock_get.return_value = mock_res

            res = self.client.get('/admin/wa_status')
            self.assertEqual(res.status_code, 200)
            self.assertTrue(res.get_json().get('connected'))

        # Test restart when ensure function returns True
        with patch('app.routes.admin._ensure_wa_bot_running', return_value=(True, "Mesin Node.js berhasil dihidupkan!")):
            res = self.client.post('/admin/wa_restart')
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertEqual(data.get('status'), 'success')


if __name__ == '__main__':
    unittest.main()
