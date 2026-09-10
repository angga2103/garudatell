import os
import sys
import sqlite3

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
db_path = os.path.join(BASE_DIR, 'app', 'garudatel.db')

def run_migration():
    if not os.path.exists(db_path):
        print(f"[-] Database tidak ditemukan di {db_path}, lewati migrasi.")
        return

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
        pin_hash VARCHAR(200),
        daily_limit REAL DEFAULT 0.0,
        operating_hours_start VARCHAR(5),
        operating_hours_end VARCHAR(5),
        activation_token VARCHAR(64) UNIQUE,
        CONSTRAINT uq_user_device UNIQUE (user_id, device_uuid)
    );
    """)

    # Cek kolom baru pada trusted_device jika tabel sudah ada sebelumnya
    cur.execute("PRAGMA table_info(trusted_device);")
    dev_cols = [row[1] for row in cur.fetchall()]
    new_dev_cols = [
        ("pin_hash", "VARCHAR(200)"),
        ("daily_limit", "REAL DEFAULT 0.0"),
        ("operating_hours_start", "VARCHAR(5)"),
        ("operating_hours_end", "VARCHAR(5)"),
        ("activation_token", "VARCHAR(64)"),
        ("activation_expires_at", "DATETIME"),
        ("session_version", "INTEGER DEFAULT 1"),
        ("active_session_token", "VARCHAR(64)"),
        ("device_fingerprint", "VARCHAR(128)"),
        ("branch_balance", "REAL DEFAULT 0.0"),
        ("low_balance_alert", "REAL DEFAULT 100000.0")
    ]

    for col_name, col_type in new_dev_cols:
        if col_name not in dev_cols:
            try:
                cur.execute(f"ALTER TABLE trusted_device ADD COLUMN {col_name} {col_type};")
                print(f"  [+] Kolom 'trusted_device.{col_name}' berhasil ditambahkan.")
            except Exception as e:
                print(f"  [!] Gagal tambah kolom trusted_device.{col_name}: {e}")
        else:
            print(f"  [i] Kolom 'trusted_device.{col_name}' sudah ada.")

    # 5. Buat tabel branch_mutation jika belum ada
    cur.execute("""
    CREATE TABLE IF NOT EXISTS branch_mutation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id INTEGER NOT NULL REFERENCES trusted_device(id),
        user_id INTEGER NOT NULL REFERENCES user(id),
        type VARCHAR(30) NOT NULL,
        amount REAL NOT NULL,
        balance_before REAL DEFAULT 0.0,
        balance_after REAL DEFAULT 0.0,
        description VARCHAR(255),
        shift_name VARCHAR(100) DEFAULT 'Kasir',
        created_at DATETIME
    );
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bmut_dev_created ON branch_mutation (device_id, created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bmut_user_created ON branch_mutation (user_id, created_at);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_bmut_type ON branch_mutation (type);")

    cur.execute("CREATE INDEX IF NOT EXISTS idx_device_user ON trusted_device (user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_device_uuid ON trusted_device (device_uuid);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_device_status ON trusted_device (status);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_device_token ON trusted_device (approval_token);")
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_device_activation ON trusted_device (activation_token);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trx_device ON `transaction` (device_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_trx_device_name ON `transaction` (device_name);")

    conn.commit()
    conn.close()

    # 6. Pastikan seluruh produk pascabayar nasional terdaftar di database
    try:
        from app import create_app
        from app.services.pascabayar_service import seed_pascabayar_products
        app = create_app()
        with app.app_context():
            ins, upd = seed_pascabayar_products()
            print(f"  [+] Katalog Pascabayar Nasional siap ({ins} baru, {upd} diperbarui).")
    except Exception as e:
        print(f"  [!] Peringatan saat seeding pascabayar: {e}")

    print("[SUCCESS] Migrasi database berhasil diselesaikan 100%!")

if __name__ == '__main__':
    run_migration()
