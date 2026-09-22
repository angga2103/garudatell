"""
Test Suite: Admin Manual Refund Feature
Memverifikasi:
1. Refund saldo akun reguler saat transaksi diubah ke FAILED dengan do_refund=1.
2. Tidak ada penambahan saldo jika do_refund tidak dicentang (do_refund=0).
3. Refund saldo kasir cabang (TrustedDevice & BranchMutation) saat transaksi kasir di-refund.
4. Proteksi double refund jika transaksi cabang sudah pernah di-refund.
5. Proteksi tiket deposit (DEPOSIT_SALDO) agar tidak bisa di-refund.
6. Proteksi transaksi UNPAID agar tidak bisa di-refund.
"""

import os
import sys
import time
import secrets

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.trusted_device import TrustedDevice
from app.models.branch_mutation import BranchMutation
from app.models.admin import Admin

def run_refund_tests():
    print("=" * 70)
    print("  TEST SUITE: ADMIN MANUAL REFUND & TRANSACTION STATUS UPDATE")
    print("=" * 70)

    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    with app.app_context():
        # Setup Test User
        test_phone = f"0899{int(time.time()) % 100000000:08d}"
        user = User(
            name="Test Refund User",
            phone=test_phone,
            password_hash="testhash",
            balance=50000.0,
            role="vip"
        )
        db.session.add(user)
        db.session.commit()

        # Setup Test Kasir Cabang
        device = TrustedDevice(
            user_id=user.id,
            device_uuid=secrets.token_hex(16),
            device_name="Cabang Kasir 1",
            status="approved",
            branch_balance=100000.0
        )
        db.session.add(device)
        db.session.commit()

        client = app.test_client()

        # Login admin session
        with client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_user'] = 'admin'

        # ----------------------------------------------------------------------
        # TEST 1: User Normal - SUCCESS -> FAILED dengan do_refund=1
        # ----------------------------------------------------------------------
        print("\n[Test 1] User Reguler: Ubah SUCCESS -> FAILED dengan do_refund=1...")
        trx1 = Transaction(
            user_id=user.id,
            ref_id=f"TRX-TEST-{int(time.time())}-1",
            product_name="Telkomsel 10K",
            sku_code="tsel10",
            target_number=test_phone,
            amount=12000.0,
            payment_method="SALDO",
            payment_status="PAID",
            status="SUCCESS",
            sn="SN123456"
        )
        db.session.add(trx1)
        db.session.commit()

        bal_before = user.balance
        res1 = client.post(f"/admin/transactions/update_status/{trx1.id}", data={
            'status': 'FAILED',
            'payment_status': 'PAID',
            'sn': 'Gagal di server provider',
            'do_refund': '1'
        }, follow_redirects=True)

        db.session.refresh(trx1)
        db.session.refresh(user)

        assert res1.status_code == 200
        assert trx1.status == 'FAILED'
        assert user.balance == bal_before + 12000.0, f"Expected {bal_before + 12000.0}, got {user.balance}"
        print(f"  [OK] Status berubah ke FAILED, saldo bertambah +Rp 12,000 (Saldo: Rp {user.balance:,.0f})")

        # ----------------------------------------------------------------------
        # TEST 2: User Normal - SUCCESS -> FAILED tanpa do_refund (do_refund=0)
        # ----------------------------------------------------------------------
        print("\n[Test 2] User Reguler: Ubah SUCCESS -> FAILED tanpa do_refund...")
        trx2 = Transaction(
            user_id=user.id,
            ref_id=f"TRX-TEST-{int(time.time())}-2",
            product_name="Indosat 25K",
            sku_code="isat25",
            target_number=test_phone,
            amount=26000.0,
            payment_method="SALDO",
            payment_status="PAID",
            status="SUCCESS"
        )
        db.session.add(trx2)
        db.session.commit()

        bal_before2 = user.balance
        res2 = client.post(f"/admin/transactions/update_status/{trx2.id}", data={
            'status': 'FAILED',
            'payment_status': 'PAID',
            'sn': 'Gagal tanpa refund',
            # do_refund tidak dikirim (unchecked)
        }, follow_redirects=True)

        db.session.refresh(trx2)
        db.session.refresh(user)

        assert trx2.status == 'FAILED'
        assert user.balance == bal_before2, f"Expected {bal_before2}, got {user.balance}"
        print(f"  [OK] Status berubah ke FAILED, saldo TIDAK bertambah (Tetap Rp {user.balance:,.0f})")

        # ----------------------------------------------------------------------
        # TEST 3: Kasir Cabang - SUCCESS -> FAILED dengan do_refund=1
        # ----------------------------------------------------------------------
        print("\n[Test 3] Kasir Cabang: Ubah SUCCESS -> FAILED dengan do_refund=1...")
        trx3 = Transaction(
            user_id=user.id,
            device_id=device.id,
            device_name=device.device_name,
            ref_id=f"TRX-TEST-{int(time.time())}-3",
            product_name="PLN 50K",
            sku_code="pln50",
            target_number="12345678901",
            amount=51000.0,
            payment_method="SALDO",
            payment_status="PAID",
            status="SUCCESS"
        )
        db.session.add(trx3)
        db.session.commit()

        dev_bal_before = device.branch_balance
        res3 = client.post(f"/admin/transactions/update_status/{trx3.id}", data={
            'status': 'FAILED',
            'payment_status': 'PAID',
            'sn': 'Token gagal refund ke cabang',
            'do_refund': '1'
        }, follow_redirects=True)

        db.session.refresh(trx3)
        db.session.refresh(device)

        assert trx3.status == 'FAILED'
        assert device.branch_balance == dev_bal_before + 51000.0, f"Expected {dev_bal_before + 51000.0}, got {device.branch_balance}"

        # Cek BranchMutation
        mut = BranchMutation.query.filter_by(device_id=device.id, type='REFUND').order_by(BranchMutation.id.desc()).first()
        assert mut is not None, "BranchMutation type REFUND tidak tercatat"
        assert mut.amount == 51000.0
        assert trx3.ref_id in mut.description
        print(f"  [OK] Saldo cabang kasir bertambah +Rp 51,000 (Saldo Cabang: Rp {device.branch_balance:,.0f})")
        print(f"  [OK] Mutasi cabang tercatat: {mut.description}")

        # ----------------------------------------------------------------------
        # TEST 4: Proteksi Double Refund pada Kasir Cabang
        # ----------------------------------------------------------------------
        print("\n[Test 4] Kasir Cabang: Coba refund ulang pada transaksi yang sudah FAILED...")
        dev_bal_before_dup = device.branch_balance
        res4 = client.post(f"/admin/transactions/update_status/{trx3.id}", data={
            'status': 'FAILED',
            'payment_status': 'PAID',
            'sn': 'Update SN saja',
            'do_refund': '1'
        }, follow_redirects=True)

        db.session.refresh(device)
        assert device.branch_balance == dev_bal_before_dup, "Saldo cabang bocor! Terjadi double refund!"
        print(f"  [OK] Double refund dicegah dengan aman. Saldo cabang tetap Rp {device.branch_balance:,.0f}")

        # ----------------------------------------------------------------------
        # TEST 5: Proteksi Tiket Deposit (DEPOSIT_SALDO)
        # ----------------------------------------------------------------------
        print("\n[Test 5] Proteksi Deposit: Coba refund pada tiket deposit...")
        trx_dep = Transaction(
            user_id=user.id,
            ref_id=f"DEP-TEST-{int(time.time())}",
            product_name="Deposit Saldo",
            sku_code="DEPOSIT_SALDO",
            target_number=test_phone,
            amount=50000.0,
            payment_method="QRIS",
            payment_status="PAID",
            status="SUCCESS"
        )
        db.session.add(trx_dep)
        db.session.commit()

        user_bal_before_dep = user.balance
        res5 = client.post(f"/admin/transactions/update_status/{trx_dep.id}", data={
            'status': 'FAILED',
            'payment_status': 'PAID',
            'do_refund': '1'
        }, follow_redirects=True)

        db.session.refresh(user)
        assert user.balance == user_bal_before_dep, "Tiket deposit tidak boleh di-refund saldo!"
        print(f"  [OK] Tiket deposit aman dari refund palsu. Saldo tetap Rp {user.balance:,.0f}")

        # ----------------------------------------------------------------------
        # TEST 6: Proteksi Transaksi UNPAID
        # ----------------------------------------------------------------------
        print("\n[Test 6] Proteksi UNPAID: Coba refund transaksi yang belum dibayar...")
        trx_unpaid = Transaction(
            user_id=user.id,
            ref_id=f"TRX-UNPAID-{int(time.time())}",
            product_name="XL 10K",
            sku_code="xl10",
            target_number=test_phone,
            amount=11000.0,
            payment_method="QRIS",
            payment_status="UNPAID",
            status="PENDING"
        )
        db.session.add(trx_unpaid)
        db.session.commit()

        user_bal_before_unpaid = user.balance
        res6 = client.post(f"/admin/transactions/update_status/{trx_unpaid.id}", data={
            'status': 'FAILED',
            'payment_status': 'UNPAID',
            'do_refund': '1'
        }, follow_redirects=True)

        db.session.refresh(user)
        assert user.balance == user_bal_before_unpaid, "Transaksi UNPAID tidak boleh di-refund!"
        print(f"  [OK] Transaksi UNPAID ditolak untuk refund. Saldo tetap Rp {user.balance:,.0f}")

        # Clean up test records
        try:
            db.session.delete(mut)
            db.session.delete(trx1)
            db.session.delete(trx2)
            db.session.delete(trx3)
            db.session.delete(trx_dep)
            db.session.delete(trx_unpaid)
            db.session.delete(device)
            db.session.delete(user)
            db.session.commit()
        except Exception:
            db.session.rollback()

    print("\n" + "=" * 70)
    print("  ALL 6/6 MANUAL REFUND TESTS PASSED SUCCESSFULLY! (100% PASS)")
    print("=" * 70)

if __name__ == '__main__':
    run_refund_tests()
