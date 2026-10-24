import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.services.setting_service import is_maintenance_mode, set_maintenance_mode, get_maintenance_info

class MaintenanceModeTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        # Reset maintenance mode to OFF after test
        set_maintenance_mode(False)
        self.ctx.pop()

    def test_maintenance_mode_lifecycle(self):
        # 1. Pastikan maintenance mode mula-mula NONAKTIF
        set_maintenance_mode(False)
        self.assertFalse(is_maintenance_mode())

        # Akses root web publik saat nonaktif -> harus 200 OK
        res = self.client.get('/')
        self.assertEqual(res.status_code, 200)

        # 2. Aktifkan Maintenance Mode
        set_maintenance_mode(
            True,
            title='Upgrade Server GarudaTel',
            message='Peningkatan performa database sedang berlangsung.',
            estimated_end='20 Menit'
        )
        self.assertTrue(is_maintenance_mode())
        info = get_maintenance_info()
        self.assertEqual(info['title'], 'Upgrade Server GarudaTel')
        self.assertEqual(info['estimated_end'], '20 Menit')

        # 3. Akses sebagai pengunjung publik (belum login admin)
        res_maint = self.client.get('/')
        self.assertEqual(res_maint.status_code, 503)
        self.assertIn(b'Upgrade Server GarudaTel', res_maint.data)
        self.assertIn(b'Peningkatan performa database', res_maint.data)
        self.assertIn(b'20 Menit', res_maint.data)
        self.assertEqual(res_maint.headers.get('Retry-After'), '300')

        # 4. Request API / JSON saat maintenance -> harus dapat JSON 503
        res_json = self.client.get('/kategori/tv', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(res_json.status_code, 503)
        data = res_json.get_json()
        self.assertEqual(data.get('status'), 'maintenance')
        self.assertEqual(data.get('error'), 'maintenance_mode')

        # 5. Rute Admin login dan admin dashboard TIDAK boleh terblokir
        res_admin_login = self.client.get('/admin/login')
        self.assertEqual(res_admin_login.status_code, 200)

        # 6. Admin yang sedang login dapat mengakses web publik secara normal
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_username'] = 'AdminSuper'

        res_admin_browse = self.client.get('/')
        self.assertEqual(res_admin_browse.status_code, 200)

        # 7. Admin preview dengan ?preview_maintenance=1
        res_preview = self.client.get('/?preview_maintenance=1')
        self.assertEqual(res_preview.status_code, 200)
        self.assertIn(b'Mode Admin: Anda sedang melihat pratinjau', res_preview.data)

        # 8. Akses langsung rute /maintenance
        res_direct = self.client.get('/maintenance')
        self.assertEqual(res_direct.status_code, 200)
        self.assertIn(b'Upgrade Server GarudaTel', res_direct.data)

        # 9. Uji toggle maintenance action via Admin
        toggle_res = self.client.post('/admin/maintenance/toggle', data={'action': 'disable'})
        self.assertEqual(toggle_res.status_code, 302)
        self.assertFalse(is_maintenance_mode())

        # Akses kembali setelah dimatikan -> harus 200 OK
        with self.client.session_transaction() as sess:
            sess.clear() # logout admin untuk simulasi user biasa
        res_after = self.client.get('/')
        self.assertEqual(res_after.status_code, 200)

if __name__ == '__main__':
    unittest.main()
