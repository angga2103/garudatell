import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models.product import Product
from app.models.user import User
import re

def test_kategori_masaaktif():
    print("=" * 70)
    print("  VERIFIKASI PERBAIKAN HALAMAN KATEGORI MASA AKTIF (/kategori/masaaktif)")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    # 1. Uji Response HTTP GET
    print("\n[1/4] Menguji Response HTTP GET /kategori/masaaktif...")
    res = client.get('/kategori/masaaktif')
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    html = res.data.decode('utf-8')
    print("  [OK] Halaman /kategori/masaaktif merespons 200 OK.")

    # 2. Parsing HTML DOM & Komponen
    print("\n[2/4] Memeriksa Komponen Template & Struktur HTML...")
    assert 'MASA AKTIF' in html
    assert 'id="pageTitle"' in html
    print("  [OK] Header & Judul MASA AKTIF tampil dengan benar.")

    # Periksa Tab Operator
    for op in ['ALL', 'TELKOMSEL', 'INDOSAT', 'XL', 'AXIS', 'TRI']:
        assert f'data-op="{op}"' in html, f"Tab {op} missing"
    print("  [OK] Ditemukan tab operator: ALL, TELKOMSEL, INDOSAT, XL, AXIS, TRI.")

    # Periksa Kartu Produk
    cards = re.findall(r'class="[^"]*product-card item-produk[^"]*"', html)
    assert len(cards) >= 20, f"Expected >= 20 products, found {len(cards)}"
    print(f"  [OK] Berhasil merender {len(cards)} produk Masa Aktif aktif dari database.")

    # 3. Uji Atribut Interaktif pada Kartu Produk
    print("\n[3/4] Memeriksa Atribut Interaktif & Tombol Checkout pada Kartu Produk...")
    assert 'onclick="beliProdukModal(this)"' in html
    assert 'data-sku=' in html
    assert 'data-nama=' in html
    assert 'data-harga=' in html
    assert 'data-provider=' in html
    assert 'class="btn-card-beli"' in html
    print("  [OK] Kartu produk memiliki event click, data-attributes, dan tombol BELI.")

    # Periksa Modal Bottom Sheet
    assert 'id="checkoutModal"' in html
    assert 'id="noHpInput"' in html
    assert 'id="btnProsesBayar"' in html
    print("  [OK] Bottom Sheet Checkout Modal dan formulir pembayaran tersedia.")

    # 4. Uji Checkout Produk Masa Aktif
    print("\n[4/4] Menguji Alur Checkout Produk Masa Aktif via API...")
    with app.app_context():
        u = User.query.first()
        uid = u.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['admin_logged_in'] = False

    sku_match = re.search(r'data-sku="([^"]+)"', html)
    test_sku = sku_match.group(1) if sku_match else 'TMAS5'
    res_checkout = client.post('/trx/checkout', json={
        'sku_code': test_sku,
        'target_number': '08123456789',
        'payment_method': 'qris'
    })
    assert res_checkout.status_code == 200
    res_json = res_checkout.get_json()
    assert res_json.get('status') == 'success'
    print(f"  [OK] Transaksi checkout produk Masa Aktif ({test_sku}) via QRIS sukses direspons server!")

    print("\n" + "=" * 70)
    print("  >>> SELURUH VERIFIKASI HALAMAN MASA AKTIF LULUS 100% SUKSES! <<<")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    test_kategori_masaaktif()
