"""
Skrip pengujian otomatis untuk Standarisasi Kategori TV Berlangganan (/kategori/tv)
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app, db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction

def test_tv_category():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI STANDARISASI KATEGORI TV BERLANGGANAN")
    print("="*65)

    # 1. UJI GET /kategori/tv
    print("\n[1/4] Memeriksa Halaman /kategori/tv ...")
    res_page = client.get('/kategori/tv')
    assert res_page.status_code == 200, f"Halaman /kategori/tv harus mengembalikan 200 OK, didapat {res_page.status_code}"
    html = res_page.data.decode('utf-8')

    assert 'TV BERLANGGANAN' in html, "Judul kategori TV BERLANGGANAN harus ada"
    assert 'noHpInput' in html, "Elemen input nomor pelanggan noHpInput harus ada"
    assert 'K-VISION' in html and 'NEX PARABOLA' in html and 'TRANSVISION' in html and 'MATRIX' in html, "Seluruh tab provider TV harus ada"
    assert 'btn-card-beli' in html, "Tombol hijau BELI pada kartu produk harus ada sesuai standar pulsa.html"
    assert 'checkoutModal' in html, "Bottom-sheet modal checkoutModal harus ada"
    assert '/trx/checkout' in html, "Endpoint /trx/checkout harus terhubung"
    print("  [OK] Halaman /kategori/tv memuat antarmuka standar modern dengan tab provider & modal checkout!")

    # 2. UJI INTEGRITAS DATA PRODUK TV (ANTI-LEAK GAMES)
    print("\n[2/4] Memeriksa Daftar Produk TV & Pencegahan Kebocoran Game ...")
    assert 'kvision30d' in html or 'kvision180d' in html or 'KVISION' in html, "SKU TV harus ter-render dalam kartu produk"
    assert 'Razer Gold' not in html and 'Ragnarok' not in html, "Produk game (Razer/Ragnarok) TIDAK boleh bocor ke kategori TV"
    print("  [OK] Seluruh produk TV database ter-render bersih dari produk game!")

    # 3. UJI CHECKOUT TV VIA QRIS (MENGGUNAKAN AKUN MEMBER)
    print("\n[3/4] Menguji Alur Checkout Paket TV via QRIS ...")
    with app.app_context():
        user = User.query.first()
        assert user is not None
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    # Temukan SKU produk TV aktif
    with app.app_context():
        prod = Product.query.filter(
            Product.category.ilike('%tv%'),
            Product.is_active == True,
            Product.sell_price > 0
        ).first()
        assert prod is not None
        test_sku = prod.sku_code
        print(f"  Menggunakan SKU TV Uji: {test_sku} ({prod.name}) - Rp {prod.sell_price:,}")

    res_checkout_qris = client.post('/trx/checkout', json={
        'sku_code': test_sku,
        'target_number': '1234567890123',
        'payment_method': 'QRIS'
    })
    assert res_checkout_qris.status_code == 200, f"Checkout QRIS harus 200 OK, got: {res_checkout_qris.status_code}"
    data_qris = res_checkout_qris.get_json()
    assert data_qris['status'] == 'success', f"Checkout harus sukses, respon: {data_qris}"
    assert 'ref_id' in data_qris
    print(f"  [OK] Transaksi TV via QRIS sukses dibuat: {data_qris['ref_id']}")

    # 4. UJI INVOICE TRANSAKSI TV
    print("\n[4/4] Memeriksa Halaman Invoice Transaksi TV ...")
    res_inv = client.get(f"/trx/invoice/{data_qris['ref_id']}")
    assert res_inv.status_code == 200
    inv_html = res_inv.data.decode('utf-8')
    assert 'qris-container' in inv_html, "Barcode QRIS harus tampil pada invoice transaksi TV!"
    print(f"  [OK] Invoice QRIS transaksi TV terkonfirmasi valid & menampilkan barcode!")

    print("\n" + "="*65)
    print("  >>> STANDARISASI KATEGORI TV BERLANGGANAN SUKSES 100%! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_tv_category()

