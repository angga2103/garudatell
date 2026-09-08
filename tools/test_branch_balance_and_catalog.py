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
from app.services.tier_service import get_user_product_price
from app.services.device_service import (
    create_branch_cashier,
    activate_cashier_device,
    login_cashier_pin,
    transfer_balance_to_branch,
    withdraw_balance_from_branch,
    request_branch_deposit_via_wa,
    check_and_notify_low_balance,
    get_branch_mutations,
    now_wib
)

class TestBranchBalanceAndCatalog(unittest.TestCase):
    def setUp(self):
        self.wa_patcher = patch('app.services.device_service.kirim_wa', return_value=True)
        self.mock_kirim_wa = self.wa_patcher.start()

        self.digi_patcher = patch('app.services.digiflazz.create_transaction', return_value=(True, {'status': 'SUCCESS', 'sn': 'SN-TEST-8888'}, 'Sukses'))
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
        self.owner = User(
            name="Bos Hendra VIP",
            phone="081299990000",
            role="vip",
            role_expires_at=now_wib() + timedelta(days=90),
            balance=500000.0,
            is_device_lock_enabled=True
        )
        self.owner.set_password("boshen123")
        db.session.add(self.owner)
        db.session.commit()

        # Setup Branch Device
        ok, dev, act_url, _ = create_branch_cashier(
            user=self.owner,
            branch_name="Cabang Grand Mall",
            pin="1234",
            daily_limit=0.0
        )
        self.device = dev
        self.test_uuid = "gt_device_grand_mall"
        activate_cashier_device(dev.activation_token, self.test_uuid)

        # Setup Products Across Categories
        products = [
            Product(sku_code="PULSA5", name="Pulsa Telkomsel 5K", category="PULSA", brand="TELKOMSEL", base_price=5100, sell_price=5500, is_active=True),
            Product(sku_code="DATA10", name="Data Telkomsel 10GB", category="DATA", brand="TELKOMSEL", base_price=25000, sell_price=27000, is_active=True),
            Product(sku_code="PLN20", name="Token PLN 20.000", category="PLN", brand="PLN", base_price=20500, sell_price=21500, is_active=True),
            Product(sku_code="DANA50", name="Saldo DANA 50K", category="EMONEY", brand="DANA", base_price=50500, sell_price=52000, is_active=True),
            Product(sku_code="OVO25", name="Saldo OVO 25K", category="EMONEY", brand="OVO", base_price=25500, sell_price=27000, is_active=True),
            Product(sku_code="FF70", name="Free Fire 70 Diamonds", category="GAMES", brand="FREE FIRE", base_price=9500, sell_price=10500, is_active=True),
            Product(sku_code="ML86", name="Mobile Legends 86 Diamonds", category="GAMES", brand="MOBILE LEGENDS", base_price=19000, sell_price=21000, is_active=True),
            Product(sku_code="NETFLIX", name="Voucher Netflix Standard", category="TV", brand="NETFLIX", base_price=120000, sell_price=125000, is_active=True),
        ]
        db.session.add_all(products)
        db.session.commit()

    def tearDown(self):
        self.wa_patcher.stop()
        self.digi_patcher.stop()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_01_owner_cannot_transfer_exceeding_balance(self):
        """Owner tidak bisa mengirim saldo ke cabang melebihi saldo miliknya sendiri."""
        # Saldo owner = 500.000. Coba kirim 600.000
        ok, msg = transfer_balance_to_branch(self.owner.id, self.device.id, 600000.0)
        self.assertFalse(ok)
        self.assertIn("tidak mencukupi", msg.lower())

        # Pastikan saldo owner dan cabang tidak berubah
        owner = db.session.get(User, self.owner.id)
        dev = db.session.get(TrustedDevice, self.device.id)
        self.assertEqual(owner.balance, 500000.0)
        self.assertEqual(dev.branch_balance, 0.0)

    def test_02_owner_transfer_balance_success_and_logs_shift(self):
        """Owner berhasil mengirim saldo ke cabang, memotong saldo owner & mencatat shift penerima di mutasi."""
        ok, msg = transfer_balance_to_branch(
            owner_id=self.owner.id,
            device_id=self.device.id,
            amount=200000.0,
            shift_name="Andi (Shift Pagi)"
        )
        self.assertTrue(ok)

        owner = db.session.get(User, self.owner.id)
        dev = db.session.get(TrustedDevice, self.device.id)
        self.assertEqual(owner.balance, 300000.0)
        self.assertEqual(dev.branch_balance, 200000.0)

        # Cek mutasi cabang tercatat
        mutations = get_branch_mutations(dev.id)
        self.assertEqual(len(mutations), 1)
        m = mutations[0]
        self.assertEqual(m.type, 'TOPUP_FROM_OWNER')
        self.assertEqual(m.amount, 200000.0)
        self.assertEqual(m.balance_before, 0.0)
        self.assertEqual(m.balance_after, 200000.0)
        self.assertEqual(m.shift_name, "Andi (Shift Pagi)")

    def test_03_owner_withdraw_balance_from_branch(self):
        """Owner menarik sebagian saldo cabang untuk dipindahkan atau dipakai sendiri."""
        # Beri saldo cabang awal 250.000
        transfer_balance_to_branch(self.owner.id, self.device.id, 250000.0)

        # 1. Coba tarik melebihi saldo cabang -> gagal
        ok_fail, msg_fail = withdraw_balance_from_branch(self.owner.id, self.device.id, 300000.0)
        self.assertFalse(ok_fail)
        self.assertIn("hanya tersisa", msg_fail.lower())

        # 2. Tarik 150.000 -> sukses
        ok_win, msg_win = withdraw_balance_from_branch(self.owner.id, self.device.id, 150000.0)
        self.assertTrue(ok_win)

        owner = db.session.get(User, self.owner.id)
        dev = db.session.get(TrustedDevice, self.device.id)
        self.assertEqual(owner.balance, 400000.0) # 500k - 250k + 150k = 400k
        self.assertEqual(dev.branch_balance, 100000.0)

        # Cek mutasi penarikan
        muts = get_branch_mutations(dev.id)
        self.assertEqual(muts[0].type, 'WITHDRAW_TO_OWNER')
        self.assertEqual(muts[0].amount, 150000.0)
        self.assertEqual(muts[0].balance_after, 100000.0)

    def test_04_cashier_checkout_deducts_branch_balance_and_records_mutation(self):
        """Kasir checkout memotong saldo cabang (bukan saldo owner) dan mencatat mutasi SALE."""
        # Transfer saldo ke cabang 100.000
        transfer_balance_to_branch(self.owner.id, self.device.id, 100000.0, shift_name="Dewi (Shift Sore)")

        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234', 'shift_name': 'Dewi (Shift Sore)'})

        prod = Product.query.filter_by(sku_code='PULSA5').first()
        expected_deduction = get_user_product_price(self.owner, prod)

        # Checkout Pulsa 5K
        res = self.client.post('/kasir/checkout', json={
            'sku_code': 'PULSA5',
            'target_number': '08123456789'
        })
        self.assertEqual(res.status_code, 200)

        dev = db.session.get(TrustedDevice, self.device.id)
        self.assertEqual(dev.branch_balance, 100000.0 - expected_deduction)

        # Mutasi terbaru harus SALE
        muts = get_branch_mutations(dev.id)
        self.assertEqual(muts[0].type, 'SALE')
        self.assertEqual(muts[0].amount, expected_deduction)
        self.assertEqual(muts[0].shift_name, 'Dewi (Shift Sore)')

    def test_05_cashier_checkout_insufficient_branch_balance(self):
        """Kasir ditolak transaksi jika saldo cabang tidak cukup meskipun saldo utama owner ada."""
        # Saldo cabang = 0.0, saldo owner = 500.000
        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234'})

        res = self.client.post('/kasir/checkout', json={
            'sku_code': 'PULSA5',
            'target_number': '08123456789'
        })
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertIn("saldo kasir cabang tidak mencukupi", data['message'].lower())

    def test_06_low_balance_auto_alert(self):
        """Ketika saldo cabang menipis (< Rp 100.000), notifikasi otomatis dikirim ke WA Owner."""
        self.device.branch_balance = 50000.0
        db.session.commit()

        sent = check_and_notify_low_balance(self.device, shift_name="Budi (Pagi)", base_url="http://localhost")
        self.assertTrue(sent)
        self.mock_kirim_wa.assert_called()
        args, kwargs = self.mock_kirim_wa.call_args
        wa_message = args[1]
        self.assertIn("PERINGATAN SALDO KASIR MENIPIS", wa_message.upper())
        self.assertIn("Cabang Grand Mall", wa_message)

    def test_07_request_deposit_from_cashier_to_owner_wa(self):
        """Kasir meminta deposit tambahan langsung mengirim pesan interaktif ke WhatsApp Owner."""
        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234', 'shift_name': 'Agus (Malam)'})

        res = self.client.post('/kasir/request_deposit', json={
            'amount': 200000.0,
            'note': 'Pelanggan ramai beli token PLN malam ini bos'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertIn("berhasil dikirim", data['message'].lower())

        # Pastikan WA terkirim ke nomor Owner
        args, _ = self.mock_kirim_wa.call_args
        phone, wa_msg = args[0], args[1]
        self.assertEqual(phone, self.owner.phone)
        self.assertIn("PERMINTAAN SALDO KASIR TOKO", wa_msg.upper())
        self.assertIn("200,000", wa_msg)
        self.assertIn("Agus (Malam)", wa_msg)

    def test_08_multi_category_and_brand_catalog(self):
        """Katalog produk kasir mendukung filter seluruh kategori & brand pills."""
        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234'})

        # 1. Kategori EMONEY -> dapat DANA50 & OVO25
        res_emoney = self.client.get('/kasir/products?category=EMONEY')
        self.assertEqual(res_emoney.status_code, 200)
        items_emoney = res_emoney.get_json()['products']
        self.assertEqual(len(items_emoney), 2)

        # 2. Filter Brand DANA
        res_dana = self.client.get('/kasir/products?category=EMONEY&brand=DANA')
        items_dana = res_dana.get_json()['products']
        self.assertEqual(len(items_dana), 1)
        self.assertEqual(items_dana[0]['sku_code'], 'DANA50')

        # 3. Live Search 'netflix'
        res_search = self.client.get('/kasir/products?q=netflix')
        items_search = res_search.get_json()['products']
        self.assertEqual(len(items_search), 1)
        self.assertEqual(items_search[0]['sku_code'], 'NETFLIX')

        # 4. Get Brands per kategori GAMES
        res_brands = self.client.get('/kasir/brands?category=GAMES')
        brands = res_brands.get_json()['brands']
        self.assertIn('FREE FIRE', brands)
        self.assertIn('MOBILE LEGENDS', brands)

    def test_09_mutations_and_history_endpoints(self):
        """Kasir dapat melihat riwayat transaksi dan log mutasi saldo."""
        transfer_balance_to_branch(self.owner.id, self.device.id, 100000.0, shift_name="Budi")

        self.client.set_cookie('gt_device_token', self.test_uuid, domain='localhost')
        self.client.post('/kasir/login_pin', json={'pin': '1234', 'shift_name': 'Budi'})

        # Cek endpoint /kasir/mutations
        res_mut = self.client.get('/kasir/mutations')
        self.assertEqual(res_mut.status_code, 200)
        data_mut = res_mut.get_json()
        self.assertEqual(data_mut['status'], 'success')
        self.assertEqual(len(data_mut['mutations']), 1)
        self.assertEqual(data_mut['mutations'][0]['shift_name'], 'Budi')

        # Cek endpoint /kasir/history
        res_hist = self.client.get('/kasir/history')
        self.assertEqual(res_hist.status_code, 200)
        data_hist = res_hist.get_json()
        self.assertEqual(data_hist['status'], 'success')

if __name__ == '__main__':
    unittest.main()
