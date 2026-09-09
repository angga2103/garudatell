
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

import unittest
from unittest.mock import patch, MagicMock
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.trusted_device import TrustedDevice
from app.models.branch_mutation import BranchMutation
from app.models.inquiry import PostpaidInquiry
from datetime import datetime, timedelta

class TestSecurityAuditFixes(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.user = User.query.filter_by(phone='081288880001').first()
        if not self.user:
            self.user = User(
                name='Security Test User',
                phone='081288880001',
                balance=500000.0,
                role='vip',
                is_active=True
            )
            self.user.set_password('Password123!')
            db.session.add(self.user)
            db.session.commit()
        else:
            self.user.balance = 500000.0
            self.user.role = 'vip'
            db.session.commit()

        self.device = TrustedDevice.query.filter_by(user_id=self.user.id, device_name='Cabang Utama').first()
        if not self.device:
            self.device = TrustedDevice(
                user_id=self.user.id,
                device_name='Cabang Utama',
                device_uuid='dev_sec_test_uuid_12345',
                status='approved',
                branch_balance=50000.0
            )
            db.session.add(self.device)
            db.session.commit()
        else:
            self.device.branch_balance = 50000.0
            db.session.commit()

        self.pln_prod = Product.query.filter_by(sku_code='post685486').first()
        if not self.pln_prod:
            self.pln_prod = Product(
                sku_code='post685486',
                name='Pln Pascabayar',
                category='Pascabayar',
                brand='PLN PASCABAYAR',
                base_price=4000.0,
                sell_price=4200.0,
                is_active=True
            )
            db.session.add(self.pln_prod)
            db.session.commit()

    def tearDown(self):
        try:
            PostpaidInquiry.query.filter_by(user_id=self.user.id).delete()
            BranchMutation.query.filter_by(user_id=self.user.id).delete()
            Transaction.query.filter_by(user_id=self.user.id).delete()
            TrustedDevice.query.filter_by(user_id=self.user.id).delete()
            User.query.filter_by(id=self.user.id).delete()
            db.session.commit()
        except Exception:
            db.session.rollback()
        self.app_context.pop()

    def login_client(self):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = str(self.user.id)
            sess['_fresh'] = True

    @patch('app.services.digiflazz.is_pln_cutoff_time', return_value=False)
    @patch('app.services.digiflazz.pay_pasca')
    def test_01_anti_price_tampering_pasca_bill(self, mock_pay, mock_cutoff):
        self.login_client()
        mock_pay.return_value = (True, {'rc': '00', 'status': 'Sukses', 'sn': 'PLN-TEST-SN'}, 'Sukses')

        ref_id = 'GT-PASCA-SEC-001'
        inq = PostpaidInquiry(
            ref_id=ref_id,
            user_id=self.user.id,
            sku_code='post685486',
            customer_no='530000000001',
            customer_name='BAPAK BUDI',
            tagihan_pokok=245800.0,
            denda=0.0,
            admin_fee=4200.0,
            total_amount=250000.0,
            expires_at=datetime.utcnow() + timedelta(minutes=30)
        )
        db.session.add(inq)
        db.session.commit()

        initial_balance = self.user.balance

        res = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'saldo',
            'inquiry_ref_id': ref_id,
            'amount': 1000.0
        })

        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'success')

        user_after = User.query.get(self.user.id)
        self.assertEqual(user_after.balance, initial_balance - 250000.0)

        inq_after = PostpaidInquiry.query.filter_by(ref_id=ref_id).first()
        self.assertTrue(inq_after.is_paid)

        res_repeat = self.client.post('/trx/checkout', json={
            'sku_code': 'post685486',
            'target_number': '530000000001',
            'payment_method': 'saldo',
            'inquiry_ref_id': ref_id,
            'amount': 250000.0
        })
        self.assertEqual(res_repeat.status_code, 400)
        self.assertIn('sudah berhasil dibayar', res_repeat.get_json()['message'])

    def test_02_paymentkita_missing_signature_rejected(self):
        trx = Transaction(
            ref_id='DEP-PK-SEC-01',
            user_id=self.user.id,
            sku_code='DEPOSIT_SALDO',
            product_name='Deposit Saldo',
            target_number='Akun Saya',
            amount=50000.0,
            payment_method='QRIS',
            payment_status='UNPAID',
            status='UNPAID',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        payload = {
            'ref_id': 'DEP-PK-SEC-01',
            'amount': '50000',
            'status': 'paid'
        }
        res = self.client.post('/callback/paymentkita', json=payload)
        self.assertEqual(res.status_code, 403)

        trx_check = Transaction.query.filter_by(ref_id='DEP-PK-SEC-01').first()
        self.assertEqual(trx_check.payment_status, 'UNPAID')

    @patch('app.services.pakasir_service.PakasirService.check_transaction')
    def test_03_pakasir_webhook_server_verification(self, mock_chk):
        trx = Transaction(
            ref_id='DEP-PA-SEC-01',
            user_id=self.user.id,
            sku_code='DEPOSIT_SALDO',
            product_name='Deposit Saldo',
            target_number='Akun Saya',
            amount=100000.0,
            payment_method='QRIS',
            payment_status='UNPAID',
            status='UNPAID',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        proj_slug = os.getenv('PAKASIR_PROJECT', 'Ansor')
        mock_chk.return_value = {'status': 'pending'}
        res_fake = self.client.post('/callback/pakasir', json={
            'project': proj_slug,
            'order_id': 'DEP-PA-SEC-01',
            'amount': 100000,
            'status': 'completed'
        })
        self.assertEqual(res_fake.status_code, 403)

        mock_chk.return_value = {'status': 'completed'}
        bal_before = self.user.balance
        res_ok = self.client.post('/callback/pakasir', json={
            'project': proj_slug,
            'order_id': 'DEP-PA-SEC-01',
            'amount': 100000,
            'status': 'completed'
        })
        self.assertEqual(res_ok.status_code, 200)

        user_after = User.query.get(self.user.id)
        self.assertEqual(user_after.balance, bal_before + 100000.0)

    @patch('app.services.digiflazz.check_transaction_status')
    def test_04_cashier_branch_balance_refund_on_webhook(self, mock_chk):
        mock_chk.return_value = (True, {
            'status': 'Gagal',
            'rc': '41',
            'sn': 'Gagal dari server',
            'message': 'Gagal'
        }, 'Gagal')

        trx = Transaction(
            ref_id='KASIR-SEC-WH-01',
            user_id=self.user.id,
            device_id=self.device.id,
            device_name=self.device.device_name,
            sku_code='danacek',
            product_name='Cek DANA',
            target_number='081775700114',
            amount=20000.0,
            payment_method='SALDO',
            payment_status='PAID',
            status='PROCESSING',
            is_prepaid=True
        )
        db.session.add(trx)
        db.session.commit()

        dev_bal_before = self.device.branch_balance
        user_bal_before = self.user.balance

        payload = {
            'data': {
                'ref_id': 'KASIR-SEC-WH-01',
                'status': 'Gagal',
                'rc': '41',
                'message': 'Produk gangguan'
            }
        }
        res = self.client.post('/callback/digiflazz', json=payload)
        self.assertEqual(res.status_code, 200)

        dev_after = TrustedDevice.query.get(self.device.id)
        self.assertEqual(dev_after.branch_balance, dev_bal_before + 20000.0)

        user_after = User.query.get(self.user.id)
        self.assertEqual(user_after.balance, user_bal_before)

        mut = BranchMutation.query.filter_by(device_id=self.device.id, type='REFUND').first()
        self.assertIsNotNone(mut)
        self.assertEqual(mut.amount, 20000.0)

if __name__ == '__main__':
    unittest.main()
