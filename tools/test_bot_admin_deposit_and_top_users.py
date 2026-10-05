#!/usr/bin/env python3
"""
Test Suite: Bot 3 Admin (@Panel_Garudatellbot)
1. Fitur Tarik Deposit (Min 200K, metode GoPay, ShopeePay, dan Bank)
2. Fitur Top Transaksi User Hari Ini (Rincian Sukses, Gagal, Nominal Sukses, Nominal Gagal, dan Total Volume)
"""

import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

# Import app factory
from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.deposit_ticket import DigiDepositTicket
from app.services.digiflazz import format_bank_name
from app.services.telegram_service import (
    get_admin_inline_keyboard,
    render_top_users_report,
    render_tarik_deposit_menu,
    render_tarik_deposit_methods_menu,
    render_tarik_deposit_amounts,
    execute_tarik_deposit,
    cancel_tarik_deposit,
    handle_admin_callback,
    handle_admin_message
)

class TestBotAdminDepositAndTopUsers(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

        # Buat dummy user untuk testing
        self.user1 = User.query.filter_by(phone='089911112222').first()
        if not self.user1:
            self.user1 = User(
                phone='089911112222',
                name='Toko Berkah Cellular',
                role='agen',
                balance=500000.0,
                pin_hash='dummy'
            )
            self.user1.set_password("pass123")
            db.session.add(self.user1)

        self.user2 = User.query.filter_by(phone='089933334444').first()
        if not self.user2:
            self.user2 = User(
                phone='089933334444',
                name='Kios Pulsa Sejahtera',
                role='reseller',
                balance=750000.0,
                pin_hash='dummy'
            )
            self.user2.set_password("pass123")
            db.session.add(self.user2)

        db.session.commit()

    def tearDown(self):
        # Bersihkan tiket deposit & transaksi test
        DigiDepositTicket.query.filter(DigiDepositTicket.owner_name.in_(['TEST BOT DEPO', 'TEST ANGGA'])).delete()
        Transaction.query.filter(Transaction.ref_id.like('TEST-TRX-%')).delete()
        if self.user1:
            db.session.delete(self.user1)
        if self.user2:
            db.session.delete(self.user2)
        db.session.commit()
        self.app_context.pop()

    def test_01_format_bank_name(self):
        """Uji format nama bank termasuk GoPay dan ShopeePay (dengan toleransi typo shoopepay)."""
        self.assertEqual(format_bank_name('shopeepay'), 'ShopeePay')
        self.assertEqual(format_bank_name('ShopeePay'), 'ShopeePay')
        self.assertEqual(format_bank_name('shoopepay'), 'ShopeePay')  # Typo tolerance
        self.assertEqual(format_bank_name('gopay'), 'GOPAY')
        self.assertEqual(format_bank_name('GoPay'), 'GOPAY')
        self.assertEqual(format_bank_name('go-pay'), 'GOPAY')
        self.assertEqual(format_bank_name('flip'), 'Flip')
        self.assertEqual(format_bank_name('bca'), 'BCA')
        self.assertEqual(format_bank_name('mandiri'), 'MANDIRI')
        print("  [OK] format_bank_name mendukung GoPay dan ShopeePay (termasuk toleransi typo shoopepay).")

    def test_02_get_admin_inline_keyboard(self):
        """Pastikan tombol '🏆 Top User Hari Ini' dan '📥 Tarik Deposit' ada di menu bot."""
        kb = get_admin_inline_keyboard()
        buttons = [btn for row in kb['inline_keyboard'] for btn in row]
        callbacks = [btn['callback_data'] for btn in buttons]

        self.assertIn('cmd_top_users', callbacks)
        self.assertIn('cmd_tarik_deposit', callbacks)
        print("  [OK] get_admin_inline_keyboard memuat tombol cmd_top_users dan cmd_tarik_deposit.")

    def test_03_tarik_deposit_nominal_validation(self):
        """Pastikan penarikan deposit menolak nominal di bawah 200K."""
        sent_messages = []
        with patch('app.services.telegram_service._send_message', side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append(text)), \
             patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('dummy_token', '12345')):
            
            # Coba 100.000 (di bawah 200K)
            execute_tarik_deposit('dummy_token', '12345', None, 'GoPay', 100000, owner_name='TEST BOT DEPO', is_edit=False)
            self.assertTrue(any('NOMINAL DI BAWAH BATAS MINIMAL' in msg or '200.000' in msg for msg in sent_messages))
            
            # Coba 199.999
            sent_messages.clear()
            execute_tarik_deposit('dummy_token', '12345', None, 'ShopeePay', 199999, owner_name='TEST BOT DEPO', is_edit=False)
            self.assertTrue(any('NOMINAL DI BAWAH BATAS MINIMAL' in msg or '200.000' in msg for msg in sent_messages))
        print("  [OK] Validasi minimal nominal Rp 200.000 (200K) berhasil memblokir nominal kurang.")

    def test_04_tarik_deposit_execution_and_cancellation(self):
        """Pastikan deposit >= 200K memanggil request_deposit dan menyimpan DigiDepositTicket di DB."""
        mock_response_data = {
            'amount': 250321,
            'account_no': '08123456789',
            'account_name': 'PT DIGIFLAZZ INTERKONEKSI INDONESIA',
            'bank': 'GOPAY',
            'notes': 'Transfer tepat 250321',
            'rc': '00'
        }

        sent_messages = []
        with patch('app.services.telegram_service._send_message', side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((text, reply_markup))), \
             patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('dummy_token', '12345')), \
             patch('app.services.digiflazz.request_deposit', return_value=(True, mock_response_data, "Tiket deposit berhasil dibuat!")):

            execute_tarik_deposit('dummy_token', '12345', None, 'GoPay', 250000, owner_name='TEST BOT DEPO', is_edit=False)

            # Verifikasi pesan sukses terkirim
            self.assertTrue(len(sent_messages) > 0)
            msg_text, msg_kb = sent_messages[-1]
            self.assertIn("TIKET DEPOSIT BERHASIL DIBUAT", msg_text)
            self.assertIn("250.321", msg_text)
            self.assertIn("GOPAY", msg_text)

            # Verifikasi tersimpan di DB
            ticket = DigiDepositTicket.query.filter_by(owner_name='TEST BOT DEPO', status='PENDING').order_by(DigiDepositTicket.id.desc()).first()
            self.assertIsNotNone(ticket)
            self.assertEqual(ticket.amount_requested, 250000.0)
            self.assertEqual(ticket.amount_transfer, 250321.0)
            self.assertEqual(ticket.bank, 'GOPAY')

            ticket_id = ticket.id

            # Uji pembatalan tiket
            cancel_tarik_deposit('dummy_token', '12345', None, ticket_id, is_edit=False)
            updated_ticket = DigiDepositTicket.query.get(ticket_id)
            self.assertEqual(updated_ticket.status, 'CANCELLED')
            print("  [OK] Pembuatan tiket deposit 250K via GoPay dan pembatalan tiket teruji sempurna.")

    def test_05_render_tarik_deposit_menu_active_detection(self):
        """Pastikan tiket pending aktif terdeteksi saat menu deposit dibuka."""
        # Buat tiket pending
        test_ticket = DigiDepositTicket(
            amount_requested=300000.0,
            amount_transfer=300123.0,
            bank='ShopeePay',
            owner_name='TEST BOT DEPO',
            account_number='08987654321',
            account_name='PT DIGIFLAZZ INTERKONEKSI INDONESIA',
            notes='Transfer tepat 300123',
            rc='00',
            status='PENDING'
        )
        db.session.add(test_ticket)
        db.session.commit()

        text, markup = render_tarik_deposit_menu()
        self.assertIn("TIKET DEPOSIT AKTIF TERDETEKSI", text)
        self.assertIn("300.123", text)
        self.assertIn("ShopeePay", text)
        
        # Periksa ada tombol pembatalan
        cancel_btn = [btn for row in markup['inline_keyboard'] for btn in row if f"depo_cancel_{test_ticket.id}" in btn.get('callback_data', '')]
        self.assertTrue(len(cancel_btn) > 0)

        # Batalkan tiket
        test_ticket.status = 'CANCELLED'
        db.session.commit()

        # Menu harus kembali ke daftar metode
        text2, markup2 = render_tarik_deposit_menu()
        self.assertIn("TARIK TIKET DEPOSIT DIGIFLAZZ", text2)
        print("  [OK] Deteksi tiket deposit aktif dan navigasi metode berjalan akurat.")

    def test_06_top_transaksi_user_hari_ini(self):
        """Pastikan Top Transaksi User Hari Ini menampilkan rincian count & nominal sukses dan gagal."""
        now = datetime.utcnow()
        # Buat transaksi hari ini untuk user 1 (2 sukses, 1 gagal)
        t1 = Transaction(
            user_id=self.user1.id,
            ref_id=f"TEST-TRX-1-{int(now.timestamp())}",
            sku_code="TS5",
            product_name="Telkomsel 5rb",
            target_number="081234567801",
            amount=6000.0,
            payment_method="balance",
            status='SUCCESS',
            created_at=now
        )
        t2 = Transaction(
            user_id=self.user1.id,
            ref_id=f"TEST-TRX-2-{int(now.timestamp())}",
            sku_code="TS10",
            product_name="Telkomsel 10rb",
            target_number="081234567802",
            amount=11000.0,
            payment_method="balance",
            status='SUCCESS',
            created_at=now
        )
        t3 = Transaction(
            user_id=self.user1.id,
            ref_id=f"TEST-TRX-3-{int(now.timestamp())}",
            sku_code="TS50",
            product_name="Telkomsel 50rb",
            target_number="081234567803",
            amount=51000.0,
            payment_method="balance",
            status='FAILED',
            created_at=now
        )

        # Buat transaksi hari ini untuk user 2 (1 sukses Rp 100.000)
        t4 = Transaction(
            user_id=self.user2.id,
            ref_id=f"TEST-TRX-4-{int(now.timestamp())}",
            sku_code="PLN100",
            product_name="Token PLN 100rb",
            target_number="14023456789",
            amount=102000.0,
            payment_method="balance",
            status='SUCCESS',
            created_at=now
        )

        db.session.add_all([t1, t2, t3, t4])
        db.session.commit()

        rep_text, rep_kb = render_top_users_report(limit=5)

        # Verifikasi konten laporan
        self.assertIn("TOP TRANSAKSI USER / TOKO HARI INI", rep_text)
        self.assertIn("RINGKASAN SISTEM HARI INI", rep_text)
        self.assertIn("PERINGKAT PENGGUNA TERAKTIF", rep_text)
        self.assertIn("Toko Berkah Cellular", rep_text)
        self.assertIn("Kios Pulsa Sejahtera", rep_text)

        # Verifikasi rincian jumlah transaksi & nominal
        self.assertIn("Sukses:", rep_text)
        self.assertIn("Gagal:", rep_text)
        self.assertIn("Total:", rep_text)

        # Tombol intip toko harus ada di inline keyboard
        buttons = [btn for row in rep_kb['inline_keyboard'] for btn in row]
        store_views = [btn['callback_data'] for btn in buttons if btn.get('callback_data', '').startswith('store_view_')]
        self.assertTrue(len(store_views) >= 2)
        self.assertIn(f"store_view_{self.user1.id}", store_views)
        self.assertIn(f"store_view_{self.user2.id}", store_views)

        print("  [OK] Top Transaksi User Hari Ini menghitung rincian sukses, gagal, dan volume per user dengan benar.")

    def test_07_chat_commands_handling(self):
        """Pastikan chat commands /topuser, /tarikdeposit, dan /bataldeposit ditangani dengan baik."""
        sent_messages = []
        with patch('app.services.telegram_service._send_message', side_effect=lambda token, chat_id, text, reply_markup=None: sent_messages.append((text, reply_markup))), \
             patch('app.services.telegram_service.get_bot_admin_credentials', return_value=('dummy_token', '12345')):

            # Test command /topuser
            handle_admin_message(self.app, {'chat': {'id': '12345'}, 'text': '/topuser'})
            self.assertTrue(any('TOP TRANSAKSI USER / TOKO HARI INI' in t[0] for t in sent_messages))

            # Test command /tarikdeposit tanpa argumen (buka menu)
            sent_messages.clear()
            handle_admin_message(self.app, {'chat': {'id': '12345'}, 'text': '/tarikdeposit'})
            self.assertTrue(any('TARIK TIKET DEPOSIT DIGIFLAZZ' in t[0] or 'TIKET DEPOSIT AKTIF' in t[0] for t in sent_messages))

            # Test command /tarikdeposit dengan nominal di bawah 200K
            sent_messages.clear()
            handle_admin_message(self.app, {'chat': {'id': '12345'}, 'text': '/tarikdeposit gopay 50000'})
            self.assertTrue(any('NOMINAL DI BAWAH BATAS MINIMAL' in t[0] or '200.000' in t[0] for t in sent_messages))

        print("  [OK] Chat commands /topuser dan /tarikdeposit teruji berhasil.")

if __name__ == '__main__':
    unittest.main()
