"""
GarudaTel v2 - SQLite to PostgreSQL Data Exporter Utility
Gunakan skrip ini jika aplikasi siap dimigrasikan ke basis data PostgreSQL untuk skala enterprise.
Penggunaan:
    python tools/export_to_postgres.py --output dump_postgres.sql
"""

import sqlite3
import argparse
import os

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'app', 'garudatel.db')

def export_data(output_file):
    if not os.path.exists(DB_PATH):
        print(f"[ERROR] Database SQLite tidak ditemukan di: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Dapatkan daftar semua tabel pengguna
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
    tables = [r[0] for r in cursor.fetchall()]

    print(f"[*] Ditemukan {len(tables)} tabel untuk diekspor: {tables}")

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("-- GarudaTel PostgreSQL Migration Dump\n")
        f.write("-- Generated automatically\n\n")

        for table in tables:
            cursor.execute(f"SELECT * FROM [{table}]")
            rows = cursor.fetchall()
            col_names = [desc[0] for desc in cursor.description]

            f.write(f"-- Data untuk tabel: {table} ({len(rows)} baris)\n")
            if not rows:
                f.write(f"-- (Tabel kosong)\n\n")
                continue

            col_list_str = ", ".join([f'"{c}"' for c in col_names])
            for row in rows:
                vals = []
                for val in row:
                    if val is None:
                        vals.append("NULL")
                    elif isinstance(val, (int, float)):
                        vals.append(str(val))
                    elif isinstance(val, bytes):
                        vals.append(f"'{val.decode('utf-8', errors='ignore')}'")
                    else:
                        safe_val = str(val).replace("'", "''")
                        vals.append(f"'{safe_val}'")
                val_str = ", ".join(vals)
                f.write(f'INSERT INTO "{table}" ({col_list_str}) VALUES ({val_str}) ON CONFLICT DO NOTHING;\n')
            f.write("\n")

    conn.close()
    print(f"[SUCCESS] Data berhasil diekspor ke file: {output_file}")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Ekspor SQLite GarudaTel ke SQL PostgreSQL")
    parser.add_argument('--output', default='tools/postgres_dump.sql', help="Nama file output")
    args = parser.parse_args()
    export_data(args.output)

