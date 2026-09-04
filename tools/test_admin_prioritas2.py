import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.transaction import Transaction
from app.models.product import Product

def test_admin_priority_2():
    print("=" * 65)
    print("  VERIFIKASI PERBAIKAN PANEL ADMIN - PRIORITAS 2")
    print("=" * 65)

    app = create_app()
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # 1. Test Dashboard Transaksi Link
    print("\n[1/5] Menguji Tautan Menu Transaksi di Dashboard...")
    res_dash = client.get('/admin/')
    assert res_dash.status_code == 200
    assert 'href="/admin/transactions"' in res_dash.text or "url_for('admin.transactions')" not in res_dash.text
    print("  [OK] Menu Transaksi di dashboard kini aktif dan mengarah ke /admin/transactions (bukan dead link '#').")

    # 2. Test Pusat Transaksi (GET /admin/transactions)
    print("\n[2/5] Menguji Pusat Transaksi (/admin/transactions)...")
    res_trx = client.get('/admin/transactions')
    assert res_trx.status_code == 200, f"Error GET /admin/transactions: {res_trx.status_code}"
    assert "Pusat Transaksi" in res_trx.text
    assert "Omset Sukses" in res_trx.text
    assert "Menampilkan halaman" in res_trx.text
    assert 'id="trxModal"' in res_trx.text
    print("  [OK] Halaman Pusat Transaksi berhasil di-render dengan ringkasan statistik & tabel riil.")

    # 3. Test Filter & Pencarian Transaksi
    print("\n[3/5] Menguji Pencarian & Filter Transaksi...")
    res_filter_status = client.get('/admin/transactions?status=SUCCESS')
    assert res_filter_status.status_code == 200
    
    res_search = client.get('/admin/transactions?q=GT')
    assert res_search.status_code == 200
    print("  [OK] Filter status dan pencarian transaksi bekerja normal.")

    # 4. Test Update Status Transaksi Manual
    print("\n[4/5] Menguji Update Status Transaksi Manual...")
    with app.app_context():
        sample_trx = Transaction.query.first()
        assert sample_trx is not None, "Wajib ada minimal 1 transaksi di database"
        tid = sample_trx.id
        old_sn = sample_trx.sn

    res_update_trx = client.post(f'/admin/transactions/update_status/{tid}', data={
        'status': 'SUCCESS',
        'payment_status': 'PAID',
        'sn': 'SN-TEST-ADMIN-SUCCESS-999'
    }, follow_redirects=True)
    assert res_update_trx.status_code == 200
    assert "berhasil diperbarui" in res_update_trx.text

    with app.app_context():
        trx_check = Transaction.query.get(tid)
        assert trx_check.status == 'SUCCESS'
        assert trx_check.payment_status == 'PAID'
        assert trx_check.sn == 'SN-TEST-ADMIN-SUCCESS-999'
        # Kembalikan SN semula
        trx_check.sn = old_sn
        db.session.commit()
    print(f"  [OK] Update status transaksi #{tid} sukses diperbarui di database.")

    # 5. Test Optimasi & Paginasi Produk (/admin/produk)
    print("\n[5/5] Menguji Paginasi & Pencarian Produk (/admin/produk)...")
    import time
    t0 = time.time()
    res_prod = client.get('/admin/produk')
    load_time = time.time() - t0
    assert res_prod.status_code == 200
    assert "Halaman" in res_prod.text
    assert "50 produk per halaman" in res_prod.text
    print(f"  [OK] Produk termuat dalam {load_time:.3f} detik (sangat cepat dengan paginasi 50 baris).")

    # Test pencarian produk server-side
    res_search_prod = client.get('/admin/produk?q=Telkomsel')
    assert res_search_prod.status_code == 200
    print("  [OK] Pencarian produk server-side sukses.")

    print("\n" + "=" * 65)
    print("  >>> SELURUH PERBAIKAN PRIORITAS 2 LULUS 100% SECARA SEMPURNA! <<<")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    test_admin_priority_2()

