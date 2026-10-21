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

if __name__ == '__main__':
    unittest.main()
