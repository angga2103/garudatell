"""
Skrip pengujian otomatis untuk Optimasi & Standarisasi Kategori Voucher Game (/kategori/games)
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app, db
from app.models.user import User
from app.models.product import Product
from app.models.transaction import Transaction

def test_games_category():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI OPTIMASI & STANDARISASI KATEGORI VOUCHER GAME")
    print("="*65)

    # 1. UJI GET /kategori/games (DEFAULT MOBILE LEGENDS DUAL INPUT)
    print("\n[1/4] Memeriksa Halaman /kategori/games (Default ML Dual Input) ...")
    res_page = client.get('/kategori/games')
    assert res_page.status_code == 200, f"Halaman /kategori/games harus mengembalikan 200 OK, didapat {res_page.status_code}"
    html = res_page.data.decode('utf-8')

    assert 'VOUCHER' in html and 'TOP UP GAME' in html, "Judul kategori VOUCHER & TOP UP GAME harus ada"
    assert 'userIdInput' in html and 'zoneIdInput' in html, "Elemen input User ID & Zone ID harus ada"
    assert 'slider-arrow-btn' in html and 'slideTabs' in html, "Tombol dan fungsi slider geser tab game harus ada"
    assert 'Mobile Legends' in html and 'Free Fire' in html and 'PUBG Mobile' in html, "Seluruh tab game populer harus ada di slider"
    assert 'gameBrandSelect' in html, "Dropdown 99 game lengkap harus ada"
    assert 'btn-card-beli' in html, "Tombol hijau BELI pada kartu produk harus ada sesuai standar pulsa.html"
    assert 'checkoutModal' in html, "Bottom-sheet modal checkoutModal harus ada"
    assert '/trx/checkout' in html, "Endpoint /trx/checkout harus terhubung"
    print("  [OK] Halaman /kategori/games memuat antarmuka standar modern dengan dual input, slider tab & modal checkout!")

    # 2. UJI SWITCH GAME SINGLE INPUT (FREE FIRE)
    print("\n[2/4] Menguji Switch Game Single Input (/kategori/games?game=FF) ...")
    res_ff = client.get('/kategori/games?game=FF')
    assert res_ff.status_code == 200
    html_ff = res_ff.data.decode('utf-8')
    assert 'display: none;' in html_ff and 'zoneInputCol' in html_ff, "Kolom Zone ID harus disembunyikan untuk Free Fire"
    print("  [OK] Switch game ke Free Fire berhasil dan otomatis menyembunyikan kolom Zone ID!")

    # 3. UJI CHECKOUT PRODUK GAME VIA QRIS (MENGGUNAKAN AKUN MEMBER)
    print("\n[3/4] Menguji Alur Checkout Top Up Game via QRIS ...")
    with app.app_context():
        user = User.query.first()
        assert user is not None
        user_id = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True

    # Temukan SKU produk game aktif
    with app.app_context():
        prod = Product.query.filter(
            (Product.category.ilike('%game%') | Product.category.ilike('%voucher%')),
            Product.brand.ilike('VIP-%'),
            Product.is_active == True,
            Product.sell_price > 0
        ).first()
        assert prod is not None
        test_sku = prod.sku_code
        print(f"  Menggunakan SKU Game Uji: {test_sku} ({prod.name}) - Rp {prod.sell_price:,}")

    res_checkout_qris = client.post('/trx/checkout', json={
        'sku_code': test_sku,
        'target_number': '12345678(2123)',
        'payment_method': 'QRIS'
    })
    assert res_checkout_qris.status_code == 200, f"Checkout QRIS harus 200 OK, got: {res_checkout_qris.status_code}"
    data_qris = res_checkout_qris.get_json()
    assert data_qris['status'] == 'success', f"Checkout harus sukses, respon: {data_qris}"
    assert 'ref_id' in data_qris
    print(f"  [OK] Transaksi Game via QRIS sukses dibuat: {data_qris['ref_id']}")

    # 4. UJI INVOICE TRANSAKSI GAME
    print("\n[4/4] Memeriksa Halaman Invoice Transaksi Game ...")
    res_inv = client.get(f"/trx/invoice/{data_qris['ref_id']}")
    assert res_inv.status_code == 200
    inv_html = res_inv.data.decode('utf-8')
    assert 'qris-container' in inv_html, "Barcode QRIS harus tampil pada invoice transaksi game!"
    print(f"  [OK] Invoice QRIS transaksi game terkonfirmasi valid & menampilkan barcode!")

    print("\n" + "="*65)
    print("  >>> OPTIMASI & STANDARISASI KATEGORI GAMES SUKSES 100%! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_games_category()

