import sys
import os
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.support_ticket import SupportTicket
from app.models.commission import CommissionLog
from app.models.trusted_device import TrustedDevice
from app.models.branch_mutation import BranchMutation
from app.models.device_session_log import DeviceSessionLog
from app.models.notification import Notification, NotificationRead
from app.models.point_log import PointLog
from app.models.merchant import MerchantApiKey

class AdminUserManagementTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        self.ctx.pop()

    def test_create_and_delete_user(self):
        with self.client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_username'] = 'AdminTest'

        # 1. Test create user
        test_phone = '089912345678'
        # Clean up if already exists
        existing = User.query.filter_by(phone=test_phone).first()
        if existing:
            # Delete via delete route
            self.client.post(f'/admin/users/{existing.id}/delete')

        res = self.client.post('/admin/users/create', data={
            'name': 'Toko Uji Coba Admin',
            'phone': '6289912345678', # Test 62 normalization
            'email': 'ujicoba@example.com',
            'password': 'PasswordKuat123',
            'pin': '8899',
            'balance': '50000',
            'role': 'reseller',
            'role_days': '45',
            'upline_input': ''
        }, follow_redirects=True)

        self.assertEqual(res.status_code, 200)

        # Verify user in database
        u = User.query.filter_by(phone=test_phone).first()
        self.assertIsNotNone(u, "User should be created")
        self.assertEqual(u.name, 'Toko Uji Coba Admin')
        self.assertEqual(u.phone, test_phone)
        self.assertEqual(u.email, 'ujicoba@example.com')
        self.assertEqual(u.balance, 50000.0)
        self.assertEqual(u.role, 'reseller')
        self.assertTrue(u.check_password('PasswordKuat123'))
        self.assertTrue(u.check_pin('8899'))
        self.assertIsNotNone(u.referral_code)
        self.assertIsNotNone(u.role_expires_at)

        # Check transaction for initial balance
        trx = Transaction.query.filter_by(user_id=u.id, sku_code='DEPOSIT_MANUAL').first()
        self.assertIsNotNone(trx)
        self.assertEqual(trx.amount, 50000.0)

        # 2. Add some relations to test cascade / safe deletion
        dev = TrustedDevice(user_id=u.id, device_uuid='uuid-test-123', device_name='HP Kasir Test', status='approved')
        db.session.add(dev)
        db.session.commit()

        bmut = BranchMutation(device_id=dev.id, user_id=u.id, type='TOPUP_FROM_OWNER', amount=10000.0)
        db.session.add(bmut)

        dlog = DeviceSessionLog(user_id=u.id, phone=u.phone, event_type='LOGIN_SUCCESS')
        db.session.add(dlog)

        ticket = SupportTicket(ticket_number=SupportTicket.generate_ticket_number(), user_id=u.id, user_name=u.name, user_phone=u.phone, transaction_id=trx.id, message='Test tiket')
        db.session.add(ticket)

        plog = PointLog(user_id=u.id, type='EARNED', points=10)
        db.session.add(plog)

        notif = Notification(title='Promo', message='Halo', target_user_id=u.id)
        db.session.add(notif)
        db.session.commit()

        nread = NotificationRead(user_id=u.id, notification_id=notif.id)
        db.session.add(nread)
        db.session.commit()

        # 3. Test delete user via AJAX JSON
        del_res = self.client.post(f'/admin/users/{u.id}/delete', headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(del_res.status_code, 200)
        del_data = del_res.get_json()
        self.assertEqual(del_data['status'], 'success')

        # Verify user is completely removed
        u_deleted = User.query.filter_by(phone=test_phone).first()
        self.assertIsNone(u_deleted, "User should be deleted from DB")

        # Verify related records are cleaned up without FK errors
        self.assertEqual(TrustedDevice.query.filter_by(user_id=u.id).count(), 0)
        self.assertEqual(BranchMutation.query.filter_by(user_id=u.id).count(), 0)
        self.assertEqual(Transaction.query.filter_by(user_id=u.id).count(), 0)
        self.assertEqual(DeviceSessionLog.query.filter_by(user_id=u.id).count(), 0)
        self.assertEqual(PointLog.query.filter_by(user_id=u.id).count(), 0)
        self.assertEqual(Notification.query.filter_by(target_user_id=u.id).count(), 0)
        self.assertEqual(NotificationRead.query.filter_by(user_id=u.id).count(), 0)
        self.assertEqual(SupportTicket.query.filter_by(user_id=u.id).count(), 0)

if __name__ == '__main__':
    unittest.main()
