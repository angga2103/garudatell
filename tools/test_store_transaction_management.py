import os
import sys
import unittest

# Ensure root dir is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.services.balance_service import adjust_user_balance_manual
from app.services.mutasi_service import get_user_mutations
from app.services.telegram_service import (
    get_admin_inline_keyboard,
    render_stores_keyboard
)

class TestStoreTransactionManagement(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        # Create test stores/users
        self.store1 = User(
            name="Toko Mooncherry Malang",
            phone="081234567801",
            balance=100000.0,
            role="reseller",
            is_active=True
        )
        self.store1.set_password("pass123")

        self.store2 = User(
            name="Toko Surya Abadi Surabaya",
            phone="081234567802",
            balance=50000.0,
            role="user",
            is_active=True
        )
        self.store2.set_password("pass123")

        db.session.add_all([self.store1, self.store2])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_adjust_balance_add(self):
        """Test penambahan saldo manual oleh admin."""
        ok, new_bal, msg, trx = adjust_user_balance_manual(
            user_id=self.store1.id,
            amount=50000.0,
            action='add',
            note='Topup kasir toko via admin',
            admin_source='Web Admin'
        )
        self.assertTrue(ok)
        self.assertEqual(new_bal, 150000.0)
        self.assertIsNotNone(trx)
        self.assertEqual(trx.sku_code, 'DEPOSIT_MANUAL')
        self.assertEqual(trx.status, 'SUCCESS')
        self.assertEqual(trx.payment_status, 'PAID')
        self.assertIn("Ditambahkan oleh Admin (Web Admin)", trx.sn)
        self.assertIn("Topup kasir toko via admin", trx.sn)

        # Cek database
        user = User.query.get(self.store1.id)
        self.assertEqual(user.balance, 150000.0)

        # Cek di mutasi akun user
        mutations_data = get_user_mutations(user.id)
        mutations = mutations_data['mutations']
        self.assertGreaterEqual(len(mutations), 1)
        m = mutations[0]
        self.assertEqual(m['direction'], '+')
        self.assertEqual(m['amount'], 50000.0)
        self.assertIn("Topup Saldo oleh Admin", m['title'])

    def test_adjust_balance_deduct(self):
        """Test pemotongan/penyesuaian saldo manual oleh admin."""
        ok, new_bal, msg, trx = adjust_user_balance_manual(
            user_id=self.store1.id,
            amount=30000.0,
            action='deduct',
            note='Koreksi selisih deposit',
            admin_source='Bot Telegram'
        )
        self.assertTrue(ok)
        self.assertEqual(new_bal, 70000.0)
        self.assertIsNotNone(trx)
        self.assertEqual(trx.sku_code, 'MANUAL_DEDUCTION')
        self.assertEqual(trx.status, 'SUCCESS')
        self.assertIn("Koreksi selisih deposit", trx.sn)

        # Cek database
        user = User.query.get(self.store1.id)
        self.assertEqual(user.balance, 70000.0)

        # Cek di mutasi akun user
        mutations_data = get_user_mutations(user.id)
        mutations = mutations_data['mutations']
        self.assertGreaterEqual(len(mutations), 1)
        m = mutations[0]
        self.assertEqual(m['direction'], '-')
        self.assertEqual(m['amount'], 30000.0)
        self.assertEqual(m['title'], 'Penyesuaian Saldo oleh Admin')

    def test_telegram_keyboard_and_store_list(self):
        """Test tombol bot admin Telegram dan render daftar toko."""
        # Menu utama
        admin_kb = get_admin_inline_keyboard()
        buttons = [btn['text'] for row in admin_kb['inline_keyboard'] for btn in row]
        self.assertIn("🏪 Cek Toko", buttons)

        # Render list toko
        rendered = render_stores_keyboard(page=1, per_page=5)
        self.assertEqual(rendered['total_stores'], 2)
        self.assertEqual(rendered['total_pages'], 1)
        
        store_buttons = [btn['text'] for row in rendered['keyboard']['inline_keyboard'] for btn in row]
        self.assertTrue(any("Mooncherry" in b for b in store_buttons))
        self.assertTrue(any("Surya Abadi" in b for b in store_buttons))

    def test_telegram_callback_and_message_handling(self):
        """Test eksekusi callback dan command telegram untuk toko dan saldo."""
        from unittest.mock import patch
        from app.services.telegram_service import handle_admin_callback, handle_admin_message

        # Mock requests.post to avoid real HTTP calls to Telegram API
        with patch('requests.post') as mock_post:
            mock_post.return_value.json.return_value = {"ok": True}

            # 1. Callback store_view
            cb_view = {
                'id': 'cb1',
                'message': {'chat': {'id': '12345'}, 'message_id': 99},
                'data': f'store_view_{self.store1.id}'
            }
            with patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('fake_token', '12345')):
                handle_admin_callback(self.app, cb_view)
                # Verify editMessageText was called
                self.assertTrue(any('editMessageText' in str(call) for call in mock_post.call_args_list))

            # 2. Callback store_do_add
            cb_add = {
                'id': 'cb2',
                'message': {'chat': {'id': '12345'}, 'message_id': 99},
                'data': f'store_do_add_{self.store1.id}_40000'
            }
            with patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('fake_token', '12345')):
                handle_admin_callback(self.app, cb_add)
                db.session.expire_all()
                u = User.query.get(self.store1.id)
                self.assertEqual(u.balance, 140000.0)

            # 3. Message /topup command
            msg_topup = {
                'chat': {'id': '12345'},
                'text': f'/topup {self.store1.id} 10000'
            }
            with patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('fake_token', '12345')):
                handle_admin_message(self.app, msg_topup)
                db.session.expire_all()
                u = User.query.get(self.store1.id)
                self.assertEqual(u.balance, 150000.0)

            # 4. Message /potong command
            msg_potong = {
                'chat': {'id': '12345'},
                'text': f'/potong {self.store1.id} 50000'
            }
            with patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('fake_token', '12345')):
                handle_admin_message(self.app, msg_potong)
                db.session.expire_all()
                u = User.query.get(self.store1.id)
                self.assertEqual(u.balance, 100000.0)

    def test_admin_transactions_web_endpoint(self):
        """Test endpoint /admin/transactions dengan filter toko dan pencarian nama toko."""
        # Tambah beberapa transaksi untuk store1
        t1 = Transaction(
            user_id=self.store1.id,
            product_name="Telkomsel 10rb",
            sku_code="TS10",
            amount=11000.0,
            target_number="081234567890",
            payment_method="SALDO",
            payment_status="PAID",
            status="SUCCESS",
            ref_id="TRX-001"
        )
        t2 = Transaction(
            user_id=self.store1.id,
            product_name="Indosat 5rb",
            sku_code="IS5",
            amount=6000.0,
            target_number="085712345678",
            payment_method="SALDO",
            payment_status="PAID",
            status="FAILED",
            sn="Nomor tidak aktif / gangguan provider",
            ref_id="TRX-002"
        )
        t3 = Transaction(
            user_id=self.store2.id,
            product_name="PLN 20rb",
            sku_code="PLN20",
            amount=20500.0,
            target_number="12345678901",
            payment_method="QRIS",
            payment_status="PAID",
            status="SUCCESS",
            ref_id="TRX-003"
        )
        db.session.add_all([t1, t2, t3])
        db.session.commit()

        client = self.app.test_client()
        with client.session_transaction() as sess:
            sess['admin_logged_in'] = True

        # 1. Filter store_id
        res = client.get(f'/admin/transactions?store_id={self.store1.id}')
        self.assertEqual(res.status_code, 200)
        html = res.get_data(as_text=True)
        self.assertIn("Toko Mooncherry Malang", html)
        self.assertIn("TRX-001", html)
        self.assertIn("TRX-002", html)
        self.assertNotIn("TRX-003", html)

        # 2. Filter store_id + status SUCCESS
        res_succ = client.get(f'/admin/transactions?store_id={self.store1.id}&status=SUCCESS')
        self.assertEqual(res_succ.status_code, 200)
        html_succ = res_succ.get_data(as_text=True)
        self.assertIn("TRX-001", html_succ)
        self.assertNotIn("TRX-002", html_succ)

        # 3. Pencarian teks nama toko
        res_q = client.get('/admin/transactions?q=Mooncherry')
        self.assertEqual(res_q.status_code, 200)
        html_q = res_q.get_data(as_text=True)
        self.assertIn("TRX-001", html_q)
        self.assertNotIn("TRX-003", html_q)

        # 4. Web adjust balance endpoint
        res_adj = client.post('/admin/user/adjust_balance', data={
            'user_id': self.store2.id,
            'amount': '25000',
            'action': 'add',
            'note': 'Topup web admin test',
            'redirect_to': 'transactions'
        }, follow_redirects=True)
        self.assertEqual(res_adj.status_code, 200)
        u2 = User.query.get(self.store2.id)
        self.assertEqual(u2.balance, 75000.0)

if __name__ == '__main__':
    unittest.main()
