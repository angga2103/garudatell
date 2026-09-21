"""
Unit Test: Pengujian Fitur Sort Data User & Jumlah Saldo User di Panel Admin (/admin/users)
"""
import unittest
import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.admin import Admin

class TestUserSortAndTotalBalance(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            # Pastikan admin ada
            admin = Admin.query.first()
            if not admin:
                admin = Admin(username='admin')
                admin.set_password('admin123')
                db.session.add(admin)
                db.session.commit()

            # Bersihkan user testing lama jika ada
            User.query.filter(User.phone.like('089999999%')).delete()
            db.session.commit()

            # Buat 3 user dengan variasi saldo untuk uji sort
            # User A: Saldo Rp 150.000 (Terbanyak)
            u_a = User(name='Toko Alpha Testing', phone='08999999901', balance=150000.0, role='vip', points=100, is_active=True)
            u_a.set_password('pass123')
            # User B: Saldo Rp 25.000 (Minim < 100rb)
            u_b = User(name='Toko Beta Testing', phone='08999999902', balance=25000.0, role='reseller', points=50, is_active=True)
            u_b.set_password('pass123')
            # User C: Saldo Rp 0 (Paling Sedikit)
            u_c = User(name='Toko Charlie Testing', phone='08999999903', balance=0.0, role='user', points=10, is_active=True)
            u_c.set_password('pass123')

            db.session.add_all([u_a, u_b, u_c])
            db.session.commit()

            self.uid_a = u_a.id
            self.uid_b = u_b.id
            self.uid_c = u_c.id

    def tearDown(self):
        with self.app.app_context():
            User.query.filter(User.phone.like('089999999%')).delete()
            db.session.commit()

    def test_admin_users_renders_total_balance_card(self):
        """Uji apakah halaman /admin/users menampilkan card TOTAL SALDO USER."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        res = self.client.get('/admin/users')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Cek card Total Saldo User ada di halaman
        self.assertIn('TOTAL SALDO USER', html)
        self.assertIn('Urutkan Saldo / Data', html)
        self.assertIn('Jumlah Saldo Ditampilkan:', html)

    def test_sort_by_saldo_desc(self):
        """Uji pengurutan saldo terbanyak (saldo_desc)."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        res = self.client.get('/admin/users?sort=saldo_desc&q=089999999')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        pos_alpha = html.find('Toko Alpha Testing')
        pos_beta = html.find('Toko Beta Testing')
        pos_charlie = html.find('Toko Charlie Testing')

        self.assertTrue(pos_alpha != -1 and pos_beta != -1 and pos_charlie != -1)
        # Saldo terbanyak harus muncul pertama, lalu kedua, lalu ketiga
        self.assertTrue(pos_alpha < pos_beta < pos_charlie, "Urutan harus Alpha (150rb) -> Beta (25rb) -> Charlie (0)")

    def test_sort_by_saldo_asc(self):
        """Uji pengurutan saldo paling sedikit (saldo_asc)."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        res = self.client.get('/admin/users?sort=saldo_asc&q=089999999')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        pos_alpha = html.find('Toko Alpha Testing')
        pos_beta = html.find('Toko Beta Testing')
        pos_charlie = html.find('Toko Charlie Testing')

        self.assertTrue(pos_alpha != -1 and pos_beta != -1 and pos_charlie != -1)
        # Saldo paling sedikit harus muncul pertama
        self.assertTrue(pos_charlie < pos_beta < pos_alpha, "Urutan harus Charlie (0) -> Beta (25rb) -> Alpha (150rb)")

    def test_filter_by_low_balance(self):
        """Uji filter saldo minim (< 100rb)."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        res = self.client.get('/admin/users?balance=low&q=089999999')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertNotIn('Toko Alpha Testing', html) # Saldo 150rb tidak boleh muncul
        self.assertIn('Toko Beta Testing', html)    # Saldo 25rb harus muncul
        self.assertIn('Toko Charlie Testing', html) # Saldo 0 harus muncul

    def test_search_user_query(self):
        """Uji pencarian pengguna berdasarkan kata kunci nama toko."""
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        res = self.client.get('/admin/users?q=Alpha')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        self.assertIn('Toko Alpha Testing', html)
        self.assertNotIn('Toko Beta Testing', html)
        self.assertNotIn('Toko Charlie Testing', html)

if __name__ == '__main__':
    unittest.main()
