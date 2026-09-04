"""
Skrip pengujian otomatis untuk verifikasi Menu Lainnya di Dashboard dan Fitur Baru Riwayat Transaksi.
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models.user import User
from app.models.transaction import Transaction

def test_dashboard_and_riwayat():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI FITUR DASHBOARD (LAINNYA) & RIWAYAT TRANSAKSI")
    print("="*65)

    # 1. VERIFIKASI MENU LAINNYA PADA DASHBOARD UTAMA
    print("\n[1/4] Memeriksa Dashboard Utama (/) & Tombol Lainnya ...")
    res_dash = client.get('/')
    assert res_dash.status_code == 200
    html_dash = res_dash.data.decode('utf-8')

    assert '<a href="#" class="action-item"' not in html_dash, "Tidak boleh ada link mati href='#' pada tombol action-item dashboard!"
    assert 'bukaModalLainnya()' in html_dash, "Tombol Lainnya harus memanggil bukaModalLainnya()"
    assert 'modalLainnyaSheet' in html_dash, "Modal bottom sheet Semua Layanan harus terpasang"
    assert '/kategori/pulsa' in html_dash and '/kategori/games' in html_dash, "Modal Lainnya harus memuat seluruh link kategori"
    print("  [OK] Tombol Lainnya aktif dan terhubung ke Modal Direktori Semua Layanan!")

    # 2. LOGIN USER UNTUK MENGAKSES RIWAYAT
    print("\n[2/4] Menyiapkan Sesi User untuk Halaman Riwayat ...")
    with app.app_context():
        user = User.query.first()
        assert user is not None
        uid = user.id

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True

    # 3. VERIFIKASI HALAMAN RIWAYAT TRANSAKSI
    print("\n[3/4] Memeriksa Halaman /riwayat (Filter, Pencarian, & Struk) ...")
    res_riwayat = client.get('/riwayat')
    assert res_riwayat.status_code == 200
    html_riw = res_riwayat.data.decode('utf-8')

    assert 'btn-header-back' in html_riw and 'href="/"' in html_riw, "Tombol kembali di header riwayat harus mengarah ke '/'"
    assert 'tab-SEMUA' in html_riw and 'tab-SUKSES' in html_riw and 'tab-ANTRI' in html_riw, "Seluruh filter tab status harus ada"
    assert 'inputSearchRiwayat' in html_riw, "Input pencarian real-time transaksi harus ada"
    assert 'bagikanStruk' in html_riw, "Fungsi bagikanStruk WhatsApp harus terpasang"
    assert 'whatsapp://send?text=' in html_riw, "Protokol whatsapp:// untuk struk harus aktif"
    print("  [OK] Halaman /riwayat memuat filter status, search bar, dan fitur bagikan struk WhatsApp!")

    # 4. MEMASTIKAN DETAIL DATA TRANSAKSI TAMPIL BENAR (TARGET & PRICE TIDAK KOSONG)
    print("\n[4/4] Memeriksa Integritas Rendering Transaksi ...")
    with app.app_context():
        trx = Transaction.query.filter_by(user_id=uid).first()
        if trx:
            assert trx.target is not None, "Property target harus mengembalikan target_number"
            assert trx.price is not None, "Property price harus mengembalikan amount"
            print(f"  [OK] Sample Transaksi: Ref={trx.ref_id} | Target={trx.target} | Price=Rp {trx.price:,.0f}")

    print("\n" + "="*65)
    print("  >>> PENGUJIAN DASHBOARD (LAINNYA) & RIWAYAT LULUS 100%! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_dashboard_and_riwayat()

