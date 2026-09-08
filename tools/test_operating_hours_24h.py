
"""
Test Suite: Pengujian Jam Buka & Tutup Toko Kasir Cabang dan Fitur 24 Jam Nonstop
"""
import os
import sys
import unittest
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.trusted_device import TrustedDevice
from app.services.device_service import (
    create_branch_cashier,
    update_branch_settings,
    activate_cashier_device,
    login_cashier_pin,
    verify_cashier_transaction_limits,
)

class TestOperatingHoursAnd24Hours(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app.config['SERVER_NAME'] = 'localhost'
        self.client = self.app.test_client()

        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Buat VIP Owner
        self.owner = User(
            name="Owner Test Hours",
            phone="081999888777",
            role="vip",
            role_expires_at=datetime.utcnow() + timedelta(days=60),
            balance=500000.0,
            is_device_lock_enabled=False
        )
        self.owner.set_password("OwnerPass123!")
        db.session.add(self.owner)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_01_is_24_hours_property_and_display(self):
        """Memastikan properti is_24_hours dan display bekerja benar."""
        d1 = TrustedDevice(device_name="Cabang 24H 1", operating_hours_start=None, operating_hours_end=None)
        self.assertTrue(d1.is_24_hours)
        self.assertEqual(d1.operating_hours_display, "24 Jam Nonstop")

        d2 = TrustedDevice(device_name="Cabang 24H 2", operating_hours_start="", operating_hours_end="")
        self.assertTrue(d2.is_24_hours)

        d3 = TrustedDevice(device_name="Cabang 24H 3", operating_hours_start="00:00", operating_hours_end="23:59")
        self.assertTrue(d3.is_24_hours)

        d4 = TrustedDevice(device_name="Cabang Shift", operating_hours_start="08:00", operating_hours_end="21:00")
        self.assertFalse(d4.is_24_hours)
        self.assertEqual(d4.operating_hours_display, "08:00 - 21:00 WIB")

    def test_02_midnight_crossing_operating_hours(self):
        """
        Memastikan jam operasional yang melintasi tengah malam (misal 18:00 - 04:00)
        dihitung secara akurat pada semua jam.
        """
        dev = TrustedDevice(device_name="Cabang Malam", operating_hours_start="18:00", operating_hours_end="04:00")
        self.assertFalse(dev.is_24_hours)

        def check_time(hour, minute):
            fake_wib = datetime(2026, 9, 8, hour, minute, 0)
            with patch('app.models.trusted_device.datetime') as mock_dt:
                mock_dt.now.return_value.replace.return_value = fake_wib
                return dev.is_within_operating_hours()

        # Dalam jam operasional malam (18:00 s/d 04:00):
        self.assertTrue(check_time(18, 0), "18:00 harusnya Buka")
        self.assertTrue(check_time(20, 30), "20:30 harusnya Buka")
        self.assertTrue(check_time(23, 59), "23:59 harusnya Buka")
        self.assertTrue(check_time(0, 0), "00:00 harusnya Buka")
        self.assertTrue(check_time(2, 15), "02:15 harusnya Buka")
        self.assertTrue(check_time(4, 0), "04:00 harusnya Buka")

        # Di luar jam operasional (04:01 s/d 17:59):
        self.assertFalse(check_time(4, 1), "04:01 harusnya Tutup")
        self.assertFalse(check_time(8, 0), "08:00 harusnya Tutup")
        self.assertFalse(check_time(12, 0), "12:00 harusnya Tutup")
        self.assertFalse(check_time(17, 59), "17:59 harusnya Tutup")

    def test_03_regular_daytime_operating_hours(self):
        """Memastikan jam operasional reguler siang (07:00 - 22:00) bekerja presisi."""
        dev = TrustedDevice(device_name="Cabang Siang", operating_hours_start="07:00", operating_hours_end="22:00")

        def check_time(hour, minute):
            fake_wib = datetime(2026, 9, 8, hour, minute, 0)
            with patch('app.models.trusted_device.datetime') as mock_dt:
                mock_dt.now.return_value.replace.return_value = fake_wib
                return dev.is_within_operating_hours()

        self.assertTrue(check_time(7, 0))
        self.assertTrue(check_time(12, 30))
        self.assertTrue(check_time(22, 0))

        self.assertFalse(check_time(6, 59))
        self.assertFalse(check_time(22, 1))
        self.assertFalse(check_time(23, 30))
        self.assertFalse(check_time(2, 0))

    def test_04_create_branch_with_24_hours_option(self):
        """Memastikan pembuatan cabang dengan opsi 24 jam menyetel jam ke None/24 jam."""
        ok, dev, act_url, msg = create_branch_cashier(
            user=self.owner,
            branch_name="Cabang Alfamart 24 Jam",
            pin="123456",
            daily_limit=1000000.0,
            is_24_hours=True
        )
        self.assertTrue(ok)
        self.assertTrue(dev.is_24_hours)
        self.assertIsNone(dev.operating_hours_start)
        self.assertIsNone(dev.operating_hours_end)
        self.assertTrue(dev.is_within_operating_hours())

    def test_05_update_branch_settings_to_24_hours_and_vice_versa(self):
        """Memastikan peralihan antara jam tertentu dan 24 jam berjalan lancar."""
        ok, dev, _, _ = create_branch_cashier(
            user=self.owner,
            branch_name="Cabang Fleksibel",
            pin="112233",
            hours_start="08:00",
            hours_end="17:00",
            is_24_hours=False
        )
        self.assertFalse(dev.is_24_hours)
        self.assertEqual(dev.operating_hours_start, "08:00")

        # Ubah ke 24 Jam
        ok_upd, msg_upd = update_branch_settings(
            user_id=self.owner.id,
            device_id=dev.id,
            is_24_hours=True
        )
        self.assertTrue(ok_upd)
        db.session.refresh(dev)
        self.assertTrue(dev.is_24_hours)
        self.assertIsNone(dev.operating_hours_start)
        self.assertIsNone(dev.operating_hours_end)

        # Ubah kembali ke Jam Tertentu (Lintas tengah malam 20:00 - 05:00)
        ok_upd2, msg_upd2 = update_branch_settings(
            user_id=self.owner.id,
            device_id=dev.id,
            hours_start="20:00",
            hours_end="05:00",
            is_24_hours=False
        )
        self.assertTrue(ok_upd2)
        db.session.refresh(dev)
        self.assertFalse(dev.is_24_hours)
        self.assertEqual(dev.operating_hours_start, "20:00")
        self.assertEqual(dev.operating_hours_end, "05:00")

    def test_06_cashier_login_and_checkout_enforces_operating_hours(self):
        """Memastikan login PIN dan verifikasi batas transaksi menolak jika toko tutup."""
        ok, dev, _, _ = create_branch_cashier(
            user=self.owner,
            branch_name="Cabang Malam Terkunci",
            pin="5555",
            hours_start="08:00",
            hours_end="17:00"
        )
        token_uuid = "device_uuid_locked"
        activate_cashier_device(dev.activation_token, token_uuid)

        # Simulasi toko sedang TUTUP (misal jam 23:00 W1B)
        fake_closed = datetime(2026, 9, 8, 23, 0, 0)
        with patch('app.models.trusted_device.datetime') as mock_dt:
            mock_dt.now.return_value.replace.return_value = fake_closed
            
            # login PIN harus ditolak
            ok_login, _, _, msg_login = login_cashier_pin(token_uuid, "5555")
            self.assertFalse(ok_login)
            self.assertIn("luar jam operasional", msg_login.lower())

            # Verifikasi transaksi checkout juga harus ditolak
            ok_trx, msg_trx = verify_cashier_transaction_limits(dev, 10000.0)
            self.assertFalse(ok_trx)
            self.assertIn("di luar jam kerja", msg_trx.lower())

        # Sekarang ubah cabang menjadi 24 Jam
        update_branch_settings(self.owner.id, dev.id, is_24_hours=True)

        with patch('app.models.trusted_device.datetime') as mock_dt:
            mock_dt.now.return_value.replace.return_value = fake_closed

            # login PIN pada jam 23:00 harus BERHASIL karena 24 jam
            ok_login, _, _, _ = login_cashier_pin(token_uuid, "5555")
            self.assertTrue(ok_login)

            # Verifikasi checkout pada jam 23:00 juga harus BERHASIL
            ok_trx, _ = verify_cashier_transaction_limits(dev, 10000.0)
            self.assertTrue(ok_trx)

    def test_07_http_routes_vip_device_create_and_update(self):
        """Memastikan endpoint HTTP /vip/device/create dan /vip/device/update memproses is_24_hours."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.owner.id)

        # 1. POST Create 24 Hours
        res = self.client.post('/vip/device/create', json={
            'branch_name': 'Cabang API 24 Jam',
            'pin': '9876',
            'daily_limit': 500000,
            'is_24_hours': True
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        dev_id = data['device_id']

        dev = TrustedDevice.query.get(dev_id)
        self.assertTrue(dev.is_24_hours)
        self.assertIsNone(dev.operating_hours_start)

        # 2. POST Update to Custom Hours
        res2 = self.client.post(f'/vip/device/update/{dev_id}', json={
            'branch_name': 'Cabang API 24 Jam',
            'is_24_hours': False,
            'hours_start': '09:00',
            'hours_end': '21:00'
        })
        self.assertEqual(res2.status_code, 200)
        db.session.refresh(dev)
        self.assertFalse(dev.is_24_hours)
        self.assertEqual(dev.operating_hours_start, '09:00')
        self.assertEqual(dev.operating_hours_end, '21:00')

        # 3. POST Update back to 24 Hours
        res3 = self.client.post(f'/vip/device/update/{dev_id}', json={
            'branch_name': 'Cabang API 24 Jam',
            'is_24_hours': True
        })
        self.assertEqual(res3.status_code, 200)
        db.session.refresh(dev)
        self.assertTrue(dev.is_24_hours)
        self.assertIsNone(dev.operating_hours_start)

if __name__ == '__main__':
    unittest.main()
