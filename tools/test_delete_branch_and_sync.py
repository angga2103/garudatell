import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.trusted_device import TrustedDevice
from app.models.branch_mutation import BranchMutation
from app.services.device_service import (
    create_branch_cashier,
    activate_cashier_device,
    login_cashier_pin,
    delete_branch_cashier,
    sync_pending_cashier_transactions,
    transfer_balance_to_branch,
    now_wib
)

class TestDeleteBranchAndSync(unittest.TestCase):
    def setUp(self):
        self.wa_patcher = patch('app.services.device_service.kirim_wa', return_value=True)
        self.mock_kirim_wa = self.wa_patcher.start()

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
        self.owner = User(
            name="Owner Test Cabang",
            phone="081211112222",
            role="vip",
            role_expires_at=now_wib() + timedelta(days=90),
            balance=500000.0,
            is_device_lock_enabled=True
        )
        self.owner.set_password("ownerpwd123")
        db.session.add(self.owner)
        db.session.commit()

        # Setup Branch Device with Balance
        ok, dev, act_url, _ = create_branch_cashier(
            user=self.owner,
            branch_name="Cabang Blok M",
            pin="1234",
            daily_limit=0.0
        )
        self.device = dev
        self.test_uuid = "gt_device_blok_m_uuid"
        activate_cashier_device(dev.activation_token, self.test_uuid)

        # Berikan saldo ke cabang 150.000
        transfer_balance_to_branch(self.owner.id, self.device.id, 150000.0)
        # Saldo owner sekarang: 350.000, Saldo cabang: 150.000

        # Setup Products
        p1 = Product(sku_code="PLN20", name="PLN 20K", category="PLN", brand="PLN", base_price=20000, sell_price=21500, is_active=True)
        p2 = Product(sku_code="TS5", name="Pulsa 5K", category="PULSA", brand="TELKOMSEL", base_price=5000, sell_price=6000, is_active=True)
        p3 = Product(sku_code="TD10", name="Data 10GB", category="DATA", brand="TELKOMSEL", base_price=25000, sell_price=27000, is_active=True)
        p4 = Product(sku_code="DANA10", name="Dana 10K", category="EMONEY", brand="DANA", base_price=10000, sell_price=11000, is_active=True)
        db.session.add_all([p1, p2, p3, p4])
        db.session.commit()

    def tearDown(self):
        self.wa_patcher.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_01_delete_branch_refunds_balance_to_owner(self):
        """Hapus cabang harus mengembalikan seluruh sisa saldo cabang ke saldo utama owner."""
        owner_before = self.owner.balance # 350.000
        branch_bal = self.device.branch_balance # 150.000

        ok, msg = delete_branch_cashier(self.owner.id, self.device.id)
        self.assertTrue(ok)
        self.assertIn("dikembalikan", msg.lower())

        # Reload data
        db.session.refresh(self.owner)
        dev = db.session.get(TrustedDevice, self.device.id)

        # Saldo owner harus bertambah 150.000 -> 500.000
        self.assertEqual(self.owner.balance, 500000.0)
        self.assertEqual(dev.branch_balance, 0.0)
        self.assertEqual(dev.status, 'deleted')
        self.assertTrue(dev.device_uuid.startswith('deleted_'))

        # Cek mutasi cabang tercatat WITHDRAW_TO_OWNER
        mut = BranchMutation.query.filter_by(device_id=dev.id, type='WITHDRAW_TO_OWNER').first()
        self.assertIsNotNone(mut)
        self.assertEqual(mut.amount, 150000.0)

    def test_02_delete_branch_not_visible_in_owner_devices(self):
        """Cabang yang dihapus tidak boleh muncul di list /vip/devices."""
        delete_branch_cashier(self.owner.id, self.device.id)

        # Login as owner
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.owner.id)

        resp = self.client.get('/vip/devices')
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(b'Cabang Blok M', resp.data)

    def test_03_token_pln_brands_endpoint_only_returns_pln(self):
        """Endpoint /kasir/brands?category=PLN tidak boleh menampilkan operator/game/e-wallet."""
        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234', 'shift_name': 'Kasir Test'})

        resp = self.client.get('/kasir/brands?category=PLN')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['brands'], ['PLN'])
        self.assertNotIn('TELKOMSEL', data['brands'])
        self.assertNotIn('DANA', data['brands'])

    def test_04_category_switch_products_endpoint(self):
        """Kategori PULSA vs DATA mengembalikan produk yang sesuai."""
        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234', 'shift_name': 'Kasir Test'})

        resp_pulsa = self.client.get('/kasir/products?category=PULSA&brand=TELKOMSEL')
        data_pulsa = resp_pulsa.get_json()
        self.assertEqual(data_pulsa['status'], 'success')
        self.assertEqual(len(data_pulsa['products']), 1)
        self.assertEqual(data_pulsa['products'][0]['sku_code'], 'TS5')

        resp_data = self.client.get('/kasir/products?category=DATA&brand=TELKOMSEL')
        data_data = resp_data.get_json()
        self.assertEqual(data_data['status'], 'success')
        self.assertEqual(len(data_data['products']), 1)
        self.assertEqual(data_data['products'][0]['sku_code'], 'TD10')

    @patch('app.services.digiflazz.check_transaction_status')
    def test_05_sync_pending_transactions_success(self, mock_check_status):
        """Transaksi pending yang dicek sukses di provider menjadi SUCCESS dan SN terisi."""
        mock_check_status.return_value = (True, {'status': 'SUCCESS', 'sn': 'PLN-TOKEN-123456789'}, 'Sukses')

        trx = Transaction(
            ref_id="REF-PENDING-01",
            user_id=self.owner.id,
            device_id=self.device.id,
            device_name=self.device.device_name,
            sku_code="PLN20",
            product_name="Token PLN 20K",
            target_number="14001234567",
            amount=21500.0,
            payment_method="SALDO",
            payment_status="PAID",
            status="PROCESSING"
        )
        db.session.add(trx)
        db.session.commit()

        # Jalankan sinkronisasi
        sync_pending_cashier_transactions(self.device.id)

        db.session.refresh(trx)
        self.assertEqual(trx.status, 'SUCCESS')
        self.assertEqual(trx.sn, 'PLN-TOKEN-123456789')

    @patch('app.services.digiflazz.check_transaction_status')
    def test_06_sync_pending_transactions_failed_refunds_branch_balance(self, mock_check_status):
        """Transaksi pending yang gagal di provider di-refund otomatis ke saldo cabang."""
        mock_check_status.return_value = (True, {'status': 'FAILED', 'sn': ''}, 'Nomor Tujuan Salah')

        branch_bal_before = self.device.branch_balance # 150.000

        trx = Transaction(
            ref_id="REF-FAIL-01",
            user_id=self.owner.id,
            device_id=self.device.id,
            device_name=self.device.device_name,
            sku_code="PLN20",
            product_name="Token PLN 20K",
            target_number="14001234567",
            amount=21500.0,
            payment_method="SALDO",
            payment_status="PAID",
            status="PROCESSING"
        )
        db.session.add(trx)
        db.session.commit()

        sync_pending_cashier_transactions(self.device.id)

        db.session.refresh(trx)
        db.session.refresh(self.device)

        self.assertEqual(trx.status, 'FAILED')
        # Saldo cabang harus bertambah 21.500 -> 171.500
        self.assertEqual(self.device.branch_balance, branch_bal_before + 21500.0)

        # Mutasi REFUND tercatat
        mut = BranchMutation.query.filter_by(device_id=self.device.id, type='REFUND').first()
        self.assertIsNotNone(mut)
        self.assertEqual(mut.amount, 21500.0)

    @patch('app.services.device_service.sync_pending_cashier_transactions')
    def test_07_kasir_history_endpoint_triggers_sync_and_returns_balance(self, mock_sync):
        """Endpoint /kasir/history memanggil sync dan mengembalikan current_balance cabang."""
        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234', 'shift_name': 'Kasir Test'})

        resp = self.client.get('/kasir/history')
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()

        mock_sync.assert_called_once_with(self.device.id)
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['current_balance'], 150000.0)

if __name__ == '__main__':
    unittest.main()
