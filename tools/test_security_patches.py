#!/usr/bin/env python3
"""
================================================================================
TEST SUITE: SECURITY PATCHES VERIFICATION (GARUDATEL V2 PRODUCTION READINESS)
================================================================================
Memverifikasi:
1. SEC-VULN-01: Reset Password Step 3 ditolak jika tanpa reset_token yang valid (HTTP 403).
2. SEC-VULN-01: Reset Password berhasil jika melalui alur sah (Step 2 -> token -> Step 3).
3. SEC-VULN-05: Webhook Digiflazz menolak User-Agent spoofing tanpa signature valid (HTTP 403).
4. SEC-VULN-06: Cron endpoint menolak fallback secret lama 'ipay-cron-secret-2026' (HTTP 403/500).
5. SEC-VULN-12: HTTP Security Headers terpasang secara global di setiap respons.
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
from app.services.otp_service import create_otp


class TestSecurityPatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False

    def setUp(self):
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.client = self.app.test_client()

        # Buat user uji untuk pengujian reset password
        self.test_phone = '089911223344'
        self.test_user = User.query.filter_by(phone=self.test_phone).first()
        if not self.test_user:
            self.test_user = User(
                name='User Security Test',
                phone=self.test_phone,
                role='Member',
                balance=50000.0
            )
            db.session.add(self.test_user)
        self.test_user.set_password('PasswordAwal123!')
        db.session.commit()

    def tearDown(self):
        # Bersihkan data uji
        OtpCode.query.filter_by(phone=self.test_phone).delete()
        db.session.commit()
        self.ctx.pop()

    def test_01_direct_step3_without_token_is_blocked(self):
        """SEC-VULN-01: Memastikan penyerang tidak bisa langsung ganti password tanpa token verifikasi."""
        resp = self.client.post('/profil', data={
            'action': 'forgot_password_step3',
            'phone': self.test_phone,
            'new_password': 'HackedPassword123!'
        })
        self.assertEqual(resp.status_code, 403)
        data = resp.get_json()
        self.assertEqual(data.get('status'), 'error')
        self.assertIn('tidak valid atau kedaluwarsa', data.get('message', ''))

        # Pastikan password asli tidak berubah
        self.test_user = User.query.filter_by(phone=self.test_phone).first()
        self.assertTrue(self.test_user.check_password('PasswordAwal123!'))
        self.assertFalse(self.test_user.check_password('HackedPassword123!'))

    def test_02_legitimate_reset_flow_with_token_succeeds(self):
        """SEC-VULN-01: Alur sah verifikasi OTP Step 2 menghasilkan token dan Step 3 berhasil memvalidasi."""
        # 1. Simulasikan pembuatan OTP di Step 1
        otp_code = create_otp(self.test_phone, action='reset_password', username=self.test_user.name)
        self.assertTrue(bool(otp_code))

        # 2. Step 2 verifikasi OTP dengan test client session
        with self.client as c:
            resp_step2 = c.post('/profil', data={
                'action': 'forgot_password_step2',
                'phone': self.test_phone,
                'otp': otp_code
            })
            self.assertEqual(resp_step2.status_code, 200)
            data2 = resp_step2.get_json()
            self.assertEqual(data2.get('status'), 'success')
            reset_token = data2.get('reset_token')
            self.assertTrue(bool(reset_token))

            # 3. Step 3 dengan reset_token yang valid
            resp_step3 = c.post('/profil', data={
                'action': 'forgot_password_step3',
                'phone': self.test_phone,
                'new_password': 'PasswordBaruAman456!',
                'reset_token': reset_token
            })
            self.assertEqual(resp_step3.status_code, 200)
            data3 = resp_step3.get_json()
            self.assertEqual(data3.get('status'), 'success')

        # Pastikan password berhasil diperbarui
        self.test_user = User.query.filter_by(phone=self.test_phone).first()
        self.assertTrue(self.test_user.check_password('PasswordBaruAman456!'))

    def test_03_cron_endpoint_rejects_fallback_secret(self):
        """SEC-VULN-06: Endpoint cron tidak lagi menerima secret default statis 'ipay-cron-secret-2026'."""
        with patch.dict(os.environ, {}, clear=True):
            resp = self.client.post('/api/cron/sync-products?key=ipay-cron-secret-2026')
            # Jika CRON_SECRET_KEY tidak diset di env, harus ditolak 500 (not configured) atau 403 (unauthorized)
            self.assertIn(resp.status_code, [403, 500])

    def test_04_digiflazz_webhook_rejects_ua_spoofing(self):
        """SEC-VULN-05: Webhook Digiflazz menolak callback dengan User-Agent spoofing jika signature tidak valid."""
        headers = {
            'User-Agent': 'Digiflazz-Hookshot/1.0',
            'Content-Type': 'application/json'
        }
        payload = {
            'data': {
                'ref_id': 'NONEXISTENT_REF_99999',
                'status': 'Gagal',
                'customer_no': '08123456789'
            }
        }
        resp = self.client.post('/api/callback/digiflazz', json=payload, headers=headers)
        # Harus ditolak dengan status 403
        self.assertEqual(resp.status_code, 403)

    def test_05_security_headers_present(self):
        """SEC-VULN-12: Memverifikasi header keamanan dasar (OWASP) terpasang di setiap respons HTTP."""
        resp = self.client.get('/health')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'SAMEORIGIN')
        self.assertEqual(resp.headers.get('X-XSS-Protection'), '1; mode=block')
        self.assertEqual(resp.headers.get('Referrer-Policy'), 'strict-origin-when-cross-origin')


if __name__ == '__main__':
    unittest.main()
