import os
import sys
from unittest.mock import patch, MagicMock

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.product import Product
from app.services.pakasir_service import PakasirService

def test_pakasir_gateway():
    print("=" * 70)
    print("  VERIFIKASI INTEGRASI PAYMENT GATEWAY PAKASIR & GATEWAY SWITCHER")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    # 1. Uji PakasirService secara unit
    print("\n[1/5] Menguji PakasirService...")
    ps = PakasirService({'project': 'garuda-store', 'api_key': 'pks_live_123456'})
    
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "payment": {
            "payment_method": "qris",
            "payment_number": "00020101021226610016ID.CO.SHOPEE.WWW01189360091800216",
            "total_payment": 25000,
            "expired_at": "2026-09-03T18:00:00+07:00"
        }
    }

    with patch('requests.post', return_value=mock_resp):
        res = ps.create_qris("GT-TEST-123", 25000)
        assert res['status'] is True
        assert "00020101021226610016" in res['qr_string']
        assert "api.qrserver.com" in res['qr_url']
        print("  [OK] PakasirService.create_qris sukses membuat QR string dan URL gambar QR.")

    with patch('requests.get') as mock_get:
        mock_get.return_value.status_code = 200
        ok, msg = ps.test_connection()
        assert ok is True
        assert "Berhasil" in msg
        print("  [OK] PakasirService.test_connection sukses memverifikasi kredensial.")

    # 2. Uji Switcher Payment Gateway dari Panel Admin
    print("\n[2/5] Menguji Pengalihan Gateway Aktif oleh Admin (/admin/save_config)...")
    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # Alihkan ke Pakasir
    res_switch_pk = client.post('/admin/save_config', data={
        'form_type': 'switch_gateway',
        'active_payment_gateway': 'pakasir'
    }, follow_redirects=True)
    assert res_switch_pk.status_code == 200
    assert "dialihkan ke PAKASIR" in res_switch_pk.text
    print("  [OK] Admin berhasil mengalihkan gateway aktif ke PAKASIR.")

    # Cek tampilan dashboard admin
    res_dash = client.get('/admin/')
    assert res_dash.status_code == 200
    assert "AKTIF: PAKASIR" in res_dash.text
    print("  [OK] Dashboard admin menampilkan status AKTIF: PAKASIR.")

    # 3. Uji /trx/generate_qris saat Pakasir Aktif
    print("\n[3/5] Menguji Dispatcher /trx/generate_qris/<ref_id> dengan Pakasir...")
    with app.app_context():
        test_u = User.query.first()
        uid = test_u.id

    # Login sebagai user
    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['admin_logged_in'] = False

    import time
    test_ref = f"GT-PKS-TEST-{int(time.time()*1000)}"
    with app.app_context():
        # Bersihkan jika ada record test sebelumnya
        Transaction.query.filter(Transaction.ref_id.like("GT-PKS-TEST-%")).delete()
        db.session.commit()
    with app.app_context():
        real_prod = Product.query.first()
        prod_sku = real_prod.sku_code if real_prod else "TEST_SKU"
        # Buat transaksi dummy UNPAID
        trx = Transaction(
            ref_id=test_ref,
            user_id=uid,
            sku_code=prod_sku,
            product_name="Pulsa Test 10k",
            target_number="08123456789",
            amount=12000,
            payment_method="QRIS",
            payment_status="UNPAID",
            status="PENDING"
        )
        db.session.add(trx)
        db.session.commit()

    with patch('app.services.pakasir_service.PakasirService.create_qris') as mock_pks_create:
        mock_pks_create.return_value = {
            'status': True,
            'qr_url': 'https://api.qrserver.com/test-qr.png',
            'qr_string': '00020101021226610016ID...',
            'expired_at': '2026-09-03T18:00:00'
        }
        res_gq = client.get(f'/trx/generate_qris/{test_ref}')
        assert res_gq.status_code == 200
        json_data = res_gq.get_json()
        assert json_data['status'] == 'success'
        assert json_data['gateway'] == 'pakasir'
        assert json_data['qr_url'] == 'https://api.qrserver.com/test-qr.png'
        print("  [OK] Endpoint /trx/generate_qris otomatis memanggil Pakasir dan mengembalikan data QRIS!")

    # 4. Uji Webhook Callback Pakasir (/trx/callback/pakasir)
    print("\n[4/5] Menguji Webhook Callback Pakasir (/trx/callback/pakasir)...")
    # Set mock project slug
    os.environ['PAKASIR_PROJECT'] = 'garuda-store'

    with patch('app.services.digiflazz.create_transaction') as mock_digi:
        mock_digi.return_value = {
            'data': {'status': 'Sukses', 'sn': 'SN-PKS-999888'}
        }
        
        # Kirim webhook pembayaran completed
        res_wb = client.post('/trx/callback/pakasir', json={
            'amount': 12000,
            'order_id': test_ref,
            'project': 'garuda-store',
            'status': 'completed',
            'payment_method': 'qris',
            'completed_at': '2026-09-03T15:00:00+07:00'
        })
        assert res_wb.status_code == 200
        assert res_wb.get_json()['status'] == 'success'

    # Verifikasi status transaksi di database
    with app.app_context():
        trx_done = Transaction.query.filter_by(ref_id=test_ref).first()
        assert trx_done.payment_status == 'PAID'
        assert trx_done.status == 'SUCCESS'
        assert trx_done.sn == 'SN-PKS-999888'
        print("  [OK] Transaksi otomatis ditandai PAID dan diproses sukses ke Digiflazz!")

    # Uji Idempotensi Webhook (Panggilan berulang tidak menyebabkan duplikasi)
    res_wb_retry = client.post('/trx/callback/pakasir', json={
        'amount': 12000,
        'order_id': test_ref,
        'project': 'garuda-store',
        'status': 'completed'
    })
    assert res_wb_retry.status_code == 200
    assert "already processed" in res_wb_retry.get_json()['message']
    print("  [OK] Idempotensi Webhook Pakasir: Panggilan duplikat direspons aman tanpa error.")

    # 5. Uji Kemampuan Kembali ke PaymentKita
    print("\n[5/5] Menguji Pengalihan Kembali ke PaymentKita...")
    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    res_switch_pk2 = client.post('/admin/save_config', data={
        'form_type': 'switch_gateway',
        'active_payment_gateway': 'paymentkita'
    }, follow_redirects=True)
    assert res_switch_pk2.status_code == 200
    assert "dialihkan ke PAYMENTKITA" in res_switch_pk2.text

    # Verifikasi dashboard kembali ke PaymentKita
    res_dash2 = client.get('/admin/')
    assert "AKTIF: PAYMENTKITA" in res_dash2.text
    print("  [OK] Admin dapat beralih bolak-balik antara PaymentKita dan Pakasir secara sempurna!")

    # Cleanup test transaction
    with app.app_context():
        t_del = Transaction.query.filter_by(ref_id=test_ref).first()
        if t_del:
            db.session.delete(t_del)
            db.session.commit()

    print("\n" + "=" * 70)
    print("  >>> SELURUH PENGUJIAN INTEGRASI PAKASIR LULUS 100% SECARA SEMPURNA! <<<")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    test_pakasir_gateway()
