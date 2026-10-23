import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.services.balance_notification_service import (
    _build_low_balance_message_upline,
    create_upline_downline_deposit_tickets,
    check_and_notify_low_balance
)
from app.services.dana_mutasi_service import process_incoming_dana_mutation

class TestUplineDownlineTopup(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Upline user
        self.upline = User.query.filter_by(phone="08555555555").first()
        if not self.upline:
            self.upline = User(
                name="Saudi",
                phone="08555555555",
                email="saudi_upline@example.com",
                balance=500000.0,
                role="VIP",
                is_active=True
            )
            self.upline.set_password("pass123")
            db.session.add(self.upline)
            db.session.commit()

        # Downline user
        self.downline = User.query.filter_by(phone="085185773471").first()
        if not self.downline:
            self.downline = User(
                name="Markazcell Sente",
                phone="085185773471",
                email="markazcell@example.com",
                balance=150000.0,
                role="MEMBER",
                upline_id=self.upline.id,
                is_active=True
            )
            self.downline.set_password("pass123")
            db.session.add(self.downline)
            db.session.commit()
        else:
            self.downline.upline_id = self.upline.id
            self.downline.balance = 150000.0
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        self.app_context.pop()

    def test_message_formatting_with_topup_options(self):
        msg = _build_low_balance_message_upline(
            store_name="Ipay",
            upline_name=self.upline.name,
            user_name=self.downline.name,
            user_phone=self.downline.phone,
            current_balance=47442.0,
            option1=250112,
            option2=500099,
            dana_number="081775700114",
            dana_name="ANGGA DIAN PRATAMA PUTRA"
        )
        self.assertIn("Halo Kak *Saudi*", msg)
        self.assertIn("Pemberitahuan kemitraan dari *Ipay*:", msg)
        self.assertIn("👤 Nama: *Markazcell Sente*", msg)
        self.assertIn("📱 No. WhatsApp: `085185773471`", msg)
        self.assertIn("💰 *Sisa Saldo:* *Rp 47.442*", msg)
        self.assertIn("Demi menjaga kelancaran transaksi penjualan toko mitra Anda", msg)
        self.assertIn("Transfer Tunai *DANA* Otomatis", msg)
        self.assertIn("📱 No. *DANA*: `081775700114`", msg)
        self.assertIn("👤 A/N: *ANGGA DIAN PRATAMA PUTRA*", msg)
        self.assertIn("🔹 Pilihan 1: *Rp 250.112*", msg)
        self.assertIn("🔹 Pilihan 2: *Rp 500.099*", msg)
        self.assertIn("⚡ *SISTEM AUTO OTOMATIS AKTIF:*", msg)
        self.assertIn("tanpa harus kirim bukti transfer", msg)
        self.assertIn("sama persis sampai 3 digit angka terakhir", msg)
        self.assertIn("⏰ *Batas Waktu:* Sebelum pukul *", msg)
        self.assertIn("Terima kasih atas peran aktif Kakak dalam membimbing jaringan kemitraan! 🚀🤝", msg)

    def test_ticket_creation_and_auto_mutation_matching(self):
        # 1. Buat tiket deposit untuk downline
        opt1, opt2, d_num, d_name = create_upline_downline_deposit_tickets(self.downline, self.upline)
        self.assertTrue(opt1)
        self.assertTrue(opt2)
        self.assertGreaterEqual(opt1, 250010)
        self.assertGreaterEqual(opt2, 500010)

        # Cari tiket di database
        t1 = Transaction.query.filter_by(amount=opt1, user_id=self.downline.id, status='PENDING').first()
        t2 = Transaction.query.filter_by(amount=opt2, user_id=self.downline.id, status='PENDING').first()
        self.assertIsNotNone(t1)
        self.assertIsNotNone(t2)
        self.assertIn(f"UPLINE_TOPUP:{self.upline.id}:", t1.sn)
        self.assertIn(f"UPLINE_TOPUP:{self.upline.id}:", t2.sn)

        # 2. Simulasikan Payhook mendeteksi dana masuk untuk opt1
        downline_old_bal = float(self.downline.balance)
        ok, res_msg, res_trx = process_incoming_dana_mutation(
            raw_amount=opt1,
            sender_name="Saudi Upline",
            raw_text=f"Transfer berhasil sebesar Rp {opt1} dari Saudi",
            event_id=f"evt_upline_{opt1}"
        )
        self.assertTrue(ok)
        self.assertEqual(res_trx.id, t1.id)
        self.assertEqual(res_trx.status, 'SUCCESS')
        self.assertEqual(res_trx.payment_status, 'PAID')

        # Cek saldo downline bertambah
        db.session.refresh(self.downline)
        self.assertEqual(float(self.downline.balance), downline_old_bal + opt1)

        # 3. Cek tiket pasangan t2 otomatis di-CANCELLED agar kode unik bebas
        db.session.refresh(t2)
        self.assertEqual(t2.status, 'CANCELLED')
        self.assertEqual(t2.payment_status, 'CANCELLED')
        self.assertIn('AUTO_CANCELLED', t2.sn)

    def test_upline_topup_8_hours_flexibility(self):
        from datetime import datetime, timedelta
        from app.services.balance_notification_service import get_wib_now

        # 1. Pastikan waktu kedaluwarsa dihitung 8 jam ke depan
        expected_expiry_str = (get_wib_now() + timedelta(hours=8)).strftime('%H.%M WIB')
        msg = _build_low_balance_message_upline(
            store_name="Ipay",
            upline_name=self.upline.name,
            user_name=self.downline.name,
            user_phone=self.downline.phone,
            current_balance=47442.0,
            option1=250112,
            option2=500099,
            dana_number="081775700114",
            dana_name="ANGGA DIAN PRATAMA PUTRA"
        )
        self.assertIn(f"Sebelum pukul *{expected_expiry_str}*", msg)

        # 2. Uji transaksi tiket upline topup yang dibuat 3 jam lalu (melebihi 45 menit biasa)
        opt1, opt2, d_num, d_name = create_upline_downline_deposit_tickets(self.downline, self.upline)
        t1 = Transaction.query.filter_by(amount=opt1, user_id=self.downline.id, status='PENDING').first()
        self.assertIsNotNone(t1)

        # Simulasikan t1 dibuat 3 jam yang lalu
        t1.created_at = datetime.utcnow() - timedelta(hours=3)
        db.session.commit()

        # Mutasi masuk setelah 3 jam: harus tetap berhasil dicocokkan karena batas 8 jam
        ok, res_msg, res_trx = process_incoming_dana_mutation(
            raw_amount=opt1,
            sender_name="Saudi Upline Flex",
            raw_text=f"Transfer berhasil sebesar Rp {opt1} dari Saudi",
            event_id=f"evt_upline_8h_{opt1}_{int(datetime.utcnow().timestamp())}"
        )
        self.assertTrue(ok)
        self.assertEqual(res_trx.id, t1.id)
        self.assertEqual(res_trx.status, 'SUCCESS')

    def test_unique_code_range_10_to_500(self):
        from app.services.dana_mutasi_service import generate_unique_code
        for _ in range(50):
            code, total = generate_unique_code(250000)
            self.assertGreaterEqual(code, 10)
            self.assertLessEqual(code, 500)
            self.assertEqual(total, 250000 + code)

    def test_cleanup_expired_upline_tickets(self):
        from datetime import datetime, timedelta
        from app.services.balance_notification_service import cleanup_expired_upline_tickets
        # Buat tiket yang usianya 9 jam lalu
        t = Transaction(
            ref_id=f"DEP-EXP-{int(datetime.utcnow().timestamp())}",
            user_id=self.downline.id,
            sku_code='DEPOSIT_MANUAL',
            product_name="Top-up DANA Mitra",
            target_number="081775700114",
            payment_method='DANA',
            amount=250123.0,
            payment_status='UNPAID',
            status='PENDING',
            sn=f"UPLINE_TOPUP:{self.upline.id}:testexp | Total: 250123",
            created_at=datetime.utcnow() - timedelta(hours=9)
        )
        db.session.add(t)
        db.session.commit()

        cleanup_expired_upline_tickets(max_hours=8)
        db.session.refresh(t)
        self.assertEqual(t.status, 'CANCELLED')
        self.assertEqual(t.payment_status, 'CANCELLED')
        self.assertIn('EXPIRED', t.sn)

    def test_riwayat_visibility_downline_vs_upline(self):
        # 1. Tiket Pending: tidak boleh tampil untuk Downline, tapi harus tampil untuk Upline
        opt1, opt2, d_num, d_name = create_upline_downline_deposit_tickets(self.downline, self.upline)
        t_pending = Transaction.query.filter_by(amount=opt1, user_id=self.downline.id, status='PENDING').first()
        self.assertIsNotNone(t_pending)

        # Simulasikan login Downline dengan client terisolasi
        client_downline = self.app.test_client()
        with client_downline.session_transaction() as sess:
            sess['_user_id'] = str(self.downline.id)
            sess['_fresh'] = True

        res_downline = client_downline.get('/riwayat')
        self.assertEqual(res_downline.status_code, 200)
        # Downline TIDAK boleh melihat Ref ID tiket pending ini
        self.assertNotIn(t_pending.ref_id, res_downline.get_data(as_text=True))

        # Reset cached user in Flask g agar client_upline mengautentikasi pengguna baru
        from flask import g
        if hasattr(g, '_login_user'):
            delattr(g, '_login_user')

        # Simulasikan login Upline dengan client terisolasi
        client_upline = self.app.test_client()
        with client_upline.session_transaction() as sess:
            sess['_user_id'] = str(self.upline.id)
            sess['_fresh'] = True

        res_upline = client_upline.get('/riwayat')
        self.assertEqual(res_upline.status_code, 200)
        # Upline HARUS melihat Ref ID tiket pending ini di riwayatnya
        self.assertIn(t_pending.ref_id, res_upline.get_data(as_text=True))

if __name__ == '__main__':
    unittest.main()
