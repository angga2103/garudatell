import os
import sys
import unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from datetime import datetime, timedelta
from app import create_app, db
from app.models import Admin, User, Product, Transaction, CommissionLog, PointLog
from app.services.setting_service import get_report_financial_settings, save_report_financial_settings


class AdminReportsFinancialTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.client = cls.app.test_client()

    def setUp(self):
        self.app_context = self.app.app_context()
        self.app_context.push()

    def tearDown(self):
        self.app_context.pop()

    def test_01_financial_settings_service(self):
        """Uji fungsi get_report_financial_settings & save_report_financial_settings"""
        cfg = get_report_financial_settings()
        self.assertIn('server_cost', cfg)
        self.assertIn('other_server_cost', cfg)
        self.assertIn('tax_mode', cfg)
        self.assertIn('tax_rate', cfg)

        # Simpan nilai baru
        ok = save_report_financial_settings({
            'server_cost': 125000.0,
            'other_server_cost': 25000.0,
            'other_server_notes': 'Domain .my.id & WA Gateway',
            'tax_mode': 'percent_omset',
            'tax_rate': 0.5
        })
        self.assertTrue(ok)
        updated = get_report_financial_settings()
        self.assertEqual(updated['server_cost'], 125000.0)
        self.assertEqual(updated['other_server_cost'], 25000.0)
        self.assertEqual(updated['other_server_notes'], 'Domain .my.id & WA Gateway')
        self.assertEqual(updated['tax_mode'], 'percent_omset')
        self.assertEqual(updated['tax_rate'], 0.5)

    def test_02_reports_unauthorized_redirect(self):
        """Pastikan tamu diarahkan ke login jika belum login admin"""
        res = self.client.get('/admin/reports')
        self.assertEqual(res.status_code, 302)
        self.assertIn('/admin/login', res.headers.get('Location', ''))

    def test_03_reports_all_presets_and_html_elements(self):
        """Uji seluruh preset waktu laporan dan elemen HTML Income Statement"""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        presets = ['today', 'yesterday', '7days', 'this_month', 'last_month', '30days', 'this_year', 'all']
        for p in presets:
            res = self.client.get(f'/admin/reports?range={p}')
            self.assertEqual(res.status_code, 200, f'Preset {p} gagal render')

        # Cek elemen penting dalam response
        html = res.get_data(as_text=True)
        self.assertIn('Laporan Keuangan', html)
        self.assertIn('Laba Kotor', html)
        self.assertIn('Beban Komisi', html)
        self.assertIn('Beban Klaim Poin Member', html)
        self.assertIn('Beban Pokok Sewa Server (VPS)', html)
        self.assertIn('Beban Pajak Dinamis', html)
        self.assertIn('LABA BERSIH AKHIR', html)

    def test_04_custom_date_range_and_cost_simulation(self):
        """Uji filter custom range dan simulasi beban dinamis"""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        url = '/admin/reports?range=custom&start_date=2026-09-01&end_date=2026-09-30&server_cost=150000&other_cost=30000&tax_mode=percent_omset&tax_rate=0.5'
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn('150.000', html)

    def test_05_save_reports_settings_endpoint(self):
        """Uji endpoint save_reports_settings via AJAX JSON"""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        res = self.client.post('/admin/reports/save_settings', json={
            'server_cost': 125000,
            'other_server_cost': 0,
            'other_server_notes': 'Domain, WA Gateway, SSL & Backup',
            'tax_mode': 'percent_omset',
            'tax_rate': 0.5
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))


if __name__ == '__main__':
    unittest.main()
