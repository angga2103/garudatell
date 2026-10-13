import os
import sys
import unittest
import socket
from unittest.mock import patch, MagicMock

# Ensure root dir is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.services.telegram_service import (
    get_telegram_api_url,
    get_telegram_session,
    call_telegram_api,
    is_admin_chat_authorized,
    get_admin_inline_keyboard,
    _send_message,
    _edit_message,
    _answer_callback
)
import urllib3.util.connection as urllib3_conn

class TestTelegramResilienceAndBotAdmin(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'TESTING': True,
            'WTF_CSRF_ENABLED': False
        })
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.client = self.app.test_client()
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_ipv4_forcing(self):
        """Pastikan urllib3 dipaksa menggunakan IPv4 (socket.AF_INET) guna mencegah blackhole IPv6 di VPS."""
        self.assertIsNotNone(urllib3_conn.allowed_gai_family)
        self.assertEqual(urllib3_conn.allowed_gai_family(), socket.AF_INET)
        print("\n[OK 1/5] urllib3 dipaksa ke AF_INET (IPv4 Only) untuk mencegah timeout IPv6 VPS.")

    def test_custom_api_base_url_and_proxy(self):
        """Pastikan custom Telegram API base URL (Cloudflare Worker / Reverse Proxy) dan Proxy didukung."""
        # Default
        with patch.dict(os.environ, {}, clear=False):
            if 'TELEGRAM_API_BASE_URL' in os.environ:
                del os.environ['TELEGRAM_API_BASE_URL']
            if 'TELEGRAM_API_URL' in os.environ:
                del os.environ['TELEGRAM_API_URL']
            self.assertEqual(get_telegram_api_url(), "https://api.telegram.org")

        # Custom URL
        with patch.dict(os.environ, {'TELEGRAM_API_BASE_URL': 'https://tg-proxy.ipay.my.id/'}):
            self.assertEqual(get_telegram_api_url(), "https://tg-proxy.ipay.my.id")

        # Session Proxy
        with patch.dict(os.environ, {'TELEGRAM_PROXY': 'http://127.0.0.1:8080'}):
            sess = get_telegram_session()
            self.assertEqual(sess.proxies.get('https'), 'http://127.0.0.1:8080')
            self.assertEqual(sess.proxies.get('http'), 'http://127.0.0.1:8080')

        print("[OK 2/5] Dukungan Custom Telegram Base URL & Proxy terverifikasi 100%.")

    def test_admin_chat_authorization_multi_id(self):
        """Pastikan validasi otorisasi chat ID mendukung ID tunggal maupun majemuk (koma-separated)."""
        # Single
        self.assertTrue(is_admin_chat_authorized('7236113204', '7236113204'))
        self.assertFalse(is_admin_chat_authorized('9999999999', '7236113204'))

        # Multi-ID
        allowed_multi = "7236113204, 1122334455, 6677889900"
        self.assertTrue(is_admin_chat_authorized('7236113204', allowed_multi))
        self.assertTrue(is_admin_chat_authorized('1122334455', allowed_multi))
        self.assertTrue(is_admin_chat_authorized('6677889900', allowed_multi))
        self.assertFalse(is_admin_chat_authorized('12345', allowed_multi))

        print("[OK 3/5] Otorisasi Multi-Admin Chat ID terverifikasi 100%.")

    @patch('requests.post')
    def test_call_telegram_api_integration(self, mock_post):
        """Uji eksekusi call_telegram_api dan penanganan timeout/error."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'ok': True, 'result': {'message_id': 123}}
        mock_post.return_value = mock_response

        # 1. Jalur normal: kirim pesan memanggil requests.post secara langsung
        _send_message('TEST_TOKEN', '7236113204', 'Halo Admin', reply_markup=get_admin_inline_keyboard())
        mock_post.assert_called()
        args, kwargs = mock_post.call_args
        self.assertIn("https://api.telegram.org/botTEST_TOKEN/sendMessage", args[0])
        self.assertEqual(kwargs['json']['chat_id'], '7236113204')
        self.assertIn('reply_markup', kwargs['json'])

        # 2. Jalur proxy: jika TELEGRAM_PROXY disetel, get_telegram_session dipanggil
        with patch.dict(os.environ, {'TELEGRAM_PROXY': 'http://127.0.0.1:8080'}):
            with patch('app.services.telegram_service.get_telegram_session') as mock_sess_func:
                mock_sess = MagicMock()
                mock_sess.request.return_value = mock_response
                mock_sess_func.return_value = mock_sess

                call_telegram_api('post', 'botTEST_TOKEN/sendMessage', json={'chat_id': '123'})
                mock_sess.request.assert_called()

        print("[OK 4/5] Integrasi call_telegram_api (_send_message, proxy session) berjalan normal.")

    @patch('app.services.telegram_service.call_telegram_api')
    def test_admin_dashboard_test_connection_route(self, mock_call):
        """Uji endpoint test_connection di admin.py dengan mocked Telegram API."""
        # 1. Sukses kirim
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'ok': True}
        mock_call.return_value = mock_resp

        with patch.dict(os.environ, {'BOT_ADMIN_TOKEN': '123:ABC', 'BOT_ADMIN_CHAT_ID': '7236113204'}):
            res = self.client.get('/admin/test_connection/bot_admin', follow_redirects=True)
            self.assertEqual(res.status_code, 200)
            self.assertIn("Tes koneksi sukses", res.text)

        # 2. Timeout error dengan hint penjelasan ramah & petunjuk solutif
        import requests
        mock_call.side_effect = requests.exceptions.ConnectTimeout("Connection to api.telegram.org timed out. (connect timeout=10)")

        with patch.dict(os.environ, {'BOT_ADMIN_TOKEN': '123:ABC', 'BOT_ADMIN_CHAT_ID': '7236113204'}):
            res_timeout = self.client.get('/admin/test_connection/bot_admin', follow_redirects=True)
            self.assertEqual(res_timeout.status_code, 200)
            self.assertIn("Error Telegram", res_timeout.text)
            self.assertIn("Penyebab: VPS mengalami kendala koneksi ke Telegram API", res_timeout.text)
            self.assertIn("garudatell", res_timeout.text)

        print("[OK 5/5] Endpoint /admin/test_connection/bot_admin lulus uji sukses & mitigasi timeout.")

if __name__ == '__main__':
    unittest.main()
