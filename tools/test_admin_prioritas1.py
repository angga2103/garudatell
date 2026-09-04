import os
import sys
import re

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product
from app.models.margin import MarginTier

def test_admin_priority_1():
    print("=" * 65)
    print("  VERIFIKASI PERBAIKAN PANEL ADMIN - PRIORITAS 1")
    print("=" * 65)

    app = create_app()
    client = app.test_client()

    with client.session_transaction() as sess:
        sess['admin_logged_in'] = True

    # 1. Test Dashboard Rendering & Real Metrics
    print("\n[1/6] Menguji Tampilan Dashboard & Metrik Riil...")
    res_dash = client.get('/admin/')
    assert res_dash.status_code == 200, f"Dashboard error: {res_dash.status_code}"
    
    # Pastikan angka hardcoded lama 1,204 dan 45.2M sudah diganti
    assert "1,204" not in res_dash.text, "Angka dummy 1,204 masih muncul di dashboard!"
    assert "45.2M" not in res_dash.text, "Angka dummy 45.2M masih muncul di dashboard!"
    
    with app.app_context():
        u_count = str(User.query.count())
    assert u_count in res_dash.text, f"Jumlah user riil ({u_count}) tidak ditemukan di dashboard!"
    print(f"  [OK] Dashboard menampilkan metrik riil dari database (User Count: {u_count}).")

    # Pastikan csrf_token hadir di seluruh form dashboard
    csrf_count = res_dash.text.count('name="csrf_token"')
    print(f"  [OK] Ditemukan {csrf_count} field csrf_token di form dashboard.")
    assert csrf_count >= 8, f"Kurang dari 8 csrf_token di dashboard (hanya {csrf_count})"

    # 2. Test Simpan Konfigurasi (POST /admin/save_config)
    print("\n[2/6] Menguji Simpan Konfigurasi...")
    res_save = client.post('/admin/save_config', data={
        'form_type': 'digiflazz',
        'digi_user': 'user_test_admin',
        'digi_url': 'https://api.digiflazz.com/v1'
    }, follow_redirects=True)
    assert res_save.status_code == 200
    assert "Konfigurasi berhasil disimpan!" in res_save.text
    print("  [OK] Form save_config berhasil diproses tanpa blokir CSRF (200 OK via redirect).")

    # 3. Test Edit User di Data User (POST /admin/user/update_action)
    print("\n[3/6] Menguji Edit User Action & Update Password...")
    with app.app_context():
        # Dapatkan 1 user atau buat test user
        test_u = User.query.filter_by(phone='081122334455').first()
        if not test_u:
            test_u = User(name='UserAdminTest', phone='081122334455', password_hash='dummy_hash', balance=50000.0)
            db.session.add(test_u)
            db.session.commit()
        uid = test_u.id

    res_user_act = client.post('/admin/user/update_action', data={
        'user_id': uid,
        'name': 'UserAdminEdited',
        'phone': '081122334455',
        'email': 'edited@garudatel.com',
        'balance': 75000,
        'password': 'newpassword123',
        'role': 'reseller',
        'status': '1'
    }, follow_redirects=True)
    
    assert res_user_act.status_code == 200
    assert "berhasil diperbarui" in res_user_act.text
    
    # Cek verifikasi database
    with app.app_context():
        u_updated = User.query.get(uid)
        assert u_updated.name == 'UserAdminEdited'
        assert u_updated.balance == 75000.0
        assert u_updated.role == 'reseller'
        assert u_updated.check_password('newpassword123') is True
        print(f"  [OK] Update user sukses: Name={u_updated.name}, Balance={u_updated.balance}, Password ter-update & terverifikasi hash!")

    # 4. Test Template Users (HTML title & modal validation)
    print("\n[4/6] Menguji Template users.html...")
    res_users = client.get('/admin/users')
    assert res_users.status_code == 200
    assert "<title>\nGarudaTel - User Center\n</title>" in res_users.text or "GarudaTel - User Center" in res_users.text
    assert 'id="editUserModal"' in res_users.text
    assert 'name="csrf_token"' in res_users.text
    print("  [OK] Template users.html memiliki title bersih dan modal berada di dalam DOM yang benar.")

    # 5. Test Margin & Produk Forms
    print("\n[5/6] Menguji Form Margin & Produk...")
    res_margin = client.get('/admin/margin')
    assert res_margin.status_code == 200
    assert 'name="csrf_token"' in res_margin.text
    
    # Test apply auto tier
    res_apply = client.post('/admin/apply_auto_tier', follow_redirects=True)
    assert res_apply.status_code == 200
    print("  [OK] Form Margin & eksekusi apply_auto_tier berhasil dijalankan tanpa kendala CSRF.")

    # 6. Test AJAX Endpoint (Generate OTP Manual & WA Pairing)
    print("\n[6/6] Menguji Endpoint AJAX Admin (/admin/generate_otp_manual)...")
    res_otp = client.post('/admin/generate_otp_manual', json={'number': '628999888777'})
    assert res_otp.status_code == 200
    otp_data = res_otp.get_json()
    assert otp_data.get('status') == 'success'
    assert len(otp_data.get('otp', '')) == 6
    print(f"  [OK] Generate OTP Manual berhasil via JSON: {otp_data.get('otp')}")

    # Bersihkan test user
    with app.app_context():
        User.query.filter_by(id=uid).delete()
        db.session.commit()

    print("\n" + "=" * 65)
    print("  >>> SELURUH PERBAIKAN PRIORITAS 1 LULUS 100% SECARA SEMPURNA! <<<")
    print("=" * 65 + "\n")

if __name__ == '__main__':
    test_admin_priority_1()
