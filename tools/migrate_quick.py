import os
import sqlite3

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
db_path = os.path.join(BASE_DIR, 'app', 'garudatel.db')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 1. Tambah kolom user jika belum ada
cur.execute("PRAGMA table_info(user);")
existing_cols = [row[1] for row in cur.fetchall()]

new_cols = [
    ("role_expires_at", "DATETIME"),
    ("upline_id", "INTEGER REFERENCES user(id)"),
    ("commission_balance", "REAL DEFAULT 0.0"),
    ("last_reminded_at", "DATETIME"),
    ("referral_code", "VARCHAR(20)")
]

for col_name, col_type in new_cols:
    if col_name not in existing_cols:
        try:
            cur.execute(f"ALTER TABLE user ADD COLUMN {col_name} {col_type};")
            print(f"  [+] Kolom 'user.{col_name}' berhasil ditambahkan.")
        except Exception as e:
            print(f"  [!] Gagal tambah kolom {col_name}: {e}")
    else:
        print(f"  [i] Kolom 'user.{col_name}' sudah ada.")

# 2. Buat tabel commission_logs jika belum ada
cur.execute("""
CREATE TABLE IF NOT EXISTS commission_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    upline_id INTEGER NOT NULL REFERENCES user(id),
    downline_id INTEGER NOT NULL REFERENCES user(id),
    transaction_id INTEGER REFERENCES `transaction`(id),
    trx_amount REAL DEFAULT 0.0,
    commission_amount REAL NOT NULL DEFAULT 0.0,
    status VARCHAR(20) DEFAULT 'earned',
    created_at DATETIME,
    payout_date DATETIME
);
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_comm_upline ON commission_logs (upline_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_comm_downline ON commission_logs (downline_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_comm_trx ON commission_logs (transaction_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_comm_status ON commission_logs (status);")

conn.commit()
conn.close()
print("[SUCCESS] Migrasi database berhasil diselesaikan 100%!")
