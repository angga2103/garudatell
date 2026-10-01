import os
import sys
import hashlib
import json
import time

# Pastikan folder project masuk sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.merchant import MerchantApiKey
from app.models.product import Product
from app.services.merchant_service import generate_merchant_credentials

def run_tests():
    app = create_app()
    with app.app_context():
        print("=== 1. VERIFIKASI TABEL & MIGRATION DATABASE ===")
        db.create_all()
        inspector = db.inspect(db.engine)
        tables = inspector.get_table_names()
        assert 'merchant_api_keys' in tables, "Tabel merchant_api_keys belum terbuat!"
        print(" [PASS] Tabel merchant_api_keys berhasil diverifikasi di database.")

        print("\n=== 2. PERSIAPAN DATA TEST MERCHANT ===")
        # Cari user untuk testing
        user = User.query.first()
        if not user:
            print(" [INFO] Membuat user dummy untuk test.")
            user = User(name="Test POS Cashier", phone="081299990001", role="user", balance=250000.0)
            db.session.add(user)
            db.session.commit()

        # Buat merchant key jika belum ada
        mch = MerchantApiKey.query.filter_by(user_id=user.id, is_active=True).first()
        if not mch:
            mch, err = generate_merchant_credentials(user.id, name="Test Kasir POS", webhook_url="http://localhost:3002/api/ppob/webhook")
            assert err is None, f"Gagal membuat merchant key: {err}"
        print(f" [PASS] Merchant Key siap: {mch.merchant_id} | User: {user.name} (Balance: Rp {user.balance:,.0f})")

        client = app.test_client()

        print("\n=== 3. TEST AUTHENTICATION (X-API-KEY) ===")
        # Tanpa header
        res = client.post('/api/v1/profile/balance', json={"merchant_id": mch.merchant_id})
        assert res.status_code == 401, f"Expected 401 without API key, got {res.status_code}"
        print(" [PASS] Ditolak 401 saat request tanpa header X-API-KEY.")

        # Key salah
        res = client.post('/api/v1/profile/balance', headers={'X-API-KEY': 'INVALID_KEY_XYZ'})
        assert res.status_code == 401, f"Expected 401 with invalid API key, got {res.status_code}"
        print(" [PASS] Ditolak 401 saat request dengan API Key salah.")

        print("\n=== 4. TEST CEK SALDO DENGAN SIGNATURE ===")
        # Signature salah
        res = client.post('/api/v1/profile/balance', headers={'X-API-KEY': mch.api_key}, json={
            "merchant_id": mch.merchant_id,
            "signature": "SALAH_SIGNATURE_123"
        })
        assert res.status_code == 403, f"Expected 403 with bad signature, got {res.status_code}"
        print(" [PASS] Ditolak 403 saat signature MD5 dimanipulasi.")

        # Signature benar: MD5(merchant_id + secret_key + "balance")
        valid_sign = hashlib.md5(f"{mch.merchant_id}{mch.secret_key}balance".encode()).hexdigest()
        res = client.post('/api/v1/profile/balance', headers={'X-API-KEY': mch.api_key}, json={
            "merchant_id": mch.merchant_id,
            "signature": valid_sign
        })
        assert res.status_code == 200, f"Expected 200 with valid signature, got {res.status_code}"
        data = res.get_json()
        assert data['status'] == 'success'
        assert data['merchant_id'] == mch.merchant_id
        assert 'balance' in data
        print(f" [PASS] Sukses ambil saldo: Rp {data['balance']:,.0f} (Merchant: {data['merchant_id']})")

        print("\n=== 5. TEST SINKRONISASI KATALOG PRODUK ===")
        res = client.get('/api/v1/products', headers={'X-API-KEY': mch.api_key})
        assert res.status_code == 200, f"Expected 200 on /products, got {res.status_code}"
        p_data = res.get_json()
        assert p_data['status'] == 'success'
        print(f" [PASS] Sukses sinkronisasi {p_data['total']} produk aktif.")

        print("\n=== 6. TEST IDEMPOTENCY GUARD ===")
        ref_id_test = f"IDEMPOTENT-TEST-{int(user.id)}-9988"
        sign_idem = hashlib.md5(f"{mch.merchant_id}{mch.secret_key}{ref_id_test}".encode()).hexdigest()

        # Buat dummy transaction existing
        from app.models.transaction import Transaction
        old_trx = Transaction.query.filter_by(ref_id=ref_id_test).first()
        if not old_trx:
            old_trx = Transaction(
                user_id=user.id,
                ref_id=ref_id_test,
                product_name="Pulsa Test 5000",
                sku_code="xld5",
                target_number="087812345678",
                amount=5800.0,
                payment_method="API_GATEWAY",
                payment_status="PAID",
                status="SUCCESS",
                sn="SN-TEST-881122"
            )
            db.session.add(old_trx)
            db.session.commit()

        # Request create dengan ref_id yang sama persis
        res = client.post('/api/v1/transaction/create', headers={'X-API-KEY': mch.api_key}, json={
            "merchant_id": mch.merchant_id,
            "buyer_sku_code": "xld5",
            "customer_no": "087812345678",
            "ref_id": ref_id_test,
            "sign": sign_idem
        })
        assert res.status_code == 200, f"Expected 200 idempotency return, got {res.status_code}"
        res_json = res.get_json()
        assert res_json['data']['sn'] == "SN-TEST-881122"
        print(" [PASS] Idempotency Guard bekerja sempurna: Transaksi dengan ref_id sama mengembalikan status tanpa double-charge.")

        print("\n=== 7. TEST CEK STATUS TRANSAKSI ===")
        res_stat = client.get(f'/api/v1/transaction/status/{ref_id_test}', headers={'X-API-KEY': mch.api_key})
        assert res_stat.status_code == 200
        stat_data = res_stat.get_json()
        assert stat_data['data']['ref_id'] == ref_id_test
        print(f" [PASS] Cek status transaksi sukses: Ref {ref_id_test} Status: {stat_data['data']['status']}")

        print("\n=== 8. TEST VALIDASI SALDO TIDAK CUKUP ===")
        # Ambil produk dengan harga lebih besar dari saldo user
        expensive_prod = Product.query.filter(Product.is_active == True, Product.sell_price > user.balance).first()
        if not expensive_prod:
            expensive_prod = Product(sku_code="TEST_EXPENSIVE_999", name="Paket Sultan Test", category="PULSA", brand="TEST", base_price=1000000.0, sell_price=1005000.0, is_active=True)
            db.session.add(expensive_prod)
            db.session.commit()

        ref_expensive = f"EXP-TEST-{int(time.time()*1000)}"
        sign_exp = hashlib.md5(f"{mch.merchant_id}{mch.secret_key}{ref_expensive}".encode()).hexdigest()
        res_exp = client.post('/api/v1/transaction/create', headers={'X-API-KEY': mch.api_key}, json={
            "merchant_id": mch.merchant_id,
            "buyer_sku_code": expensive_prod.sku_code,
            "customer_no": "087812345678",
            "ref_id": ref_expensive,
            "sign": sign_exp
        })
        assert res_exp.status_code == 400
        assert "tidak mencukupi" in res_exp.get_json().get("message", "")
        print(f" [PASS] Validasi saldo berhasil menolak transaksi saat saldo kurang (Rp {user.balance:,.0f} < Rp {expensive_prod.sell_price:,.0f}).")

        print("\n========================================================")
        print(" ALL 8 MERCHANT API TESTS PASSED SUCCESSFULLY! (100%)")
        print("========================================================")

if __name__ == '__main__':
    run_tests()
