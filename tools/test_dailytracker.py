"""
Skrip pengujian Moeslim Daily Tracker Native pada GarudaTel (/muslimtrack)
"""
import sys
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.models.user import User

def test_muslimtrack_native():
    app = create_app()
    client = app.test_client()

    print("\n" + "="*65)
    print("  VERIFIKASI MOESLIM DAILY TRACKER NATIVE (/muslimtrack)")
    print("="*65)

    # 1. Cek Navbar Bawah di Dashboard (/)
    print("\n[1/6] Memeriksa Tombol Tengah Navbar Bawah di Dashboard (/) ...")
    res_dash = client.get('/')
    assert res_dash.status_code == 200
    html_dash = res_dash.data.decode('utf-8')
    assert 'href="/muslimtrack"' in html_dash, "Navbar bawah harus memiliki tautan ke /muslimtrack"
    assert 'fa-calendar-check' in html_dash, "Icon tombol tengah harus menggunakan fa-calendar-check untuk Daily Tracker"
    print("  [OK] Tombol tengah navbar bawah berhasil mengarah ke /muslimtrack!")

    # 2. Cek Akses Halaman Utama /muslimtrack Mode Tamu (Guest)
    print("\n[2/6] Menguji Endpoint /muslimtrack (Mode Tamu / Guest Otomatis) ...")
    res_track = client.get('/muslimtrack')
    assert res_track.status_code == 200
    html_track = res_track.data.decode('utf-8')
    
    assert 'Moeslem Daily Tracker' in html_track, "Judul Moeslem Daily Tracker harus ada"
    assert 'tanilink.github.io' not in html_track, "Tidak boleh ada link/iframe ke github eksternal!"
    assert 'Kembali ke GarudaTel' in html_track, "Tombol navigasi kembali ke GarudaTel harus ada"
    assert 'href="/"' in html_track, "Tautan kembali harus mengarah ke '/'"
    assert 'prayer-wajib-container' in html_track, "Komponen shalat wajib native harus ada"
    assert 'prayer-sunnah-container' in html_track, "Komponen shalat sunnah native harus ada"
    assert 'list-ibadah-extra' in html_track, "Komponen amalan ibadah ekstra harus ada"
    assert 'list-kesehatan' in html_track, "Komponen kesehatan jasmani harus ada"
    assert 'list-akhlak' in html_track, "Komponen akhlak adab sosial harus ada"
    assert 'whatsapp://send?text=' in html_track, "Format sharing harus menggunakan protokol langsung whatsapp://"
    assert 'bottom-nav' in html_track, "Bottom navbar GarudaTel harus hadir di halaman muslimtrack"
    assert 'const isGarudatelLoggedIn = false;' in html_track, "Jika belum login harus otomatis guest"
    assert 'Tamu (Mode Guest)' in html_track, "Tamu harus terdeteksi"
    print("  [OK] Mode tamu berhasil otomatis aktif tanpa halangan login!")

    # 3. Cek Deteksi Login Akun GarudaTel Otomatis
    print("\n[3/6] Menguji Deteksi Login Akun GarudaTel Otomatis ...")
    with app.app_context():
        user = User.query.first()
        assert user is not None
        uid = user.id
        uname = user.name

    with client.session_transaction() as sess:
        sess['_user_id'] = str(uid)
        sess['_fresh'] = True

    res_user = client.get('/muslimtrack')
    assert res_user.status_code == 200
    html_user = res_user.data.decode('utf-8')
    assert 'const isGarudatelLoggedIn = true;' in html_user, "User login harus terdeteksi true"
    assert uname in html_user, f"Nama user {uname} harus ada di halaman"
    print(f"  [OK] Login akun GarudaTel berhasil terdeteksi otomatis ({uname})!")

    # 4. Cek Akses Endpoint Alias (/scan, /dailytracker, /tracker)
    print("\n[4/6] Menguji Endpoint Alias (/scan, /dailytracker & /tracker) ...")
    res_scan = client.get('/scan')
    assert res_scan.status_code == 200
    res_alias1 = client.get('/dailytracker')
    assert res_alias1.status_code == 200
    res_alias2 = client.get('/tracker')
    assert res_alias2.status_code == 200
    print("  [OK] Seluruh alias endpoint /scan, /dailytracker, dan /tracker berjalan normal 200 OK!")

    # 5. Cek Tombol Kembali di Semua Layanan
    print("\n[5/6] Memeriksa Tombol Navigasi Kembali ke Home ...")
    assert 'href="/"' in html_track
    print("  [OK] Tombol kembali terverifikasi langsung menuju ke halaman utama user (/)!")

    # 6. Cek Keselarasan Tema Teal GarudaTel
    print("\n[6/6] Memeriksa Keselarasan Tema Teal GarudaTel (#00877a) ...")
    assert '#00877a' in html_track, "Warna tema teal GarudaTel #00877a harus diterapkan"
    print("  [OK] Tema warna GarudaTel #00877a telah diselaraskan!")

    print("\n" + "="*65)
    print("  >>> VERIFIKASI MOESLIM DAILY TRACKER NATIVE SUKSES 100%! <<<")
    print("="*65 + "\n")

if __name__ == '__main__':
    test_muslimtrack_native()
