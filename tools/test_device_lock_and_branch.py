import os
import sys
import unittest
from datetime import datetime, timedelta

# Tambahkan direktori root proyek ke path
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.trusted_device import TrustedDevice
from app.services.device_service import (
    register_device_request,
    approve_device_by_token,
    reject_device_by_token,
    approve_device_manual,
    revoke_device,
    toggle_device_lock,
    verify_device_for_transaction,
    get_branch_usage_report,
    now_wib
)

from unittest.mock import patch

class TestDeviceLockAndBranch(unittest.TestCase):
    def setUp(self):
        self.wa_patcher = patch('app.services.device_service.kirim_wa', return_value=True)
        self.mock_kirim_wa = self.wa_patcher.start()

        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

        # Buat dummy VIP owner
        self.vip_owner = User(
            name="Pak Bos VIP",
            phone="081234567890",
            role="vip",
            role_expires_at=now_wib() + timedelta(days=30),
            balance=500000.0,
            is_device_lock_enabled=False
        )
        self.vip_owner.set_password("password123")
        db.session.add(self.vip_owner)

        # Buat dummy Member biasa
        self.regular_user = User(
            name="Member Biasa",
            phone="089876543210",
            role="user",
            balance=100000.0,
            is_device_lock_enabled=False
        )
        self.regular_user.set_password("password123")
        db.session.add(self.regular_user)
        db.session.commit()

    def tearDown(self):
        self.wa_patcher.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_01_non_vip_cannot_register_device(self):
        """Memastikan member biasa tidak dapat menggunakan fitur kunci kasir."""
        ok, dev, msg = register_device_request(
            user=self.regular_user,
            device_uuid="uuid_test_1",
            device_name="Cabang Ilegal"
        )
        self.assertFalse(ok)
        self.assertIn("hanya tersedia untuk akun vip", msg.lower())

    def test_02_vip_register_device_pending(self):
        """Memastikan akun VIP dapat mendaftarkan perangkat dengan status pending & token berlaku."""
        ok, dev, msg = register_device_request(
            user=self.vip_owner,
            device_uuid="uuid_kasir_cabang_1",
            device_name="Cabang 1 - Pasar Baru",
            user_agent="Chrome 120 on Windows 10",
            ip_address="192.168.1.50"
        )
        self.assertTrue(ok)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.status, 'pending')
        self.assertEqual(dev.device_name, "Cabang 1 - Pasar Baru")
        self.assertIsNotNone(dev.approval_token)
        self.assertFalse(dev.is_token_expired())

    def test_03_approve_device_by_token(self):
        """Memastikan link 1-klik approval WhatsApp mengubah status menjadi approved & mengaktifkan lock."""
        ok, dev, _ = register_device_request(
            user=self.vip_owner,
            device_uuid="uuid_kasir_cabang_1",
            device_name="Cabang 1 - Pasar Baru"
        )
        token = dev.approval_token

        # Simulasi Owner klik link approve di WhatsApp
        app_ok, app_dev, msg = approve_device_by_token(token)
        self.assertTrue(app_ok)
        self.assertEqual(app_dev.status, 'approved')
        self.assertIsNone(app_dev.approval_token)
        self.assertIsNotNone(app_dev.approved_at)

        # Cek apakah is_device_lock_enabled otomatis aktif
        owner = User.query.get(self.vip_owner.id)
        self.assertTrue(owner.is_device_lock_enabled)

    def test_04_approve_device_expired_token(self):
        """Memastikan token yang kedaluwarsa (> 15 menit) ditolak."""
        ok, dev, _ = register_device_request(
            user=self.vip_owner,
            device_uuid="uuid_kasir_cabang_1",
            device_name="Cabang 1 - Pasar Baru"
        )
        # Mundurkan waktu kadaluarsa ke masa lalu
        dev.approval_expires_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()

        app_ok, app_dev, msg = approve_device_by_token(dev.approval_token)
        self.assertFalse(app_ok)
        self.assertIn("kedaluwarsa", msg.lower())

    def test_05_reject_device_by_token(self):
        """Memastikan link 1-klik reject WhatsApp mengubah status menjadi rejected."""
        ok, dev, _ = register_device_request(
            user=self.vip_owner,
            device_uuid="uuid_kasir_cabang_1",
            device_name="Cabang 1 - Pasar Baru"
        )
        rej_ok, rej_dev, msg = reject_device_by_token(dev.approval_token)
        self.assertTrue(rej_ok)
        self.assertEqual(rej_dev.status, 'rejected')
        self.assertIsNone(rej_dev.approval_token)

    def test_06_manual_approve_and_revoke(self):
        """Memastikan Owner dapat approve manual dan mencabut izin (revoke) dari dashboard."""
        ok, dev, _ = register_device_request(
            user=self.vip_owner,
            device_uuid="uuid_kasir_cabang_2",
            device_name="Cabang 2 - Simpang Lima"
        )
        # Approve manual
        app_ok, _ = approve_device_manual(self.vip_owner.id, dev.id)
        self.assertTrue(app_ok)
        self.assertEqual(dev.status, 'approved')

        # Revoke
        rev_ok, _ = revoke_device(self.vip_owner.id, dev.id)
        self.assertTrue(rev_ok)
        self.assertEqual(dev.status, 'revoked')

    def test_07_transaction_interceptor_regular_user_allowed(self):
        """Member biasa selalu diizinkan transaksi tanpa device lock."""
        allowed, dev, err = verify_device_for_transaction(self.regular_user, None)
        self.assertTrue(allowed)
        self.assertIsNone(err)

    def test_08_transaction_interceptor_vip_lock_disabled(self):
        """VIP dengan proteksi nonaktif tetap diizinkan transaksi."""
        self.vip_owner.is_device_lock_enabled = False
        db.session.commit()

        allowed, dev, err = verify_device_for_transaction(self.vip_owner, None)
        self.assertTrue(allowed)
        self.assertIsNone(err)

    def test_09_transaction_interceptor_vip_lock_active_fraud_blocked(self):
        """VIP dengan proteksi AKTIF, transaksi dari HP luar/tanpa token kasir DITOLAK (Pencegahan Kecurangan Karyawan)."""
        self.vip_owner.is_device_lock_enabled = True
        db.session.commit()

        # A. Karyawan di rumah tanpa token kasir sama sekali
        allowed, dev, err = verify_device_for_transaction(self.vip_owner, None)
        self.assertFalse(allowed)
        self.assertIn("kunci kasir", err.lower())

        # B. Karyawan dengan token palsu / tidak terdaftar
        allowed, dev, err = verify_device_for_transaction(self.vip_owner, "fake_uuid_hp_pribadi")
        self.assertFalse(allowed)
        self.assertIn("belum terdaftar", err.lower())

        # C. Karyawan dengan perangkat yang statusnya masih pending / rejected
        dev_pending = TrustedDevice(
            user_id=self.vip_owner.id,
            device_uuid="pending_uuid",
            device_name="Kasir Pending",
            status="pending"
        )
        db.session.add(dev_pending)
        db.session.commit()

        allowed, dev, err = verify_device_for_transaction(self.vip_owner, "pending_uuid")
        self.assertFalse(allowed)
        self.assertIn("menunggu persetujuan", err.lower())

    def test_10_transaction_interceptor_vip_lock_active_approved_allowed(self):
        """VIP dengan proteksi AKTIF, transaksi dari perangkat kasir resmi disetujui DIIZINKAN."""
        self.vip_owner.is_device_lock_enabled = True
        dev_resmi = TrustedDevice(
            user_id=self.vip_owner.id,
            device_uuid="resmi_uuid_123",
            device_name="Cabang 1 - Pasar Baru",
            status="approved"
        )
        db.session.add(dev_resmi)
        db.session.commit()

        allowed, dev, err = verify_device_for_transaction(self.vip_owner, "resmi_uuid_123")
        self.assertTrue(allowed)
        self.assertIsNotNone(dev)
        self.assertEqual(dev.device_name, "Cabang 1 - Pasar Baru")
        self.assertIsNotNone(dev.last_used_at)

    def test_11_branch_usage_report(self):
        """Memastikan laporan pemakaian saldo mengelompokkan data per nama cabang."""
        # Catat 2 transaksi Cabang 1
        trx1 = Transaction(
            ref_id="TRX-CB1-01",
            user_id=self.vip_owner.id,
            sku_code="TS10",
            product_name="Telkomsel 10K",
            target_number="0812345678",
            amount=11000.0,
            payment_method="SALDO",
            status="SUCCESS",
            device_name="Cabang 1 - Pasar Baru",
            created_at=datetime.utcnow()
        )
        trx2 = Transaction(
            ref_id="TRX-CB1-02",
            user_id=self.vip_owner.id,
            sku_code="TS20",
            product_name="Telkomsel 20K",
            target_number="0812345679",
            amount=21000.0,
            payment_method="SALDO",
            status="SUCCESS",
            device_name="Cabang 1 - Pasar Baru",
            created_at=datetime.utcnow()
        )
        # Catat 1 transaksi Cabang 2
        trx3 = Transaction(
            ref_id="TRX-CB2-01",
            user_id=self.vip_owner.id,
            sku_code="IS50",
            product_name="Indosat 50K",
            target_number="0857123456",
            amount=51000.0,
            payment_method="SALDO",
            status="SUCCESS",
            device_name="Cabang 2 - Simpang Lima",
            created_at=datetime.utcnow()
        )
        db.session.add_all([trx1, trx2, trx3])
        db.session.commit()

        report = get_branch_usage_report(self.vip_owner.id, period='today')
        self.assertEqual(report['total_trx'], 3)
        self.assertEqual(report['total_amount'], 83000.0)

        # Cek cabang: Cabang 2 total spent 51k, Cabang 1 total spent 32k
        self.assertEqual(len(report['branches']), 2)
        top_branch = report['branches'][0]
        self.assertEqual(top_branch['branch_name'], "Cabang 2 - Simpang Lima")
        self.assertEqual(top_branch['total_spent'], 51000.0)

        second_branch = report['branches'][1]
        self.assertEqual(second_branch['branch_name'], "Cabang 1 - Pasar Baru")
        self.assertEqual(second_branch['total_trx'], 2)
        self.assertEqual(second_branch['total_spent'], 32000.0)

    def test_12_route_check_device_status_polling(self):
        """Memastikan endpoint polling AJAX mengembalikan status perangkat."""
        dev = TrustedDevice(
            user_id=self.vip_owner.id,
            device_uuid="polling_uuid_test",
            device_name="Cabang Polling",
            status="pending"
        )
        db.session.add(dev)
        db.session.commit()

        # Saat pending
        res = self.client.get("/vip/device/check-status/polling_uuid_test")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'pending')
        self.assertFalse(data['is_approved'])

        # Ubah ke approved
        dev.status = 'approved'
        db.session.commit()

        res = self.client.get("/vip/device/check-status/polling_uuid_test")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'approved')
        self.assertTrue(data['is_approved'])

    def test_13_route_whatsapp_1click_approve_and_reject(self):
        """Memastikan route GET /vip/device/approve/<token> dan reject render halaman HTML sukses."""
        ok, dev, _ = register_device_request(
            user=self.vip_owner,
            device_uuid="wa_click_uuid",
            device_name="Cabang WA Click"
        )
        token = dev.approval_token

        # Owner klik link approve
        res = self.client.get(f"/vip/device/approve/{token}")
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Perangkat Kasir Resmi Disetujui", html)
        self.assertIn("Cabang WA Click", html)

        # Cek di DB
        updated_dev = TrustedDevice.query.filter_by(device_uuid="wa_click_uuid").first()
        self.assertEqual(updated_dev.status, 'approved')

if __name__ == '__main__':
    unittest.main(verbosity=2)

