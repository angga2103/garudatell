import os
import sys
import re

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models.user import User

def test_revised_category_pages():
    print("=" * 70)
    print("  VERIFIKASI KOMPREHENSIF STANDARDISASI HALAMAN KATEGORI")
    print("  (PULSA, PAKET DATA, TELP & SMS, TOKEN & TAGIHAN PLN)")
    print("=" * 70)

    app = create_app()
    client = app.test_client()

    with app.app_context():
        u = User.query.first()
        uid = u.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['admin_logged_in'] = False

    # 1. UJI HALAMAN PULSA
    print("\n[1/4] Menguji Halaman Pulsa (/kategori/pulsa)...")
    res_pulsa = client.get('/kategori/pulsa')
    assert res_pulsa.status_code == 200
    html_pulsa = res_pulsa.data.decode('utf-8')
    assert 'PULSA REGULER' in html_pulsa
    assert 'id="noHpInput"' in html_pulsa
    assert 'id="checkoutModal"' in html_pulsa
    assert 'data-op="ALL"' in html_pulsa
    assert 'data-op="TELKOMSEL"' in html_pulsa
    assert 'data-op="BYU"' in html_pulsa
    assert 'data-op="INDOSAT"' in html_pulsa
    assert 'data-op="XL"' in html_pulsa
    assert 'data-op="AXIS"' in html_pulsa
    assert 'data-op="TRI"' in html_pulsa
    assert 'data-op="SMARTFREN"' in html_pulsa
    
    cards_pulsa = re.findall(r'class="[^"]*product-card item-produk[^"]*"', html_pulsa)
    assert len(cards_pulsa) >= 40, f"Expected >= 40 pulsa products, found {len(cards_pulsa)}"
    assert 'onclick="beliProdukModal(this)"' in html_pulsa
    assert 'class="btn-card-beli"' in html_pulsa
    
    sku_pulsa_match = re.search(r'data-sku="([^"]+)"', html_pulsa)
    assert sku_pulsa_match is not None
    sku_pulsa = sku_pulsa_match.group(1)
    
    # Test checkout API pulsa
    res_ck_pulsa = client.post('/trx/checkout', json={
        'sku_code': sku_pulsa,
        'target_number': '08123456789',
        'payment_method': 'qris'
    })
    assert res_ck_pulsa.status_code == 200
    assert res_ck_pulsa.get_json().get('status') == 'success'
    print(f"  [OK] Halaman Pulsa 100% valid ({len(cards_pulsa)} produk, tabs lengkap, checkout {sku_pulsa} sukses).")

    # 2. UJI HALAMAN PAKET DATA
    print("\n[2/4] Menguji Halaman Paket Data (/kategori/data)...")
    res_data = client.get('/kategori/data')
    assert res_data.status_code == 200
    html_data = res_data.data.decode('utf-8')
    assert 'PAKET DATA' in html_data
    assert 'id="noHpInput"' in html_data
    assert 'id="checkoutModal"' in html_data
    assert 'data-op="ALL"' in html_data
    assert 'data-op="TELKOMSEL"' in html_data
    assert 'data-op="BYU"' in html_data
    assert 'data-op="INDOSAT"' in html_data
    
    cards_data = re.findall(r'class="[^"]*product-card item-produk[^"]*"', html_data)
    assert len(cards_data) >= 500, f"Expected >= 500 data products, found {len(cards_data)}"
    assert 'onclick="beliProdukModal(this)"' in html_data
    assert 'class="btn-card-beli"' in html_data

    sku_data_match = re.search(r'data-sku="([^"]+)"', html_data)
    assert sku_data_match is not None
    sku_data = sku_data_match.group(1)

    # Test checkout API data
    res_ck_data = client.post('/trx/checkout', json={
        'sku_code': sku_data,
        'target_number': '08123456789',
        'payment_method': 'qris'
    })
    assert res_ck_data.status_code == 200
    assert res_ck_data.get_json().get('status') == 'success'
    print(f"  [OK] Halaman Paket Data 100% valid ({len(cards_data)} produk, tabs lengkap, checkout {sku_data} sukses).")

    # 3. UJI HALAMAN TELP & SMS
    print("\n[3/4] Menguji Halaman Telp & SMS (/kategori/telpsms)...")
    res_telp = client.get('/kategori/telpsms')
    assert res_telp.status_code == 200
    html_telp = res_telp.data.decode('utf-8')
    assert 'TELP & SMS' in html_telp
    assert 'id="noHpInput"' in html_telp
    assert 'id="checkoutModal"' in html_telp
    assert 'data-op="ALL"' in html_telp
    assert 'data-op="TELKOMSEL"' in html_telp
    assert 'data-op="INDOSAT"' in html_telp
    assert 'data-op="XL"' in html_telp
    assert 'data-op="AXIS"' in html_telp
    assert 'data-op="TRI"' in html_telp
    
    cards_telp = re.findall(r'class="[^"]*product-card item-produk[^"]*"', html_telp)
    assert len(cards_telp) >= 15, f"Expected >= 15 telpsms products, found {len(cards_telp)}"
    assert 'onclick="beliProdukModal(this)"' in html_telp
    assert 'class="btn-card-beli"' in html_telp

    sku_telp_match = re.search(r'data-sku="([^"]+)"', html_telp)
    assert sku_telp_match is not None
    sku_telp = sku_telp_match.group(1)

    # Test checkout API telpsms
    res_ck_telp = client.post('/trx/checkout', json={
        'sku_code': sku_telp,
        'target_number': '08123456789',
        'payment_method': 'qris'
    })
    assert res_ck_telp.status_code == 200
    assert res_ck_telp.get_json().get('status') == 'success'
    print(f"  [OK] Halaman Telp & SMS 100% valid ({len(cards_telp)} produk, tabs lengkap, checkout {sku_telp} sukses).")

    # 4. UJI HALAMAN TOKEN & TAGIHAN PLN
    print("\n[4/4] Menguji Halaman Token & Tagihan PLN (/kategori/pln)...")
    res_pln = client.get('/kategori/pln')
    assert res_pln.status_code == 200
    html_pln = res_pln.data.decode('utf-8')
    assert 'TOKEN & TAGIHAN PLN' in html_pln
    assert 'id="noMeterInput"' in html_pln
    assert 'id="checkoutModal"' in html_pln
    assert 'data-op="ALL"' in html_pln
    assert 'data-op="PRABAYAR"' in html_pln
    assert 'data-op="PASCABAYAR"' in html_pln
    
    cards_pln = re.findall(r'class="[^"]*product-card item-produk[^"]*"', html_pln)
    assert len(cards_pln) >= 10, f"Expected >= 10 PLN products, found {len(cards_pln)}"
    assert 'onclick="beliProdukModal(this)"' in html_pln
    assert 'class="btn-card-beli"' in html_pln

    # VERIFIKASI PERBAIKAN CRITICAL BUG: data-sku="SKU" TIDAK BOLEH ADA LAGI!
    assert 'data-sku="SKU"' not in html_pln, "Critical bug: data-sku='SKU' still exists!"
    print("  [OK] Bug Kritis 'data-sku=\"SKU\"' telah 100% TERATASI (sekarang memuat SKU riil)!")

    # Ambil sample produk PLN (misal PLN20)
    sku_pln_match = re.search(r'data-sku="([^"]+)"', html_pln)
    assert sku_pln_match is not None
    sku_pln = sku_pln_match.group(1)
    assert sku_pln != 'SKU', "SKU must not be literal string 'SKU'"

    # Test checkout API PLN
    res_ck_pln = client.post('/trx/checkout', json={
        'sku_code': sku_pln,
        'target_number': '141234567890',
        'payment_method': 'qris'
    })
    assert res_ck_pln.status_code == 200
    assert res_ck_pln.get_json().get('status') == 'success'
    print(f"  [OK] Halaman PLN 100% valid ({len(cards_pln)} produk, tabs Prabayar/Pascabayar, checkout {sku_pln} sukses).")

    print("\n" + "=" * 70)
    print("  >>> SELURUH 4 HALAMAN KATEGORI TERSTANDARISASI & LULUS 100%! <<<")
    print("=" * 70 + "\n")

if __name__ == '__main__':
    test_revised_category_pages()

