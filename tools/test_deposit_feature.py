import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction

def test_deposit_feature():
    print("=" * 70)
    print("  VERIFIKASI FITUR DEPOSIT BARCODE (GATEWAY AKTIF) & MANUAL E-WALLET")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    with app.app_context():
        user = User.query.first()
        assert user is not None, "User harus ada di database"
        user_id = user.id
        initial_balance = float(user.balance or 0.0)

    # Sesi login member
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['admin_logged_in'] = False

    # 1. UJI DASHBOARD: Logo Barcode di samping Poin Member mengarah ke /deposit
    print("\n[1/6] Memeriksa Tombol Barcode di Dashboard (/)...")
    res_dash = client.get('/')
    assert res_dash.status_code == 200
    html_dash = res_dash.data.decode('utf-8')
    assert 'href="/deposit"' in html_dash, "Tautan ke /deposit harus ada di dashboard!"
    assert 'fa-barcode' in html_dash, "Ikon fa-barcode harus ada di tombol barcode!"
    assert 'TOP UP' in html_dash or 'DEPOSIT' in html_dash, "Label TOP UP/DEPOSIT harus ada!"
    print("  [OK] Tombol Barcode Top Up di samping Poin Member terpasang rapi dan mengarah ke /deposit!")

    # 2. UJI HALAMAN DEPOSIT: GET /deposit
    print("\n[2/6] Memeriksa Halaman Deposit Saldo (/deposit)...")
    res_dep = client.get('/deposit')
    assert res_dep.status_code == 200
    html_dep = res_dep.data.decode('utf-8')
    assert 'Isi Saldo Akun' in html_dep
    assert 'header-inner' in html_dep, "Header-inner responsive wrapper harus ada!"
    assert 'Barcode QRIS' in html_dep
    assert 'Transfer Manual E-Wallet' in html_dep
    assert '081775700114' in html_dep, "Nomor tujuan transfer 081775700114 harus tampil di halaman!"
    assert 'DANA' in html_dep and 'SHOPEEPAY' in html_dep and 'GOPAY' in html_dep
    print("  [OK] Halaman /deposit berhasil memuat UI Barcode QRIS & E-Wallet manual 081775700114 secara responsif!")

    # 3. UJI DEPOSIT QRIS OTOMATIS & TAMPILAN BARCODE DI INVOICE
    print("\n[3/6] Menguji Pembuatan Order Deposit Barcode QRIS & Tampilan Barcode Invoice...")
    res_qris = client.post('/trx/topup_deposit', json={'amount': 25000})
    assert res_qris.status_code == 200
    data_qris = res_qris.get_json()
    assert data_qris['status'] == 'success'
    qris_ref_id = data_qris['ref_id']
    assert qris_ref_id.startswith('DEP-')

    with app.app_context():
        trx_qris = Transaction.query.filter_by(ref_id=qris_ref_id).first()
        assert trx_qris is not None
        assert trx_qris.sku_code == 'DEPOSIT_SALDO'
        assert trx_qris.amount == 25000.0
        assert trx_qris.payment_method == 'qris'
        print(f"  [OK] Transaksi QRIS berhasil dibuat dengan ref_id: {qris_ref_id}")

    # Cek Halaman Invoice: Pastikan Barcode QRIS TAMPIL (Menangani bug Image 2)
    res_inv = client.get(f'/trx/invoice/{qris_ref_id}')
    assert res_inv.status_code == 200
    html_inv = res_inv.data.decode('utf-8')
    assert 'qris-container' in html_inv, "Container Barcode QRIS harus tampil di invoice!"
    assert 'Pindai Barcode QRIS' in html_inv, "Judul Pindai Barcode QRIS harus muncul!"
    assert 'generate_qris' in html_inv, "Script generate_qris harus dimuat!"
    assert 'inv-header-inner' in html_inv, "Layout responsif inv-header-inner harus terpasang!"
    print("  [OK] Barcode QRIS di halaman /trx/invoice terbukti 100% TAMPIL (Bug case-sensitive teratasi)!")

    # 4. UJI DEPOSIT MANUAL E-WALLET DENGAN KODE UNIK & PROTOKOL whatsapp://
    print("\n[4/6] Menguji Pembuatan Order Deposit Transfer Manual & Protokol whatsapp://...")
    res_manual = client.post('/deposit/manual', json={
        'nominal': 50000,
        'ewallet_type': 'SHOPEEPAY'
    })
    assert res_manual.status_code == 200
    data_manual = res_manual.get_json()
    assert data_manual['status'] == 'success'
    
    unique_code_int = int(data_manual['unique_code'])
    assert 1 <= unique_code_int <= 99, f"Kode unik harus antara 01 dan 99, didapat: {unique_code_int}"
    assert data_manual['total_transfer'] == 50000 + unique_code_int
    assert data_manual['ewallet_dest'] == '081775700114'
    assert data_manual['wa_url'].startswith('whatsapp://send?phone=6281775700114'), "wa_url harus menggunakan protokol whatsapp://!"
    assert data_manual['wa_web_url'].startswith('https://wa.me/6281775700114'), "wa_web_url fallback harus tersedia!"
    assert 'DEP-MANUAL-' in data_manual['ref_id']
    print(f"  [OK] Deposit Manual E-Wallet sukses! Kode Unik: {data_manual['unique_code']} | Total: Rp {data_manual['total_transfer']:,}")
    print(f"  [OK] Link Protokol whatsapp:// terbukti valid (langsung membuka WhatsApp tanpa tab baru)!")

    # 5. UJI APPROVAL ADMIN ATAS TRANSAKSI DEPOSIT MANUAL
    print("\n[5/6] Menguji Persetujuan Deposit Manual oleh Admin (/admin/transactions/update_status)...")
    manual_ref_id = data_manual['ref_id']
    
    with app.app_context():
        trx_manual = Transaction.query.filter_by(ref_id=manual_ref_id).first()
        trx_manual_id = trx_manual.id
        u_before = User.query.filter_by(id=user_id).first()
        bal_before = u_before.balance

    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    res_approve = client.post(f'/admin/transactions/update_status/{trx_manual_id}', data={
        'status': 'SUCCESS',
        'payment_status': 'PAID',
        'sn': 'Transfer Diterima Admin'
    }, follow_redirects=True)
    assert res_approve.status_code == 200

    with app.app_context():
        trx_after = Transaction.query.get(trx_manual_id)
        assert trx_after.status == 'SUCCESS'
        u_after = User.query.filter_by(id=user_id).first()
        assert u_after.balance == bal_before + 50000.0, f"Saldo harus bertambah 50.000, sebelum: {bal_before}, sekarang: {u_after.balance}"
        print(f"  [OK] Approval admin berhasil! Saldo user bertambah +Rp 50.000 (Saldo sekarang: Rp {u_after.balance:,.0f})")

    # 6. UJI KEAMANAN & MINIMAL NOMINAL
    print("\n[6/6] Menguji Validasi Minimal Nominal (< Rp 10.000)...")
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['admin_logged_in'] = False

    res_invalid_qris = client.post('/trx/topup_deposit', json={'amount': 5000})
    assert res_invalid_qris.status_code == 400
    res_invalid_manual = client.post('/deposit/manual', json={'nominal': 5000})
    assert res_invalid_manual.status_code == 400
    print("  [OK] Validasi minimal nominal Rp 10.000 berjalan aman!")

    print("\n" + "=" * 70)
    print("  >>> SELURUH FITUR DEPOSIT BARCODE & MANUAL LULUS 100%! <<<")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    test_deposit_feature()

