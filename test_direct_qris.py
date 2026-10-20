import os
import sys
import unittest
from datetime import datetime, timedelta

# Ensure root dir in path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.models.setting import Setting
from app.utils.qris import (
    generate_dynamic_qris,
    validate_qris,
    crc16_ccitt,
    parse_emvco_qris,
    DEFAULT_DANA_QRIS_STRING,
)
from app.services.setting_service import (
    get_setting_value,
    set_setting_value,
    get_active_payment_gateway,
    is_payment_gateway_enabled,
    is_inhouse_qris_enabled,
    invalidate_setting_cache,
)
from app.services.dana_mutasi_service import (
    generate_unique_code,
    create_dana_deposit_ticket,
    process_incoming_dana_mutation,
)
from app.services.order_service import process_paid_order


class TestDirectQrisAndDanaPayhook(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # Buat user dummy untuk testing jika belum ada
        self.test_user = User.query.filter_by(phone="08999999999").first()
        if not self.test_user:
            self.test_user = User(
                name="Tester QRIS",
                phone="08999999999",
                email="tester_qris@example.com",
                balance=50000.0,
                role="MEMBER",
            )
            self.test_user.set_password("password123")
            db.session.add(self.test_user)
            db.session.commit()

        # Buat produk dummy jika belum ada
        self.test_prod = Product.query.filter_by(sku_code="TEST_PULSA10").first()
        if not self.test_prod:
            self.test_prod = Product(
                sku_code="TEST_PULSA10",
                name="Pulsa Test 10.000",
                category="Pulsa Reguler",
                brand="TELKOMSEL",
                sell_price=11000.0,
                base_price=10100.0,
                is_active=True,
            )
            db.session.add(self.test_prod)
            db.session.commit()

        invalidate_setting_cache()

    def tearDown(self):
        self.app_context.pop()

    # ============================================================
    # 1. TEST EMVCo QRIS GENERATOR & CRC16 CHECKSUM
    # ============================================================
    def test_01_user_base_qris_validity(self):
        """Memverifikasi string base QRIS DANA milik user 100% valid EMVCo dan CRC."""
        ok, msg = validate_qris(DEFAULT_DANA_QRIS_STRING)
        self.assertTrue(ok, f"Base QRIS user tidak valid: {msg}")

        tags = dict(parse_emvco_qris(DEFAULT_DANA_QRIS_STRING))
        self.assertEqual(tags.get("00"), "01")
        self.assertEqual(tags.get("53"), "360")  # IDR
        self.assertEqual(tags.get("58"), "ID")   # Indonesia
        self.assertIn("ANGGA DIAN PRATAMA PUTRA", tags.get("59", ""))
        self.assertEqual(tags.get("60"), "Kota Bekasi")
        self.assertEqual(tags.get("54"), "10120")  # Nominal asli Rp 10.120

    def test_02_dynamic_qris_generation(self):
        """Memverifikasi injeksi nominal Tag 54 dan rekalkulasi CRC16-CCITT."""
        test_amounts = [5000, 10120, 25147, 50350, 100000, 1500000]
        for amt in test_amounts:
            dyn_str = generate_dynamic_qris(DEFAULT_DANA_QRIS_STRING, amt)
            ok, msg = validate_qris(dyn_str)
            self.assertTrue(ok, f"Hasil dynamic QRIS untuk nominal {amt} tidak valid: {msg}")

            tags = dict(parse_emvco_qris(dyn_str))
            self.assertEqual(tags.get("01"), "12", "Tag 01 harus bernilai 12 (Dynamic QR)")
            self.assertEqual(tags.get("54"), str(amt), f"Tag 54 harus memuat nominal {amt}")

            # Re-cek kalkulasi CRC
            crc_actual = dyn_str[-4:]
            crc_calc = crc16_ccitt(dyn_str[:-4])
            self.assertEqual(crc_actual, crc_calc, f"CRC tidak cocok pada nominal {amt}")

    # ============================================================
    # 2. TEST PENGATURAN PAYMENT GATEWAY (DANA vs PAKASIR vs PAYMENTKITA vs OFF)
    # ============================================================
    def test_03_payment_gateway_switch_modes(self):
        """Memverifikasi fungsi pemilihan 4 mode: dana, pakasir, paymentkita, off."""
        # Mode 1: DANA In-House
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()
        self.assertEqual(get_active_payment_gateway(), "dana")
        self.assertTrue(is_payment_gateway_enabled(), "Mode DANA harus terhitung aktif")

        # Mode 2: Pakasir
        set_setting_value("active_payment_gateway", "pakasir")
        invalidate_setting_cache()
        self.assertEqual(get_active_payment_gateway(), "pakasir")
        self.assertTrue(is_payment_gateway_enabled(), "Mode Pakasir harus terhitung aktif")

        # Mode 3: PaymentKita
        set_setting_value("active_payment_gateway", "paymentkita")
        invalidate_setting_cache()
        self.assertEqual(get_active_payment_gateway(), "paymentkita")
        self.assertTrue(is_payment_gateway_enabled(), "Mode PaymentKita harus terhitung aktif")

        # Mode 4: OFF (Semua QRIS mati, hanya saldo)
        set_setting_value("active_payment_gateway", "off")
        invalidate_setting_cache()
        self.assertEqual(get_active_payment_gateway(), "off")
        self.assertFalse(is_payment_gateway_enabled(), "Mode OFF harus mengembalikan False")

        # Kembalikan ke mode DANA
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()

    # ============================================================
    # 3. TEST KODE UNIK & PENCEGAHAN BENTROK TRANSAKSI
    # ============================================================
    def test_04_unique_code_collision_prevention(self):
        """Memverifikasi kode unik tidak bentrok antara tiket deposit dan order QRIS."""
        base_nominal = 25000

        # Generate order 1
        code1, total1 = generate_unique_code(base_nominal)
        trx1 = Transaction(
            ref_id=f"TEST-COL-1-{datetime.utcnow().timestamp()}",
            user_id=self.test_user.id,
            sku_code="TEST_PULSA10",
            product_name="Pulsa Test",
            target_number="08123456789",
            amount=float(total1),
            payment_method="QRIS",
            payment_status="UNPAID",
            status="UNPAID",
        )
        db.session.add(trx1)
        db.session.commit()

        # Generate order 2 dengan nominal pokok yang sama persis
        code2, total2 = generate_unique_code(base_nominal)
        self.assertNotEqual(total1, total2, "Total nominal tidak boleh sama (harus bebas bentrok)")
        self.assertNotEqual(code1, code2, "Kode unik tidak boleh sama pada nominal pokok yang sama")

        # Bersihkan transaksi uji
        db.session.delete(trx1)
        db.session.commit()

    # ============================================================
    # 4. TEST DIRECT QRIS PRODUCT PURCHASE VIA PAYHOOK WEBHOOK
    # ============================================================
    def test_05_direct_qris_product_purchase_via_payhook(self):
        """Simulasi alur penuh order produk via QRIS hingga lunas otomatis via webhook DANA."""
        set_setting_value("active_payment_gateway", "dana")
        invalidate_setting_cache()

        base_nominal = 15000
        code, total_amount = generate_unique_code(base_nominal)
        ref_id = f"GT-TESTQRIS-{int(datetime.utcnow().timestamp())}"

        # 1. Simulasikan pembuatan order QRIS oleh user
        trx = Transaction(
            ref_id=ref_id,
            user_id=self.test_user.id,
            sku_code="TEST_PULSA10",
            product_name="Pulsa Test 10.000",
            target_number="08999999999",
            amount=float(total_amount),
            payment_method="QRIS",
            payment_status="UNPAID",
            status="UNPAID",
            sn=f"Pokok: Rp {base_nominal:,} | Unik: {code:03d} | Total: Rp {total_amount:,} | DANA QRIS",
        )
        db.session.add(trx)
        db.session.commit()

        # Pastikan transaksi berhasil tersimpan dengan status UNPAID
        self.assertEqual(trx.payment_status, "UNPAID")
        self.assertEqual(trx.status, "UNPAID")

        # 2. Simulasikan PayHook mengirimkan webhook transfer masuk ke server
        event_id = f"payhook_test_evt_{int(datetime.utcnow().timestamp())}"
        sender_name = "Budi Hartono (BCA QRIS)"
        raw_notif_text = f"Kamu menerima pembayaran QRIS sebesar Rp {total_amount:,} dari {sender_name}"

        from unittest.mock import patch

        with patch("app.services.digiflazz.create_transaction") as mock_digi:
            mock_digi.return_value = {
                "data": {
                    "status": "Sukses",
                    "rc": "00",
                    "sn": "SN998877665544",
                    "message": "Transaksi Sukses",
                }
            }

            ok, msg, matched_trx = process_incoming_dana_mutation(
                raw_amount=total_amount,
                sender_name=sender_name,
                raw_text=raw_notif_text,
                event_id=event_id,
            )

        self.assertTrue(ok, f"Mutasi DANA gagal diproses: {msg}")
        self.assertIsNotNone(matched_trx)
        self.assertEqual(matched_trx.ref_id, ref_id)
        self.assertEqual(matched_trx.payment_status, "PAID")
        self.assertEqual(matched_trx.status, "SUCCESS")
        self.assertEqual(matched_trx.sn, "SN998877665544")

        # 3. Test Idempotency: Jika webhook dikirim ulang oleh PayHook (retry)
        ok_retry, msg_retry, retry_trx = process_incoming_dana_mutation(
            raw_amount=total_amount,
            sender_name=sender_name,
            raw_text=raw_notif_text,
            event_id=event_id,
        )
        self.assertTrue(ok_retry)
        self.assertIn("idempoten", msg_retry.lower())

        # Bersihkan transaksi uji
        db.session.delete(trx)
        db.session.commit()

    # ============================================================
    # 5. TEST DEPOSIT TIKET MANUAL TETAP BERJALAN NORMAL
    # ============================================================
    def test_06_deposit_ticket_still_works_perfectly(self):
        """Memverifikasi bahwa fitur deposit saldo DANA tetap berjalan lancar tanpa terganggu."""
        initial_balance = float(self.test_user.balance or 0.0)
        depo_amount = 20000

        ok, msg, t_data = create_dana_deposit_ticket(self.test_user.id, depo_amount)
        self.assertTrue(ok, f"Gagal membuat tiket deposit: {msg}")
        total_transfer = t_data["total_transfer"]
        ref_id = t_data["ref_id"]

        # Simulasikan mutasi masuk untuk tiket deposit
        evt_id = f"payhook_depo_evt_{int(datetime.utcnow().timestamp())}"
        ok_mut, msg_mut, trx_depo = process_incoming_dana_mutation(
            raw_amount=total_transfer,
            sender_name="Siti Aminah",
            event_id=evt_id,
        )

        self.assertTrue(ok_mut, f"Mutasi deposit gagal: {msg_mut}")
        self.assertEqual(trx_depo.ref_id, ref_id)
        self.assertEqual(trx_depo.status, "SUCCESS")

        # Cek saldo user bertambah persis
        db.session.refresh(self.test_user)
        expected_balance = initial_balance + float(total_transfer)
        self.assertAlmostEqual(float(self.test_user.balance), expected_balance, places=2)

        # Bersihkan tiket uji
        db.session.delete(trx_depo)
        db.session.commit()

    # ============================================================
    # 6. TEST PROVIDER FAILURE AUTO-REFUND TO USER WALLET
    # ============================================================
    def test_07_provider_failure_auto_refund_qris(self):
        """Memverifikasi jika API provider gagal, dana pembayaran QRIS otomatis masuk ke saldo akun user."""
        from unittest.mock import patch

        db.session.refresh(self.test_user)
        initial_balance = float(self.test_user.balance or 0.0)

        base_nominal = 12000
        code, total_amount = generate_unique_code(base_nominal)
        ref_id = f"GT-FAILREF-{int(datetime.utcnow().timestamp())}"

        trx = Transaction(
            ref_id=ref_id,
            user_id=self.test_user.id,
            sku_code="TEST_PULSA10",
            product_name="Pulsa Test Gagal",
            target_number="08999999999",
            amount=float(total_amount),
            payment_method="QRIS",
            payment_status="UNPAID",
            status="UNPAID",
        )
        db.session.add(trx)
        db.session.commit()

        event_id = f"payhook_fail_evt_{int(datetime.utcnow().timestamp())}"
        with patch("app.services.digiflazz.create_transaction") as mock_digi:
            mock_digi.return_value = {
                "data": {
                    "status": "Gagal",
                    "rc": "42",
                    "message": "Cut off time / Gangguan operator",
                }
            }

            ok, msg, matched_trx = process_incoming_dana_mutation(
                raw_amount=total_amount,
                sender_name="Joko Anwar",
                raw_text=f"Kamu menerima pembayaran QRIS sebesar Rp {total_amount:,} dari Joko Anwar",
                event_id=event_id,
            )

        self.assertTrue(ok)
        self.assertEqual(matched_trx.payment_status, "PAID")
        self.assertEqual(matched_trx.status, "FAILED")
        self.assertIn("Refund", matched_trx.sn)

        # Cek saldo user otomatis bertambah sebesar total_amount yang dibayar via QRIS
        db.session.refresh(self.test_user)
        expected_balance = initial_balance + float(total_amount)
        self.assertAlmostEqual(float(self.test_user.balance), expected_balance, places=2)

        # Bersihkan transaksi uji
        db.session.delete(trx)
        db.session.commit()


if __name__ == "__main__":
    unittest.main()
