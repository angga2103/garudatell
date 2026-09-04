"""
Skrip pengujian otomatis untuk Standarisasi Kategori E-Money (/kategori/emoney)
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app, db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction

def test_emoney_category():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI STANDARISASI KATEGORI E-WALLET & E-MONEY")
    print("="*65)

    # 1. UJI GET /kategori/emoney
    print("\n[1/4] Memeriksa Halaman /kategori/emoney ...")
    res_page = client.get('/kategori/emoney')
    assert res_page.status_code == 200, f"Halaman /kategori/emoney harus mengembalikan 200 OK, didapat {res_page.status_code}"
    html = res_page.data.decode('utf-8')

    assert 'E-WALLET' in html and 'E-MONEY' in html, "Judul kategori E-WALLET & E-MONEY harus ada"
    assert 'Aktivasi Perdana' not in html, "Produk perdana tidak boleh masuk ke kategori e-money"
    assert 'phoneInput' in html or 'noHpInput' in html, "Elemen input nomor akun harus ada"
    assert 'DANA' in html and 'GOPAY' in html and 'OVO' in html and 'SHOPEEPAY' in html and 'LINKAJA' in html, "Seluruh tab provider harus ada"
    assert 'btn-card-beli' in html, "Tombol BELI pada kartu produk harus ada sesuai referensi gambar 1"
    assert 'checkoutModal' in html, "Bottom-sheet modal checkoutModal harus ada"
    assert '/trx/checkout' in html, "Endpoint /trx/checkout harus terhubung"
    print("  [OK] Halaman /kategori/emoney memuat antarmuka standar modern dengan tab provider & modal checkout!")

    # 2. UJI PRODUK AKTIF DATABASE DALAM RENDER
    print("\n[2/4] Memeriksa Daftar Produk Database yang Ter-render ...")
    assert 'data-sku="dana20"' in html or 'data-sku="DN20"' in html or 'data-sku="GP10"' in html, "SKU e-wallet harus ter-render dalam kartu produk"
    assert 'data-provider="DANA"' in html, "Atribut data-provider DANA harus ada"
    assert 'data-provider="GOPAY"' in html, "Atribut data-provider GOPAY harus ada"
    assert 'data-provider="OVO"' in html, "Atribut data-provider OVO harus ada"
    assert 'data-provider="SHOPEEPAY"' in html, "Atribut data-provider SHOPEEPAY harus ada"
    print("  [OK] Seluruh produk aktif database ter-render lengkap dengan atribut SKU & Provider!")

    # 3. UJI CHECKOUT E-MONEY VIA QRIS (MENGGUNAKAN AKUN MEMBER)
    print("\n[3/4] Menguji Alur Checkout Produk E-Money via QRIS ...")
    with app.app_context():
        user = User.query.first()
        assert user is not None
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    # Temukan SKU produk e-money aktif
    with app.app_context():
        prod = Product.query.filter(
            Product.category.ilike('%e-money%'),
            Product.is_active == True,
            Product.sell_price > 0
        ).first()
        assert prod is not None
        test_sku = prod.sku_code
        print(f"  Menggunakan SKU Uji: {test_sku} ({prod.name}) - Rp {prod.sell_price:,}")

    res_checkout_qris = client.post('/trx/checkout', json={
        'sku_code': test_sku,
        'target_number': '081234567890',
        'payment_method': 'QRIS'
    })
    assert res_checkout_qris.status_code == 200, f"Checkout QRIS harus 200 OK, got: {res_checkout_qris.status_code}"
    data_qris = res_checkout_qris.get_json()
    assert data_qris['status'] == 'success', f"Checkout harus sukses, respon: {data_qris}"
    assert 'ref_id' in data_qris
    print(f"  [OK] Transaksi E-Money via QRIS sukses dibuat: {data_qris['ref_id']}")

    # 4. UJI INVOICE TRANSAKSI E-MONEY
    print("\n[4/4] Memeriksa Halaman Invoice Transaksi E-Money ...")
    res_inv = client.get(f"/trx/invoice/{data_qris['ref_id']}")
    assert res_inv.status_code == 200
    inv_html = res_inv.data.decode('utf-8')
    assert 'qris-container' in inv_html, "Barcode QRIS harus tampil pada invoice transaksi e-money!"
    print(f"  [OK] Invoice QRIS transaksi e-money terkonfirmasi valid & menampilkan barcode!")

    print("\n" + "="*65)
    print("  >>> STANDARISASI KATEGORI E-MONEY SUKSES 100%! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_emoney_category()
