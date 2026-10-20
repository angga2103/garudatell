import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.services.setting_service import set_setting_value, invalidate_setting_cache
from app.services.dana_mutasi_service import process_incoming_dana_mutation, generate_unique_code
from app.services.order_service import _auto_refund_on_failure, process_paid_order


class TestTransactionSecurityAndEdgeCases(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.client = self.app.test_client()

        # User dummy
        self.user = User.query.filter_by(phone="08777777777").first()
        if not self.user:
            self.user = User(
                name="Security Audit Tester",
                phone="08777777777",
                email="security_test@example.com",
                balance=10000.0,
                role="MEMBER",
            )
            self.user.set_password("pass123")
            db.session.add(self.user)
            db.session.commit()

        # Product dummy
        self.prod = Product.query.filter_by(sku_code="SEC_TEST_SKU").first()
        if not self.prod:
            self.prod = Product(
                sku_code="SEC_TEST_SKU",
                name="Produk Audit Keamanan",
                category="Pulsa",
                brand="TELKOMSEL",
                sell_price=10500.0,
                base_price=10000.0,
                is_active=True,
            )
            db.session.add(self.prod)
            db.session.commit()

    def tearDown(self):
        self.app_context.pop()

    def test_01_prevent_double_refund(self):
        """Memverifikasi bahwa _auto_refund_on_failure idempoten dan tidak mendobelkan saldo user."""
        db.session.refresh(self.user)
        initial_balance = float(self.user.balance or 0.0)

        trx = Transaction(
            ref_id=f"TEST-DBLREF-{int(datetime.now().timestamp())}",
            user_id=self.user.id,
            sku_code=self.prod.sku_code,
            product_name=self.prod.name,
            target_number="08777777777",
            amount=15000.0,
            payment_method="QRIS",
            payment_status="PAID",
            status="FAILED",
            sn="Gangguan",
        )
        db.session.add(trx)
        db.session.commit()

        # Refund pertama
        _auto_refund_on_failure(trx)
        db.session.commit()
        db.session.refresh(self.user)
        self.assertAlmostEqual(float(self.user.balance), initial_balance + 15000.0, places=2)
        self.assertIn("Refund", trx.sn)

        # Refund kedua (simulasi webhook ulang / retry sync)
        _auto_refund_on_failure(trx)
        db.session.commit()
        db.session.refresh(self.user)
        # Saldo TIDAK boleh bertambah lagi!
        self.assertAlmostEqual(float(self.user.balance), initial_balance + 15000.0, places=2)

        # Bersihkan
        db.session.delete(trx)
        db.session.commit()

    def test_02_customer_scans_cancelled_qris_recovery(self):
        """
        Memverifikasi kasus kritis: Pembeli terlanjur menekan 'Batalkan' tapi tetap transfer/scan QRIS.
        Sistem harus otomatis menyelamatkan uang pembeli ke Saldo Akun.
        """
        db.session.refresh(self.user)
        initial_balance = float(self.user.balance or 0.0)

        nominal = 25000
        code, total_amount = generate_unique_code(nominal)
        ref_id = f"TEST-CANCREC-{int(datetime.now().timestamp())}"

        # Transaksi yang dibatalkan oleh user
        trx_batal = Transaction(
            ref_id=ref_id,
            user_id=self.user.id,
            sku_code=self.prod.sku_code,
            product_name=self.prod.name,
            target_number="08777777777",
            amount=float(total_amount),
            payment_method="QRIS",
            payment_status="CANCELLED",
            status="CANCELLED",
            sn="Dibatalkan User",
        )
        db.session.add(trx_batal)
        db.session.commit()

        # Webhook mutasi DANA masuk untuk nominal tersebut
        ok, msg, res_trx = process_incoming_dana_mutation(
            raw_amount=total_amount,
            sender_name="Pengirim Telat",
            raw_text=f"Kamu menerima transfer Rp {total_amount:,}",
            event_id=f"evt_canc_{int(datetime.now().timestamp())}",
        )

        self.assertTrue(ok, f"Gagal recovery transaksi batal: {msg}")
        self.assertEqual(res_trx.ref_id, ref_id)
        self.assertEqual(res_trx.payment_status, "PAID")
        self.assertIn("masuk Saldo Akun", res_trx.sn)

        # Cek saldo user otomatis terisi sebesar total_amount
        db.session.refresh(self.user)
        self.assertAlmostEqual(float(self.user.balance), initial_balance + float(total_amount), places=2)

        # Bersihkan
        db.session.delete(trx_batal)
        db.session.commit()

    def test_03_paymentkita_empty_secret_rejection(self):
        """Memverifikasi bahwa webhook PaymentKita menolak signature palsu jika secret di env kosong."""
        with patch.dict(os.environ, {"PAYMENTKITA_MERCHANT_ID": "", "PAYMENTKITA_SECRET": ""}):
            # Mencoba mengirim POST callback dengan data sembarang
            res = self.client.post("/trx/callback/paymentkita", json={
                "ref_id": "TEST-FAKE-ORDER",
                "amount": "10000",
                "status": "success",
                "signature": "d41d8cd98f00b204e9800998ecf8427e" # MD5 kosong
            })
            # Wajib ditolak (403 atau 400), TIDAK BOLEH 200!
            self.assertIn(res.status_code, [400, 403, 404])

    def test_04_digiflazz_webhook_refunds_qris_on_failure(self):
        """Memverifikasi bahwa webhook Digiflazz merefund transaksi QRIS jika status provider FAILED."""
        db.session.refresh(self.user)
        initial_balance = float(self.user.balance or 0.0)

        ref_id = f"TEST-DIGI-QRIS-FAIL-{int(datetime.now().timestamp())}"
        trx = Transaction(
            ref_id=ref_id,
            user_id=self.user.id,
            sku_code=self.prod.sku_code,
            product_name=self.prod.name,
            target_number="08777777777",
            amount=18500.0,
            payment_method="QRIS",
            payment_status="PAID",
            status="PROCESSING",
            sn="Menunggu proses provider",
        )
        db.session.add(trx)
        db.session.commit()

        # Webhook Digiflazz mengirim status Gagal (misal RC 41 - Gangguan)
        # Mock signature validation agar webhook diterima
        with patch("app.services.digiflazz.check_transaction_status") as mock_chk:
            mock_chk.return_value = (True, {"status": "Gagal", "rc": "41", "message": "Nomor Gangguan"}, "Gagal")
            res = self.client.post("/trx/callback/digiflazz", json={
                "data": {
                    "ref_id": ref_id,
                    "status": "Gagal",
                    "rc": "41",
                    "message": "Nomor Gangguan"
                }
            })

        db.session.refresh(trx)
        self.assertEqual(trx.status, "FAILED")
        self.assertIn("Refund", trx.sn)

        # Cek saldo user ter-refund
        db.session.refresh(self.user)
        self.assertAlmostEqual(float(self.user.balance), initial_balance + 18500.0, places=2)

        # Bersihkan
        db.session.delete(trx)
        db.session.commit()


if __name__ == "__main__":
    unittest.main()
