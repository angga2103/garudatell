#!/usr/bin/env python3
"""
tools/cron_sync_products.py
Script eksekusi terjadwal (Cron Job) mandiri untuk GarudaTel v2:
1. Sinkronisasi katalog produk dari Digiflazz ke database lokal secara aman.
2. Mematuhi aturan baku anti-wipeout & circuit breaker (RC 83).
3. Melindungi produk yang digembok admin (is_admin_disabled=True) agar tidak aktif kembali.
4. Memindai saldo minim toko mitra (< Rp 100.000) dan mengirim notifikasi WhatsApp ramah.
5. Mengirimkan laporan langsung ke Telegram Bot 3 Admin (baik sukses maupun peringatan kendala).
6. Mencatat riwayat eksekusi terstruktur ke storage/logs/cron_sync.log.

Penggunaan Crontab Linux (disarankan setiap 30 menit):
*/30 * * * * /var/www/garudatel/venv/bin/python /var/www/garudatel/tools/cron_sync_products.py >> /var/www/garudatel/storage/logs/cron_sync.log 2>&1
"""

import os
import sys
import argparse
from datetime import datetime

# Pastikan path root proyek terdaftar dalam sys.path
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import create_app
from app.services.digiflazz import sync_products
from app.services.balance_notification_service import scan_and_notify_all_low_balance_users


def main():
    parser = argparse.ArgumentParser(description="GarudaTel v2 - Auto-Sync Products & Low Balance Cron Runner")
    parser.add_argument("--force", action="store_true", help="Paksa sinkronisasi (abaikan cooldown 5 menit)")
    parser.add_argument("--no-notify", action="store_true", help="Jangan kirim laporan notifikasi ke Bot 3 Admin")
    parser.add_argument("--skip-scan", action="store_true", help="Lewati pemindaian saldo minim toko mitra")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        start_time = datetime.now()
        timestamp_str = start_time.strftime("%Y-%m-%d %H:%M:%S WIB")
        print(f"[{timestamp_str}] [CRON START] Menjalankan sinkronisasi produk Digiflazz...")

        try:
            # 1. Jalankan sinkronisasi katalog produk Digiflazz
            ok, msg = sync_products(force=args.force, notify_admin_bot=not args.no_notify)
            status_tag = "SUCCESS" if ok else "WARNING/FAILED"
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}] [CRON DIGIFLAZZ] [{status_tag}] {msg}")

            # 2. Jika sinkronisasi berhasil, jalankan pemindaian saldo minim toko
            if ok and not args.skip_scan:
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}] [CRON SCAN] Memindai toko dengan saldo minim...")
                try:
                    scan_res = scan_and_notify_all_low_balance_users(force_all=False)
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}] [CRON SCAN] Hasil: {scan_res}")
                except Exception as e_scan:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}] [CRON SCAN ERROR] {e_scan}")

            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}] [CRON FINISH] Selesai dalam {elapsed:.2f} detik.\n")
            sys.exit(0 if ok else 1)

        except Exception as ex:
            elapsed = (datetime.now() - start_time).total_seconds()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S WIB')}] [CRON FATAL ERROR] {ex} (waktu: {elapsed:.2f}s)")
            import traceback
            traceback.print_exc()
            sys.exit(2)


if __name__ == "__main__":
    main()
