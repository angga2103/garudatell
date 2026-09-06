import os
import sys
import traceback

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

print("=" * 70)
print("   DIAGNOSTIK SISTEM MUTASI SALDO GARUDATEL (VPS SCAN)")
print("=" * 70)

try:
    from app import create_app
    from app.extensions import db
    from app.models.user import User
    from app.models.transaction import Transaction
    from app.services.mutasi_service import get_user_mutations
    print("[1/5] Inisialisasi Flask App & DB Extensions... OK")
except Exception as e:
    print("\n[ERROR KRITIS] Gagal mengimpor modul aplikasi:")
    traceback.print_exc()
    sys.exit(1)

app = create_app()

with app.app_context():
    print("[2/5] Memeriksa Koneksi Database & Tabel...")
    try:
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        tables = inspector.get_table_names()
        print(f"      Tabel terdeteksi ({len(tables)} tabel): {', '.join(tables[:10])}...")
        
        users_count = User.query.count()
        trxs_count = Transaction.query.count()
        print(f"      Total Pengguna: {users_count}, Total Transaksi: {trxs_count}")
    except Exception as e:
        print("\n[ERROR] Masalah koneksi database:")
        traceback.print_exc()

    print("\n[3/5] Menguji Engine Mutasi get_user_mutations()...")
    users = User.query.all()
    if not users:
        print("      [WARNING] Database belum memiliki user.")
    for u in users[:3]:
        try:
            res = get_user_mutations(u.id)
            print(f"      User ID {u.id} ({u.name}): {len(res['mutations'])} mutasi, Saldo: Rp {res['stats']['current_balance']:,.0f}")
        except Exception as e:
            print(f"\n[ERROR] get_user_mutations gagal pada user {u.id}:")
            traceback.print_exc()

    print("\n[4/5] Menguji HTTP Endpoint GET /mutasi, /informasi, /mutations...")
    client = app.test_client()
    test_user = users[0] if users else None

    if test_user:
        with client.session_transaction() as sess:
            sess['_user_id'] = str(test_user.id)
            sess['admin_logged_in'] = False

        for ep in ['/mutasi', '/informasi', '/mutations']:
            try:
                resp = client.get(ep)
                print(f"      {ep} -> HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    print(f"      [RESPONSE BODY ERROR]:\n{resp.data.decode('utf-8', errors='ignore')[:600]}")
            except Exception as e:
                print(f"\n[ERROR CRASH] Endpoint {ep} melempar unhandled exception:")
                traceback.print_exc()
    else:
        print("      Skip simulasi login karena tidak ada user.")

print("\n[5/5] Memeriksa File Log Terakhir...")
log_file = os.path.join(BASE_DIR, 'storage', 'logs', 'garudatel.log')
if os.path.exists(log_file):
    print(f"      Log terdeteksi di {log_file}")
    try:
        with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            last_lines = lines[-20:] if len(lines) >= 20 else lines
            print("      --- 20 BARIS TERAKHIR GARUDATEL.LOG ---")
            for l in last_lines:
                print("      " + l.rstrip())
    except Exception as e:
        print(f"      Gagal membaca log: {e}")
else:
    print(f"      File log {log_file} belum ada.")

print("\n" + "=" * 70)
print("   DIAGNOSTIK SELESAI")
print("=" * 70)
