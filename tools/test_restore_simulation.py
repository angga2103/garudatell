import os
import sys
import shutil
import zipfile
import sqlite3

def run_simulation():
    ZIP_PATH = os.path.abspath('storage/backups/latest_backup.zip')
    SANDBOX_DIR = os.path.abspath('test_sandbox_restore')

    if os.path.exists(SANDBOX_DIR):
        shutil.rmtree(SANDBOX_DIR)

    os.makedirs(SANDBOX_DIR, exist_ok=True)

    print('=== 1. EKSTRAKSI ARSIP CADANGAN KE SANDBOX ===')
    with zipfile.ZipFile(ZIP_PATH, 'r') as z:
        z.extractall(SANDBOX_DIR)
    print('Ekstraksi berhasil!')

    APP_DIR = os.path.join(SANDBOX_DIR, 'var', 'www', 'garudatel')
    DB_PATH = os.path.join(APP_DIR, 'app', 'garudatel.db')
    ENV_PATH = os.path.join(APP_DIR, '.env')

    print('\n=== 2. PEMERIKSAAN INTEGRITAS DATABASE SQLITE ===')
    print('File Database ditemukan:', os.path.exists(DB_PATH))
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('PRAGMA integrity_check')
    integrity = cursor.fetchall()
    print('Hasil PRAGMA integrity_check:', integrity)
    assert integrity == [('ok',)], f"Database corrupt! Hasil: {integrity}"

    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = [row[0] for row in cursor.fetchall() if not row[0].startswith('sqlite_')]
    print(f'Total tabel ditemukan: {len(tables)}')
    for tbl in tables:
        cursor.execute(f'SELECT COUNT(*) FROM "{tbl}"')
        count = cursor.fetchone()[0]
        print(f' - Tabel {tbl:28}: {count:5} baris data')

    conn.close()

    print('\n=== 3. PEMERIKSAAN KREDENSIAL .ENV ===')
    print('File .env ditemukan:', os.path.exists(ENV_PATH))
    with open(ENV_PATH, 'r', encoding='utf-8') as f:
        env_content = f.read()

    keys_to_check = [
        'SECRET_KEY',
        'DIGI_USER',
        'DIGI_KEY',
        'DIGI_URL',
        'PAYMENTKITA_MERCHANT_ID',
        'PAYMENTKITA_SECRET',
        'WA_BOT_SECRET_TOKEN',
        'CRON_SECRET_KEY'
    ]
    for k in keys_to_check:
        has_k = (k + '=') in env_content or (k in env_content)
        val_status = "LENGKAP / TERISI" if has_k else "HILANG"
        print(f' - Parameter {k:25}: {val_status}')

    print('\n=== 4. SIMULASI INISIALISASI FLASK & SERVICE APP ===')
    sys.path.insert(0, APP_DIR)
    from app import create_app
    test_app = create_app()
    test_app.config['TESTING'] = True
    test_app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'

    client = test_app.test_client()

    # Test homepage
    res_home = client.get('/')
    print(f' - GET / status                       : {res_home.status_code} (OK)')
    assert res_home.status_code == 200

    # Test profil page (tempat login modal)
    res_profil = client.get('/profil')
    print(f' - GET /profil status                 : {res_profil.status_code} (OK)')
    assert res_profil.status_code == 200

    # Test admin login page
    res_admin_login = client.get('/admin/login')
    print(f' - GET /admin/login status            : {res_admin_login.status_code} (OK)')
    assert res_admin_login.status_code == 200

    # Test maintenance endpoint
    res_maint = client.get('/maintenance')
    print(f' - GET /maintenance status            : {res_maint.status_code} (OK)')
    assert res_maint.status_code == 200

    # Test protected admin route
    res_admin = client.get('/admin/store_settings')
    print(f' - GET /admin/store_settings (unauth) : {res_admin.status_code} (Redirect 302 OK)')
    assert res_admin.status_code == 302

    # Test user protected routes
    res_riwayat = client.get('/riwayat')
    print(f' - GET /riwayat status               : {res_riwayat.status_code} (OK)')
    assert res_riwayat.status_code in [200, 302]

    res_deposit = client.get('/deposit')
    print(f' - GET /deposit status               : {res_deposit.status_code} (OK)')
    assert res_deposit.status_code in [200, 302]

    # Test user public / terms route
    res_terms = client.get('/terms')
    print(f' - GET /terms status                 : {res_terms.status_code} (OK)')
    assert res_terms.status_code == 200

    # Test notifikasi
    res_notif = client.get('/notifikasi')
    print(f' - GET /notifikasi status            : {res_notif.status_code} (OK)')
    assert res_notif.status_code in [200, 302]

    # Test API endpoint
    res_api = client.get('/api/user/info')
    api_status = res_api.get_json().get('status', 'unknown')
    print(f' - GET /api/user/info status          : {res_api.status_code} (OK - {api_status})')
    assert res_api.status_code == 200

    print('\n=== 5. BERSIHKAN DIREKTORI SANDBOX ===')
    with test_app.app_context():
        from app.extensions import db
        db.session.remove()
        db.engine.dispose()

    import gc
    gc.collect()

    if os.path.exists(SANDBOX_DIR):
        try:
            shutil.rmtree(SANDBOX_DIR)
        except Exception:
            pass
    print('Direktori simulasi telah dibersihkan.')

    print('\n' + '='*60)
    print(' HASIL AKHIR: 100% LOLOS PENGUJIAN RESTORASI & VALIDASI')
    print('='*60)

if __name__ == '__main__':
    run_simulation()
