import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.trusted_device import TrustedDevice
from app.services.device_service import (
    create_branch_cashier,
    activate_cashier_device,
    login_cashier_pin,
    update_branch_settings,
    regenerate_activation_link,
    verify_cashier_transaction_limits,
    get_branch_cashier_history,
    now_wib
)

class TestCashierPortal(unittest.TestCase):
    def setUp(self):
        self.wa_patcher = patch('app.services.device_service.kirim_wa', return_value=True)
        self.mock_kirim_wa = self.wa_patcher.start()

        # Mock provider calls
        self.digi_patcher = patch('app.services.digiflazz.create_transaction', return_value=(True, {'status': 'SUCCESS', 'sn': 'SN-KASIR-12345'}, 'Sukses'))
        self.mock_digi = self.digi_patcher.start()

        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SERVER_NAME'] = 'localhost'
        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Setup VIP Owner
        self.vip_owner = User(
            name="Owner Konter VIP",
            phone="081122334455",
            role="vip",
            role_expires_at=now_wib() + timedelta(days=60),
            balance=1000000.0,
            is_device_lock_enabled=False
        )
        self.vip_owner.set_password("ownersecret123")
        db.session.add(self.vip_owner)

        # Setup Regular Member (Non-VIP)
        self.regular_user = User(
            name="Member Reguler",
            phone="089988776655",
            role="user",
            balance=50000.0
        )
        self.regular_user.set_password("regularsecret123")
        db.session.add(self.regular_user)

        # Setup Dummy Products
        self.prod_pulsa = Product(
            sku_code="TLKM5",
            name="Telkomsel 5.000",
            category="PULSA",
            brand="TELKOMSEL",
            base_price=5100.0,
            sell_price=5500.0,
            is_active=True
        )
        self.prod_game = Product(
            sku_code="FF50",
            name="Free Fire 50 Diamond",
            category="GAMES",
            brand="VIP-GARENA",
            base_price=7000.0,
            sell_price=8000.0,
            is_active=True
        )
        db.session.add(self.prod_pulsa)
        db.session.add(self.prod_game)

        db.session.commit()

    def tearDown(self):
        self.wa_patcher.stop()
        self.digi_patcher.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_01_non_vip_cannot_create_branch_cashier(self):
        """Memastikan akun non-VIP ditolak membuat cabang kasir."""
        ok, dev, act_url, msg = create_branch_cashier(
            user=self.regular_user,
            branch_name="Cabang Ilegal",
            pin="1234"
        )
        self.assertFalse(ok)
        self.assertIsNone(dev)
        self.assertIn("vip", msg.lower())

    def test_02_vip_owner_creates_branch_cashier(self):
        """Memastikan VIP Owner berhasil membuat cabang kasir dengan PIN dan limit harian."""
        ok, dev, act_url, msg = create_branch_cashier(
            user=self.vip_owner,
            branch_name="Cabang 1 - Pasar Baru",
            pin="889900",
            daily_limit=500000.0,
            hours_start="07:00",
            hours_end="22:00",
            base_url="http://localhost"
        )
        self.assertTrue(ok)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.device_name, "Cabang 1 - Pasar Baru")
        self.assertEqual(dev.status, 'pending')
        self.assertEqual(dev.daily_limit, 500000.0)
        self.assertEqual(dev.operating_hours_start, "07:00")
        self.assertEqual(dev.operating_hours_end, "22:00")
        self.assertTrue(dev.check_pin("889900"))
        self.assertFalse(dev.check_pin("123456"))
        self.assertIsNotNone(dev.activation_token)
        self.assertIn(dev.activation_token, act_url)

    def test_03_invalid_pin_rejected(self):
        """Memastikan PIN yang bukan 4-6 digit angka ditolak saat pembuatan cabang."""
        # Terlalu pendek
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang 2", "12")
        self.assertFalse(ok)
        # Terlalu panjang
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang 2", "1234567")
        self.assertFalse(ok)
        # Mengandung huruf
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang 2", "12ab")
        self.assertFalse(ok)

    def test_04_activate_cashier_device_success(self):
        """Memastikan tautan aktivasi mengikat browser toko dan menghanguskan token."""
        ok, dev, act_url, msg = create_branch_cashier(
            user=self.vip_owner,
            branch_name="Cabang 2 - Mall",
            pin="123456"
        )
        token = dev.activation_token
        test_uuid = "gt_pos_browser_uuid_test_123"

        # Aktivasi
        ok_act, act_dev, msg_act = activate_cashier_device(
            token=token,
            device_uuid=test_uuid,
            user_agent="Mozilla/5.0 POS Terminal",
            ip_address="192.168.1.100"
        )
        self.assertTrue(ok_act)
        self.assertEqual(act_dev.status, 'approved')
        self.assertEqual(act_dev.device_uuid, test_uuid)
        self.assertIsNone(act_dev.activation_token)

        # Coba gunakan token yang sama kedua kalinya (harus gagal)
        ok_act2, act_dev2, msg_act2 = activate_cashier_device(
            token=token,
            device_uuid="another_uuid"
        )
        self.assertFalse(ok_act2)

    def test_05_cashier_pin_login(self):
        """Memastikan login PIN kasir berhasil tanpa OTP WA ke Owner."""
        ok, dev, act_url, msg = create_branch_cashier(
            user=self.vip_owner,
            branch_name="Cabang 3",
            pin="654321"
        )
        test_uuid = "pos_device_3"
        activate_cashier_device(dev.activation_token, test_uuid)

        # 1. PIN Salah
        ok_l, dev_l, own_l, msg_l = login_cashier_pin(test_uuid, "999999")
        self.assertFalse(ok_l)
        self.assertIn("salah", msg_l.lower())

        # 2. PIN Benar
        ok_l2, dev_l2, own_l2, msg_l2 = login_cashier_pin(test_uuid, "654321")
        self.assertTrue(ok_l2)
        self.assertEqual(dev_l2.id, dev.id)
        self.assertEqual(own_l2.id, self.vip_owner.id)

    def test_06_route_activation_sets_cookie(self):
        """Memastikan route GET /kasir/aktivasi/<token> mengeset cookie gt_device_token."""
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang 4", "112233")
        token = dev.activation_token

        resp = self.client.get(f"/kasir/aktivasi/{token}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Aktivasi Kasir Berhasil", resp.data.decode('utf-8'))
        
        # Pastikan cookie gt_device_token terpasang
        cookie_header = resp.headers.get('Set-Cookie', '')
        self.assertIn('gt_device_token=', cookie_header)

    def test_07_route_pin_login_and_pos_access(self):
        """Memastikan alur lengkap dari aktivasi, PIN login via AJAX, hingga layar POS."""
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang Utama", "445566")
        test_uuid = "uuid_cabang_utama"
        activate_cashier_device(dev.activation_token, test_uuid)

        # Set cookie di test client
        self.client.set_cookie('gt_device_token', test_uuid, domain='localhost')

        # Akses /kasir sebelum login PIN -> Muncul layar PIN Login
        res_index1 = self.client.get('/kasir/')
        self.assertEqual(res_index1.status_code, 200)
        self.assertIn("Buka Shift Kasir", res_index1.data.decode('utf-8'))

        # Kirim PIN via AJAX POST /kasir/login_pin
        res_login = self.client.post('/kasir/login_pin', json={'pin': '445566'})
        self.assertEqual(res_login.status_code, 200)
        json_data = res_login.get_json()
        self.assertEqual(json_data['status'], 'success')
        self.assertEqual(json_data['redirect'], '/kasir')

        # Akses /kasir setelah login PIN -> Muncul POS Transaksi
        res_index2 = self.client.get('/kasir/')
        self.assertEqual(res_index2.status_code, 200)
        self.assertIn("Cabang Utama", res_index2.data.decode('utf-8'))
        self.assertIn("Kasir POS", res_index2.data.decode('utf-8'))

    def test_08_cashier_products_catalog(self):
        """Memastikan endpoint /kasir/products mengembalikan harga VIP toko."""
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang Toko", "1234")
        test_uuid = "uuid_katalog"
        activate_cashier_device(dev.activation_token, test_uuid)
        self.client.set_cookie('gt_device_token', test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234'})

        res = self.client.get('/kasir/products')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertTrue(data['count'] >= 2)
        skus = [p['sku_code'] for p in data['products']]
        self.assertIn('TLKM5', skus)

    def test_09_cashier_checkout_success(self):
        """Memastikan kasir cabang dapat checkout: memotong saldo Owner & mencatat nama cabang."""
        ok, dev, act_url, msg = create_branch_cashier(
            self.vip_owner,
            "Cabang Sudirman",
            "778899",
            daily_limit=100000.0,
            hours_start="00:00",
            hours_end="23:59"
        )
        test_uuid = "uuid_sudirman"
        activate_cashier_device(dev.activation_token, test_uuid)
        dev.branch_balance = 100000.0
        db.session.commit()
        self.client.set_cookie('gt_device_token', test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '778899', 'shift_name': 'Budi (Shift Pagi)'})

        initial_branch_balance = dev.branch_balance

        # Eksekusi checkout
        res = self.client.post('/kasir/checkout', json={
            'sku_code': 'TLKM5',
            'target_number': '08123456789'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['trx']['branch_name'], "Cabang Sudirman")
        self.assertEqual(data['trx']['sn'], "SN-KASIR-12345")

        # Cek saldo cabang kasir terpotong
        updated_dev = db.session.get(TrustedDevice, dev.id)
        self.assertLess(updated_dev.branch_balance, initial_branch_balance)

        # Cek transaksi tercatat di database dengan device_id
        trx = Transaction.query.filter_by(ref_id=data['trx']['ref_id']).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.device_id, dev.id)
        self.assertEqual(trx.device_name, "Cabang Sudirman")

    def test_10_cashier_checkout_daily_limit_exceeded(self):
        """Memastikan transaksi ditolak jika melebihi plafon limit harian cabang."""
        ok, dev, act_url, msg = create_branch_cashier(
            self.vip_owner,
            "Cabang Kecil",
            "1234",
            daily_limit=5000.0,
            hours_start="00:00",
            hours_end="23:59"
        )
        test_uuid = "uuid_limit_test"
        activate_cashier_device(dev.activation_token, test_uuid)
        dev.branch_balance = 50000.0
        db.session.commit()
        self.client.set_cookie('gt_device_token', test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234'})

        res = self.client.post('/kasir/checkout', json={
            'sku_code': 'TLKM5',
            'target_number': '08123456789'
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("limit harian", data['message'].lower())

    def test_11_cashier_checkout_outside_operating_hours(self):
        """Memastikan transaksi ditolak jika dilakukan di luar jam kerja operasional cabang."""
        ok, dev, act_url, msg = create_branch_cashier(
            self.vip_owner,
            "Cabang Malam",
            "1234",
            daily_limit=0.0,
            hours_start="02:00",
            hours_end="02:01"
        )
        test_uuid = "uuid_hours_test"
        activate_cashier_device(dev.activation_token, test_uuid)
        self.client.set_cookie('gt_device_token', test_uuid, domain='localhost')

        with patch.object(dev, 'is_within_operating_hours', return_value=False):
            ok_lim, err_lim = verify_cashier_transaction_limits(dev, 5000.0)
            self.assertFalse(ok_lim)
            self.assertIn("jam kerja", err_lim.lower())

    def test_12_cashier_history_isolated_per_branch(self):
        """Memastikan riwayat transaksi cabang hanya menampilkan transaksi cabang tersebut."""
        # Cabang A
        ok1, dev1, _, _ = create_branch_cashier(self.vip_owner, "Cabang A", "1111")
        uuid1 = "uuid_cabang_a"
        activate_cashier_device(dev1.activation_token, uuid1)

        # Cabang B
        ok2, dev2, _, _ = create_branch_cashier(self.vip_owner, "Cabang B", "2222")
        uuid2 = "uuid_cabang_b"
        activate_cashier_device(dev2.activation_token, uuid2)

        # Buat transaksi buatan untuk Cabang A
        trx_a = Transaction(
            user_id=self.vip_owner.id,
            ref_id="TRX-A-1",
            product_name="Telkomsel 5K",
            sku_code="TLKM5",
            target_number="08111",
            amount=5000.0,
            payment_method='SALDO',
            status='SUCCESS',
            device_id=dev1.id,
            device_name=dev1.device_name
        )
        # Buat transaksi buatan untuk Cabang B
        trx_b = Transaction(
            user_id=self.vip_owner.id,
            ref_id="TRX-B-1",
            product_name="Telkomsel 10K",
            sku_code="TLKM10",
            target_number="08222",
            amount=10000.0,
            payment_method='SALDO',
            status='SUCCESS',
            device_id=dev2.id,
            device_name=dev2.device_name
        )
        db.session.add(trx_a)
        db.session.add(trx_b)
        db.session.commit()

        # Riwayat Cabang A
        hist_a = get_branch_cashier_history(dev1.id)
        self.assertEqual(len(hist_a), 1)
        self.assertEqual(hist_a[0].ref_id, "TRX-A-1")

        # Riwayat Cabang B
        hist_b = get_branch_cashier_history(dev2.id)
        self.assertEqual(len(hist_b), 1)
        self.assertEqual(hist_b[0].ref_id, "TRX-B-1")

    def test_13_owner_update_branch_and_regenerate_token(self):
        """Memastikan Owner dapat mengupdate cabang dan me-regenerate link aktivasi."""
        ok, dev, _, _ = create_branch_cashier(self.vip_owner, "Cabang Lama", "1234")
        
        # 1. Update nama, PIN, dan limit
        ok_up, msg_up = update_branch_settings(
            user_id=self.vip_owner.id,
            device_id=dev.id,
            branch_name="Cabang Baru Rebranded",
            new_pin="9988",
            daily_limit=2000000.0
        )
        self.assertTrue(ok_up)
        updated_dev = db.session.get(TrustedDevice, dev.id)
        self.assertEqual(updated_dev.device_name, "Cabang Baru Rebranded")
        self.assertTrue(updated_dev.check_pin("9988"))
        self.assertEqual(updated_dev.daily_limit, 2000000.0)

        # 2. Regenerate link aktivasi (misal jika PC toko diganti)
        ok_reg, new_url, msg_reg = regenerate_activation_link(self.vip_owner.id, dev.id, "http://localhost")
        self.assertTrue(ok_reg)
        self.assertIsNotNone(updated_dev.activation_token)
        self.assertEqual(updated_dev.status, 'pending')
        self.assertIn(updated_dev.activation_token, new_url)

    def test_14_cashier_logout(self):
        """Memastikan logout menghapus sesi kasir dan kembali ke layar login PIN."""
        ok, dev, act_url, msg = create_branch_cashier(self.vip_owner, "Cabang Logout", "1234")
        test_uuid = "uuid_logout"
        activate_cashier_device(dev.activation_token, test_uuid)
        self.client.set_cookie('gt_device_token', test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234'})

        # Sesi aktif
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get('cashier_device_id'), dev.id)

        # Logout
        resp = self.client.get('/kasir/logout')
        self.assertEqual(resp.status_code, 302)

        # Sesi kasir telah dihapus
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('cashier_device_id'))


if __name__ == '__main__':
    unittest.main()

