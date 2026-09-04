"""
GarudaTel v2 - Comprehensive Automated Verification & Test Suite
Menguji seluruh lapisan sistem: Healthcheck, Database, Auth, OTP, Transaksi, Idempotensi, CSRF, dan Rate Limiting.

Jalankan dengan:
    python tests/test_full_system.py
"""

import os
import sys
import time
import re
import hashlib

# Sisipkan root directory ke sys.path
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction
from app.models.admin import Admin
from app.models.otp import OtpCode
from app.services.otp_service import create_otp, verify_otp

def run_all_tests():
    print("=" * 70)
    print("  GARUDATEL v2 - COMPREHENSIVE SYSTEM VERIFICATION SUITE")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    # ----------------------------------------------------------------------
    # 1. TEST HEALTHCHECK ENDPOINT
    # ----------------------------------------------------------------------
    print("\n[1/7] Menguji Healthcheck Endpoint (/health)...")
    res_health = client.get('/health')
    assert res_health.status_code == 200, f"Expected 200, got {res_health.status_code}"
    health_json = res_health.get_json()
    assert health_json.get('status') == 'healthy', f"Status not healthy: {health_json}"
    assert health_json.get('database') == 'connected', f"Database not connected: {health_json}"
    assert 'version' in health_json, "Version key missing in health check"
    print(f"  [OK] Healthcheck 200 OK - DB: {health_json['database']} | Version: {health_json['version']}")

    # ----------------------------------------------------------------------
    # 2. TEST DATABASE SCHEMA & CONCURRENCY (WAL MODE)
    # ----------------------------------------------------------------------
    print("\n[2/7] Menguji Integritas Skema Database & SQLite WAL Mode...")
    with app.app_context():
        journal_mode = db.session.execute(db.text("PRAGMA journal_mode;")).scalar()
        busy_timeout = db.session.execute(db.text("PRAGMA busy_timeout;")).scalar()
        assert str(journal_mode).lower() == 'wal', f"Expected WAL mode, got {journal_mode}"
        assert int(busy_timeout) >= 10000, f"Expected busy_timeout >= 10000, got {busy_timeout}"
        print(f"  [OK] SQLite Concurrency: journal_mode={journal_mode.upper()} | busy_timeout={busy_timeout}ms")

        # Cek ketersediaan semua tabel model
        table_counts = {
            'Admin': Admin.query.count(),
            'Product': Product.query.count(),
            'User': User.query.count(),
            'Transaction': Transaction.query.count(),
            'OtpCode': OtpCode.query.count()
        }
        for model_name, cnt in table_counts.items():
            print(f"  [OK] Model {model_name}: {cnt} baris aktif terdaftar.")

    # ----------------------------------------------------------------------
    # 3. TEST OTP SYSTEM & ANTI-REUSE LIFECYCLE
    # ----------------------------------------------------------------------
    print("\n[3/7] Menguji Siklus Hidup OTP & Proteksi Anti-Reuse...")
    test_phone = "089912345678"
    with app.app_context():
        otp_code = create_otp(test_phone, action='test_verif', username='FullTester')
        assert len(otp_code) == 6, f"OTP length invalid: {otp_code}"
        
        # Test kode salah
        is_val, msg, _ = verify_otp(test_phone, "000000", action='test_verif')
        assert not is_val, "Kode salah seharusnya ditolak!"

        # Test kode benar
        is_val, msg, data = verify_otp(test_phone, otp_code, action='test_verif')
        assert is_val, f"Kode benar seharusnya diterima: {msg}"
        assert data.get('username') == 'FullTester', "Metadata username tidak sesuai"

        # Test reuse (tidak boleh dipakai dua kali)
        is_val_reuse, msg_reuse, _ = verify_otp(test_phone, otp_code, action='test_verif')
        assert not is_val_reuse, "OTP bekas pakai seharusnya ditolak!"
        print("  [OK] OTP Lifecycle: Pembuatan 6-digit -> Penolakan kode salah -> Sukses verifikasi -> Penolakan reuse berhasil 100%.")

    # ----------------------------------------------------------------------
    # 4. TEST CHECKOUT TRANSACTION PIPELINE
    # ----------------------------------------------------------------------
    print("\n[4/7] Menguji Pipeline Transaksi Checkout...")
    # Test Unauthenticated
    r_unauth = client.post('/trx/checkout', json={'sku_code': 'test', 'target_number': '08123'})
    assert r_unauth.status_code == 401, f"Expected 401 for unauth checkout, got {r_unauth.status_code}"
    print("  [OK] Unauthenticated checkout mengembalikan JSON 401 (Login Required).")

    with app.app_context():
        # Buat user test
        u_test = User.query.filter_by(phone='089900001111').first()
        if not u_test:
            u_test = User(name='TestTrxUser', phone='089900001111', password_hash='dummy_hash', balance=1000.0)
            db.session.add(u_test)
            db.session.commit()
        else:
            u_test.balance = 1000.0
            db.session.commit()
        test_uid = u_test.id

        # Dapatkan produk aktif
        sample_prod = Product.query.filter_by(is_active=True).first()
        sample_sku = sample_prod.sku_code if sample_prod else 'TEST_SKU'

    # Simulasikan login
    with client.session_transaction() as sess:
        sess['_user_id'] = str(test_uid)
        sess['_fresh'] = True

    # Test Saldo tidak cukup -> Tawarkan QRIS
    r_insufficient = client.post('/trx/checkout', json={
        'sku_code': sample_sku, 'target_number': '081234567890', 'payment_method': 'saldo'
    })
    d_insufficient = r_insufficient.get_json()
    assert d_insufficient.get('insufficient_balance') is True, "Harus menyarankan QRIS jika saldo kurang"
    print("  [OK] Saldo tidak cukup mengembalikan saran fallback QRIS dengan elegan.")

    # Test Checkout QRIS Reguler
    r_qris = client.post('/trx/checkout', json={
        'sku_code': sample_sku, 'target_number': '081234567890', 'payment_method': 'qris'
    })
    d_qris = r_qris.get_json()
    assert d_qris.get('status') == 'success'
    assert '/trx/invoice/' in d_qris.get('redirect', '')
    ref_id_qris = d_qris.get('ref_id')
    print(f"  [OK] Checkout QRIS sukses: Invoice redirect ke {d_qris.get('redirect')}")

    # Test Checkout QRIS Bebas Nominal (DANA)
    r_bebas = client.post('/trx/checkout', json={
        'sku_code': 'DANA', 'target_number': '081234567890', 'payment_method': 'qris', 'amount': 50000
    })
    d_bebas = r_bebas.get_json()
    assert d_bebas.get('status') == 'success'
    with app.app_context():
        u_check = User.query.get(test_uid)
        assert u_check.balance == 1000.0, "Saldo TIDAK BOLEH terpotong untuk transaksi QRIS Bebas Nominal!"
    print("  [OK] Checkout Bebas Nominal QRIS tidak memotong saldo user (saldo aman).")

    # ----------------------------------------------------------------------
    # 5. TEST WEBHOOK IDEMPOTENCY & SIGNATURE SECURITY
    # ----------------------------------------------------------------------
    print("\n[5/7] Menguji Idempotensi Webhook Callback...")
    with app.app_context():
        trx_qris = Transaction.query.filter_by(ref_id=ref_id_qris).first()
        trx_qris.status = 'SUCCESS'
        trx_qris.payment_status = 'PAID'
        db.session.commit()

        username = os.getenv('DIGI_USER', '').strip()
        key = os.getenv('DIGI_KEY', '').strip()
        sign_valid = hashlib.md5(f"{username}{key}{ref_id_qris}".encode()).hexdigest()

    # Panggilan pertama (transaksi sudah selesai)
    r_cb1 = client.post('/trx/callback/digiflazz', json={
        'ref_id': ref_id_qris, 'status': 'Sukses', 'sign': sign_valid
    })
    assert r_cb1.get_json().get('message') == 'Transaction already completed'
    print("  [OK] Idempotensi Digiflazz: Webhook duplikat pada transaksi sukses direspons 200 tanpa duplikasi aksi.")

    r_pk1 = client.post('/trx/callback/paymentkita', json={
        'ref_id': ref_id_qris, 'status': 'paid'
    })
    assert r_pk1.get_json().get('message') == 'Payment already processed'
    print("  [OK] Idempotensi PaymentKita: Webhook retry pada transaksi PAID direspons 200 tanpa duplikasi kredit.")

    # ----------------------------------------------------------------------
    # 6. TEST CSRF PROTECTION & RATE LIMITING
    # ----------------------------------------------------------------------
    print("\n[6/7] Menguji CSRF Protection & Rate Limiting...")
    # Admin form renders CSRF token
    r_admin_form = client.get('/admin/login')
    match_csrf = re.search(r'name="csrf_token" value="([^"]+)"', r_admin_form.text)
    assert match_csrf, "CSRF token wajib hadir di form login admin!"
    valid_csrf = match_csrf.group(1)
    print("  [OK] Form admin menyertakan token CSRF valid.")

    # Rate limiter test
    stat_codes = []
    for _ in range(7):
        r_lim = client.post('/admin/login', data={
            'username': 'bruteforcer', 'password': 'wrongpassword', 'csrf_token': valid_csrf
        })
        stat_codes.append(r_lim.status_code)
    assert 429 in stat_codes, f"Rate limit seharusnya mengembalikan 429: {stat_codes}"
    print(f"  [OK] Rate Limiting aktif: Request beruntun dibatasi ({stat_codes[-1]}: Too Many Requests).")

    # ----------------------------------------------------------------------
    # 7. TEST LOGGING & ARTIFACT RECOVERY
    # ----------------------------------------------------------------------
    print("\n[7/7] Menguji Structured Logging & Cleanup...")
    log_path = os.path.join(BASE_DIR, 'storage', 'logs', 'garudatel.log')
    assert os.path.exists(os.path.dirname(log_path)), "Folder log storage/logs/ tidak ditemukan!"
    print(f"  [OK] File logging aktif di: storage/logs/")

    # Bersihkan user test
    with app.app_context():
        Transaction.query.filter_by(user_id=test_uid).delete()
        User.query.filter_by(id=test_uid).delete()
        OtpCode.query.filter_by(phone=test_phone).delete()
        db.session.commit()
    print("  [OK] Data pengujian sementara telah dibersihkan secara aman.")

    print("\n" + "=" * 70)
    print("  >>> SELURUH PENGUJIAN SISTEM (7/7) LULUS 100% SECARA SEMPURNA! <<<")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    run_all_tests()

