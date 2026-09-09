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
from app.models.inquiry import PostpaidInquiry
from app.services.device_service import (
    create_branch_cashier,
    activate_cashier_device,
    login_cashier_pin,
    now_wib
)

class TestPascabayarPPOB(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()

        self.ctx = self.app.app_context()
        self.ctx.push()

        # 1. VIP Owner & Regular User
        self.vip_owner = User.query.filter_by(phone="081122334400").first()
        if not self.vip_owner:
            self.vip_owner = User(
                name="Owner Toko VIP",
                phone="081122334400",
                role="vip",
                role_expires_at=now_wib() + timedelta(days=60),
                balance=1000000.0,
                is_active=True
            )
            self.vip_owner.set_password("ownersecret123")
            db.session.add(self.vip_owner)
        else:
            self.vip_owner.role = "vip"
            self.vip_owner.role_expires_at = now_wib() + timedelta(days=60)
            self.vip_owner.balance = 1000000.0
            self.vip_owner.is_active = True

        self.member_user = User.query.filter_by(phone="082233445566").first()
        if not self.member_user:
            self.member_user = User(
                name="Pelanggan Member",
                phone="082233445566",
                role="user",
                balance=250000.0,
                is_active=True
            )
            self.member_user.set_password("membersecret123")
            db.session.add(self.member_user)
        else:
            self.member_user.balance = 250000.0
            self.member_user.is_active = True

        # 2. Produk Pascabayar (PDAM, BPJS, PBB, PLN Pasca)
        def get_or_create_prod(sku, name, cat, brand, bp, sp):
            p = Product.query.filter_by(sku_code=sku).first()
            if not p:
                p = Product(
                    sku_code=sku,
                    name=name,
                    category=cat,
                    brand=brand,
                    base_price=bp,
                    sell_price=sp,
                    is_active=True
                )
                db.session.add(p)
            else:
                p.is_active = True
                p.category = cat
                p.brand = brand
                p.sell_price = sp
            return p

        self.pdam_prod = get_or_create_prod("post685472", "PDAM Kab Kediri", "Pascabayar", "PDAM", 2000.0, 2500.0)
        self.bpjs_prod = get_or_create_prod("post685476", "BPJS Kesehatan", "Pascabayar", "BPJS KESEHATAN", 2000.0, 2500.0)
        self.pbb_prod = get_or_create_prod("post685474", "PBB Kab Kediri", "Pascabayar", "PBB", 2500.0, 3000.0)
        self.pln_pasca = get_or_create_prod("post685486", "PLN Pascabayar", "Pascabayar", "PLN PASCABAYAR", 3000.0, 3500.0)
        db.session.commit()

        # 3. Setup Kasir Device
        self.cashier_device = TrustedDevice.query.filter_by(device_name="Cabang Kasir Pusat Pasca").first()
        if not self.cashier_device:
            ok, dev, act_url, msg = create_branch_cashier(
                user=self.vip_owner,
                branch_name="Cabang Kasir Pusat Pasca",
                pin="123456",
                daily_limit=5000000.0,
                base_url="http://localhost"
            )
            self.cashier_device = dev
            self.device_uuid = "pos_uuid_test_pasca"
            activate_cashier_device(dev.activation_token, self.device_uuid)
        else:
            self.device_uuid = self.cashier_device.device_uuid or "pos_uuid_test_pasca"
            self.cashier_device.device_uuid = self.device_uuid
            self.cashier_device.status = 'approved'
            self.cashier_device.set_pin("123456")
        
        self.cashier_device.branch_balance = 500000.0
        db.session.commit()

    def tearDown(self):
        try:
            Transaction.query.filter(Transaction.ref_id.like('%PASCA%')).delete()
            PostpaidInquiry.query.filter(PostpaidInquiry.ref_id.like('%PASCA%')).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
        self.ctx.pop()

    def login_member(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.member_user.id)
            sess['_fresh'] = True

    def login_cashier_session(self):
        self.client.set_cookie('gt_device_token', self.device_uuid)
        res = self.client.post('/kasir/login_pin', json={'pin': '123456'})
        self.assertEqual(res.status_code, 200)

    # ==================== TEST USER WEB ====================
    def test_01_user_kategori_pascabayar_pages(self):
        for path in ['/kategori/pascabayar', '/kategori/pdam', '/kategori/bpjs', '/kategori/pbb', '/kategori/ppob']:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, f"Gagal membuka route {path}")
            html = res.data.decode('utf-8')
            self.assertIn("Tagihan", html)
            self.assertIn("PDAM", html)
            self.assertIn("BPJS", html)

    @patch('app.services.digiflazz.inquiry_pasca')
    def test_02_user_inquiry_bill_pdam(self, mock_inq):
        self.login_member()
        mock_inq.return_value = (
            True,
            {
                'rc': '00',
                'status': 'Sukses',
                'customer_name': 'BUDI SANTOSO',
                'customer_no': '0102030405',
                'price': 45000,
                'admin': 2000,
                'desc': {
                    'tarif': 'R1',
                    'daya': '900',
                    'lembar_tagihan': '1',
                    'detail': [
                        {'periode': '2026-08', 'nilai_tagihan': 43000, 'denda': 0}
                    ]
                }
            },
            "Inquiry sukses"
        )

        res = self.client.post('/trx/inquiry_bill', json={
            'sku_code': 'post685472',
            'customer_no': '0102030405'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['customer_name'], 'BUDI SANTOSO')
        self.assertEqual(data['tagihan_pokok'], 43000.0)
        self.assertEqual(data['admin_fee'], 2500.0)
        self.assertEqual(data['total_bayar'], 45500.0)
        self.assertTrue(data['ref_id'].startswith('GT-PASCA-'))

        inq_db = PostpaidInquiry.query.filter_by(ref_id=data['ref_id']).first()
        self.assertIsNotNone(inq_db)
        self.assertEqual(inq_db.total_amount, 45500.0)

    # ==================== TEST KASIR POS ====================
    def test_03_kasir_catalog_pascabayar(self):
        self.login_cashier_session()

        res_p = self.client.get('/kasir/products?category=PASCABAYAR')
        self.assertEqual(res_p.status_code, 200)
        data_p = res_p.get_json()
        self.assertEqual(data_p['status'], 'success')
        self.assertGreaterEqual(data_p['count'], 4)
        skus = [p['sku_code'] for p in data_p['products']]
        self.assertIn('post685472', skus)
        self.assertIn('post685476', skus)
        for p in data_p['products']:
            self.assertTrue(p['is_pasca'])

        res_b = self.client.get('/kasir/brands?category=PASCABAYAR')
        self.assertEqual(res_b.status_code, 200)
        data_b = res_b.get_json()
        self.assertIn('PDAM', data_b['brands'])
        self.assertIn('BPJS KESEHATAN', data_b['brands'])
        self.assertIn('PBB', data_b['brands'])

    @patch('app.services.digiflazz.inquiry_pasca')
    def test_04_kasir_inquiry_bill(self, mock_inq):
        self.login_cashier_session()
        mock_inq.return_value = (
            True,
            {
                'rc': '00',
                'status': 'Sukses',
                'customer_name': 'KASIR TEST PELANGGAN',
                'customer_no': '1234567890',
                'price': 75000,
                'admin': 2000,
                'desc': {
                    'tarif': 'R2',
                    'daya': '2200',
                    'lembar_tagihan': '1',
                    'detail': [
                        {'periode': '2026-08', 'nilai_tagihan': 73000, 'denda': 2000}
                    ]
                }
            },
            "Inquiry sukses"
        )

        res = self.client.post('/kasir/inquiry_bill', json={
            'sku_code': 'post685476',
            'customer_no': '1234567890'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['customer_name'], 'KASIR TEST PELANGGAN')
        self.assertEqual(data['denda'], 2000.0)
        self.assertEqual(data['admin_fee'], 2500.0)
        self.assertEqual(data['total_bayar'], 73000.0 + 2000.0 + 2500.0)
        self.assertTrue(data['ref_id'].startswith('KASIR-PASCA-'))

    @patch('app.services.digiflazz.pay_pasca')
    @patch('app.services.digiflazz.inquiry_pasca')
    def test_05_kasir_checkout_pascabayar_success(self, mock_inq, mock_pay):
        self.login_cashier_session()

        mock_inq.return_value = (
            True,
            {
                'rc': '00',
                'status': 'Sukses',
                'customer_name': 'WARGA KEDIRI',
                'customer_no': '9988776655',
                'price': 50000,
                'admin': 2000,
                'desc': {
                    'detail': [{'periode': '2026-08', 'nilai_tagihan': 48000, 'denda': 0}]
                }
            },
            "Inquiry sukses"
        )
        res_inq = self.client.post('/kasir/inquiry_bill', json={
            'sku_code': 'post685472',
            'customer_no': '9988776655'
        })
        inq_data = res_inq.get_json()
        ref_id = inq_data['ref_id']
        expected_total = inq_data['total_bayar']

        mock_pay.return_value = (
            True,
            {
                'rc': '00',
                'status': 'Sukses',
                'sn': 'PDAM-TRX-SUKSES-998811'
            },
            "Pembayaran tagihan pascabayar sukses"
        )

        bal_awal = self.cashier_device.branch_balance
        res_pay = self.client.post('/kasir/checkout', json={
            'sku_code': 'post685472',
            'target_number': '9988776655',
            'inquiry_ref_id': ref_id
        })
        self.assertEqual(res_pay.status_code, 200)
        pay_data = res_pay.get_json()
        self.assertEqual(pay_data['status'], 'success')
        self.assertEqual(pay_data['ref_id'], ref_id)

        db.session.refresh(self.cashier_device)
        self.assertEqual(self.cashier_device.branch_balance, bal_awal - expected_total)

        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.status, 'SUCCESS')
        self.assertEqual(trx.price, expected_total)
        self.assertEqual(trx.sn, 'PDAM-TRX-SUKSES-998811')

        mut = BranchMutation.query.filter_by(device_id=self.cashier_device.id, type='SALE').first()
        self.assertIsNotNone(mut)
        self.assertEqual(mut.amount, expected_total)

        res_pay_again = self.client.post('/kasir/checkout', json={
            'sku_code': 'post685472',
            'target_number': '9988776655',
            'inquiry_ref_id': ref_id
        })
        self.assertEqual(res_pay_again.status_code, 400)
        self.assertIn("sudah berhasil dibayar", res_pay_again.get_json()['message'])

    @patch('app.services.digiflazz.pay_pasca')
    @patch('app.services.digiflazz.inquiry_pasca')
    def test_06_kasir_checkout_pascabayar_failed_refunds_branch_balance(self, mock_inq, mock_pay):
        self.login_cashier_session()

        mock_inq.return_value = (
            True,
            {
                'rc': '00',
                'status': 'Sukses',
                'customer_name': 'WARGA GAGAL',
                'customer_no': '8877665544',
                'price': 30000,
                'admin': 2000,
                'desc': {
                    'detail': [{'periode': '2026-08', 'nilai_tagihan': 28000, 'denda': 0}]
                }
            },
            "Inquiry sukses"
        )
        res_inq = self.client.post('/kasir/inquiry_bill', json={
            'sku_code': 'post685472',
            'customer_no': '8877665544'
        })
        inq_data = res_inq.get_json()
        ref_id = inq_data['ref_id']
        tagihan_total = inq_data['total_bayar']

        mock_pay.return_value = (
            False,
            {
                'rc': '42',
                'status': 'Gagal',
                'message': 'TAGIHAN SUDAH TERBAYAR DI TEMPAT LAIN'
            },
            "Pembayaran tagihan gagal"
        )

        bal_awal = self.cashier_device.branch_balance
        res_pay = self.client.post('/kasir/checkout', json={
            'sku_code': 'post685472',
            'target_number': '8877665544',
            'inquiry_ref_id': ref_id
        })
        self.assertEqual(res_pay.status_code, 200)

        db.session.refresh(self.cashier_device)
        self.assertEqual(self.cashier_device.branch_balance, bal_awal)

        mut_ref = BranchMutation.query.filter_by(device_id=self.cashier_device.id, type='REFUND').first()
        self.assertIsNotNone(mut_ref)
        self.assertEqual(mut_ref.amount, tagihan_total)
        self.assertIn("TAGIHAN SUDAH TERBAYAR", mut_ref.description)

        trx = Transaction.query.filter_by(ref_id=ref_id).first()
        self.assertEqual(trx.status, 'FAILED')

if __name__ == '__main__':
    unittest.main()
