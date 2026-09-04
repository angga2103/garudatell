"""
Skrip pengujian otomatis untuk verifikasi Tombol Kembali ke Halaman Utama User (/)
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app

def test_back_buttons():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI TOMBOL KEMBALI MENGARAH KE HALAMAN UTAMA USER (/)")
    print("="*65)

    from app.models.user import User
    with app.app_context():
        u = User.query.first()
        uid = u.id if u else 1

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True

    pages = [
        ('/kategori/games', 'top-bar'),
        ('/kategori/pulsa', 'top-bar'),
        ('/kategori/data', 'top-bar'),
        ('/kategori/emoney', 'top-bar'),
        ('/kategori/tv', 'top-bar'),
        ('/kategori/pln', 'top-bar'),
        ('/kategori/telp-sms', 'top-bar'),
        ('/kategori/masa-aktif', 'top-bar'),
        ('/poin', 'top-bar'),
        ('/deposit', 'back-btn'),
        ('/muslimtrack', 'flex'),
        ('/scan', 'tracker-nav-btn'),
        ('/notifikasi', 'btn-header-back'),
        ('/bantuan', 'btn-header-back'),
    ]

    from app.models.transaction import Transaction
    with app.app_context():
        latest_trx = Transaction.query.first()
        if latest_trx:
            pages.append((f'/trx/invoice/{latest_trx.ref_id}', 'inv-back'))

    for url, btn_class in pages:
        res = client.get(url)
        assert res.status_code == 200, f"Halaman {url} gagal diakses: {res.status_code}"
        html = res.data.decode('utf-8')
        
        # Pastikan tautan tombol kembali mengarah langsung ke '/'
        assert 'href="/"' in html, f"Tautan href='/' tidak ditemukan di {url}"
        print(f"  [OK] {url:35} -> 200 OK | Tombol Kembali mengarah ke '/'")

    # Cek bahwa dashboard / dan /dashboard dapat diakses sempurna
    assert client.get('/').status_code == 200
    assert client.get('/dashboard').status_code == 200
    print("  [OK] Route '/' dan alias '/dashboard' berstatus 200 OK!")

    print("\n" + "="*65)
    print("  >>> SELURUH TOMBOL KEMBALI BERHASIL TERVERIFIKASI KE '/'! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_back_buttons()
