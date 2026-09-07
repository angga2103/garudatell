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
    ("referral_code", "VARCHAR(20)"),
    ("is_device_lock_enabled", "BOOLEAN DEFAULT 0")
]

for col_name, col_type in new_cols:
    if col_name not in existing_cols:
        try:
            cur.execute(f"ALTER TABLE user ADD COLUMN {col_name} {col_type};")
            print(f"  [+] Kolom 'user.{col_name}' berhasil ditambahkan.")
        except Exception as e:
            print(f"  [!] Gagal tambah kolom user.{col_name}: {e}")
    else:
        print(f"  [i] Kolom 'user.{col_name}' sudah ada.")

# 2. Tambah kolom transaction jika belum ada
cur.execute("PRAGMA table_info(`transaction`);")
trx_cols = [row[1] for row in cur.fetchall()]

new_trx_cols = [
    ("device_id", "INTEGER REFERENCES trusted_device(id)"),
    ("device_name", "VARCHAR(100)")
]

for col_name, col_type in new_trx_cols:
    if col_name not in trx_cols:
        try:
            cur.execute(f"ALTER TABLE `transaction` ADD COLUMN {col_name} {col_type};")
            print(f"  [+] Kolom 'transaction.{col_name}' berhasil ditambahkan.")
        except Exception as e:
            print(f"  [!] Gagal tambah kolom transaction.{col_name}: {e}")
    else:
        print(f"  [i] Kolom 'transaction.{col_name}' sudah ada.")

# 3. Buat tabel commission_logs jika belum ada
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

# 4. Buat tabel trusted_device jika belum ada
cur.execute("""
CREATE TABLE IF NOT EXISTS trusted_device (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES user(id),
    device_uuid VARCHAR(64) NOT NULL,
    device_name VARCHAR(100) NOT NULL,
    device_info VARCHAR(255),
    ip_address VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    approval_token VARCHAR(64) UNIQUE,
    approval_expires_at DATETIME,
    approved_at DATETIME,
    created_at DATETIME,
    last_used_at DATETIME,
    CONSTRAINT uq_user_device UNIQUE (user_id, device_uuid)
);
""")
cur.execute("CREATE INDEX IF NOT EXISTS idx_device_user ON trusted_device (user_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_device_uuid ON trusted_device (device_uuid);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_device_status ON trusted_device (status);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_device_token ON trusted_device (approval_token);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_trx_device ON `transaction` (device_id);")
cur.execute("CREATE INDEX IF NOT EXISTS idx_trx_device_name ON `transaction` (device_name);")

conn.commit()
conn.close()
print("[SUCCESS] Migrasi database berhasil diselesaikan 100%!")

