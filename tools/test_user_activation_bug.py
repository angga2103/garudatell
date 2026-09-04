import os
import sys

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User

def test_user_activation_bug():
    print("=" * 65)
    print("  VERIFIKASI PERBAIKAN BUG AKTIVASI USER (UNIQUE EMAIL CONSTRAINT)")
    print("=" * 65)

    app = create_app()
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # 1. Pastikan user 1 dalam kondisi terblokir
    with app.app_context():
        u1 = User.query.get(1)
        assert u1 is not None, "User ID 1 harus ada di DB"
        u1.is_active = False
        u1.email = None
        db.session.commit()
        print(f"[1/3] User 1 '{u1.name}' disiapkan: is_active={u1.is_active}, email={repr(u1.email)}")

    # 2. Simulasi Aksi Admin: Mengaktifkan User 1 dengan form email kosong ('')
    print("\n[2/3] Menguji Aktivasi User 1 dengan form email kosong ('')...")
    res_activate = client.post('/admin/user/update_action', data={
        'user_id': 1,
        'name': 'Angga Dian',
        'phone': '0817757001199',
        'email': '',  # String kosong dari input form
        'balance': 100000,
        'role': 'user',
        'status': '1'  # Aktifkan kembali!
    }, follow_redirects=True)

    assert res_activate.status_code == 200, f"Gagal HTTP: {res_activate.status_code}"
    assert "Terjadi kesalahan sistem" not in res_activate.text, "Error sistem masih terjadi!"
    assert "UNIQUE constraint failed" not in res_activate.text, "IntegrityError UNIQUE constraint masih muncul!"
    assert "Data pengguna Angga Dian berhasil diperbarui" in res_activate.text or "berhasil" in res_activate.text

    # Verifikasi status di database
    with app.app_context():
        u1_updated = User.query.get(1)
        assert u1_updated.is_active is True, "User 1 harus berstatus Aktif (True)!"
        assert u1_updated.email is None, f"Email harus None/NULL di database, tapi didapat: {repr(u1_updated.email)}"
        print(f"  [OK] User 1 berhasil diaktifkan: is_active={u1_updated.is_active}, email={repr(u1_updated.email)}")

    # 3. Uji Aktivasi User Lain dengan email kosong juga (memastikan tidak ada tabrakan NULL di SQLite)
    print("\n[3/3] Menguji User 2 dan 3 dengan email kosong...")
    with app.app_context():
        u2 = User.query.get(2)
        if u2:
            u2.email = None
            db.session.commit()

    res_user2 = client.post('/admin/user/update_action', data={
        'user_id': 2,
        'name': 'tes1',
        'phone': '08123456789',
        'email': '',
        'balance': 50000,
        'role': 'user',
        'status': '1'
    }, follow_redirects=True)
    assert res_user2.status_code == 200
    assert "UNIQUE constraint failed" not in res_user2.text

    with app.app_context():
        u1_check = User.query.get(1)
        u2_check = User.query.get(2)
        assert u1_check.is_active is True
        assert u2_check.is_active is True
        assert u1_check.email is None
        assert u2_check.email is None
        print("  [OK] Beberapa user dengan email kosong/None dapat aktif bersamaan tanpa error UNIQUE constraint!")

    print("\n" + "=" * 65)
    print("  >>> PERBAIKAN BUG AKTIVASI USER 100% SUKSES DIVERIFIKASI! <<<")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    test_user_activation_bug()

