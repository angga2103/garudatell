#!/usr/bin/env python3
"""
================================================================================
GARUDATEL v2 - TELEGRAM BOT DAEMON (BOT 3 ADMIN & BOT 2 NOTIFIKASI/RESTORE)
================================================================================
Menjalankan daemon background untuk:
1. Bot 3 (Panel Admin): Interaksi tombol inline, cek saldo, omset, dan /otp darurat.
2. Bot 2 (Notifikasi & Backup): Menangkap callback tombol '🔄 Restore Data ke VPS Ini',
   menampilkan konfirmasi keamanan, dan menjalankan 1-click restore otomatis.
================================================================================
"""

import sys
import os
import time
import signal
import logging
import threading
import requests
from dotenv import load_dotenv

# Set base dir
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [Bot Daemon] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("BotDaemon")

from app import create_app
from app.services.telegram_service import (
    get_bot_admin_credentials,
    get_bot_notif_credentials,
    get_bot_cs_credentials,
    handle_admin_callback,
    handle_admin_message,
    handle_notif_callback,
    handle_cs_bot_update
)

# Flag stop global
running = True

def handle_exit(signum, frame):
    global running
    logger.info("Menerima sinyal keluar. Menghentikan seluruh daemon Bot secara tertib...")
    running = False

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


def poll_bot_notif_worker(app, token, allowed_chat):
    """
    Worker thread khusus untuk menangani interaksi tombol inline pada Bot 2
    (seperti tombol '🔄 Restore Data ke VPS Ini' pada auto-backup 30 menit).
    """
    logger.info(f"🟢 [Bot 2 Notif] Listener Callback aktif untuk Bot 2 (Token: ...{token[-6:]})")
    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"

    while running:
        try:
            params = {
                'offset': offset,
                'timeout': 20,
                'allowed_updates': ['callback_query', 'message']
            }
            resp = requests.get(poll_url, params=params, timeout=30)
            if resp.status_code != 200:
                time.sleep(3)
                continue

            data = resp.json()
            if not data.get('ok'):
                time.sleep(3)
                continue

            updates = data.get('result', [])
            for update in updates:
                offset = update['update_id'] + 1

                # Tangani Callback Query (Klik tombol Restore)
                if 'callback_query' in update:
                    cb = update['callback_query']
                    user_sender = cb.get('from', {}).get('username') or cb.get('from', {}).get('id')
                    action = cb.get('data', '')
                    logger.info(f"[Bot 2 Notif] Callback dari @{user_sender}: '{action}'")
                    try:
                        handle_notif_callback(app, cb)
                    except Exception as err:
                        logger.error(f"[Bot 2 Notif] Error handle callback {action}: {err}")

        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.RequestException as net_err:
            time.sleep(3)
        except Exception as e:
            logger.error(f"[Bot 2 Notif] Polling error: {e}")
            time.sleep(3)

    logger.info("🔴 [Bot 2 Notif] Listener Worker dihentikan.")


def poll_bot_cs_worker(app, token, allowed_chat):
    """
    Worker thread khusus untuk Bot 1 : CS & Balas Inbox.
    Mendengarkan balasan manual dari admin Telegram dan meneruskannya ke web pengguna.
    """
    logger.info(f"🟢 [Bot 1 CS] Listener Balasan aktif untuk Bot 1 (Token: ...{token[-6:]})")

    # Pastikan webhook dinonaktifkan agar getUpdates selalu diizinkan oleh Telegram API
    try:
        del_res = requests.post(
            f"https://api.telegram.org/bot{token}/deleteWebhook",
            json={"drop_pending_updates": False},
            timeout=10
        )
        logger.info(f"[Bot 1 CS] Webhook status check: {del_res.json().get('description', 'OK')}")
    except Exception as ex_wh:
        logger.warning(f"[Bot 1 CS] Gagal cek deleteWebhook: {ex_wh}")

    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"

    while running:
        try:
            params = {
                'offset': offset,
                'timeout': 20,
                'allowed_updates': ['message', 'callback_query']
            }
            resp = requests.get(poll_url, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"[Bot 1 CS] Polling HTTP {resp.status_code}: {resp.text}")
                time.sleep(3)
                continue

            data = resp.json()
            if not data.get('ok'):
                logger.warning(f"[Bot 1 CS] Polling not OK: {data.get('description')}")
                time.sleep(3)
                continue

            updates = data.get('result', [])
            if updates:
                logger.info(f"[Bot 1 CS] Mendapatkan {len(updates)} update baru dari Telegram.")

            for update in updates:
                offset = update['update_id'] + 1
                try:
                    logger.info(f"[Bot 1 CS] Memproses update ID: {update.get('update_id')}")
                    handle_cs_bot_update(app, update, token)
                except Exception as err:
                    logger.error(f"[Bot 1 CS] Error handle update {update.get('update_id')}: {err}", exc_info=True)

        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.RequestException as req_err:
            logger.warning(f"[Bot 1 CS] Network request error: {req_err}")
            time.sleep(3)
        except Exception as e:
            logger.error(f"[Bot 1 CS] Polling error: {e}", exc_info=True)
            time.sleep(3)

    logger.info("🔴 [Bot 1 CS] Listener Worker dihentikan.")


def main():
    admin_token, admin_chat = get_bot_admin_credentials()
    notif_token, notif_chat = get_bot_notif_credentials()
    cs_token, cs_chat = get_bot_cs_credentials()

    if not admin_token and not notif_token and not cs_token:
        logger.error("Token bot Telegram belum diatur di .env! Bot tidak dapat dijalankan.")
        sys.exit(1)

    logger.info("=======================================================")
    logger.info("   GARUDATEL v2 - TELEGRAM BOT UNIFIED DAEMON")
    logger.info("=======================================================")
    logger.info(f"Target Chat ID Admin Terdaftar: {admin_chat or 'Semua Admin'}")

    app = create_app()

    # 1. Jalankan Bot 1 CS Listener di thread terpisah jika token ada
    if cs_token:
        cs_thread = threading.Thread(
            target=poll_bot_cs_worker,
            args=(app, cs_token, cs_chat),
            daemon=True,
            name="BotCSWorker"
        )
        cs_thread.start()
        logger.info(f"🚀 [Bot 1 CS] Bot 1 CS Listener aktif (Token: ...{cs_token[-6:]})")

    # 2. Jalankan Bot 2 Notif Listener di thread terpisah jika token berbeda
    if notif_token and notif_token != admin_token and notif_token != cs_token:
        notif_thread = threading.Thread(
            target=poll_bot_notif_worker,
            args=(app, notif_token, notif_chat),
            daemon=True,
            name="BotNotifWorker"
        )
        notif_thread.start()
    else:
        logger.info("[Bot Daemon] Bot 2 menggunakan token yang sama dengan Bot 3 atau tidak diatur terpisah.")

    if not admin_token:
        logger.info("[Bot Daemon] BOT_ADMIN_TOKEN tidak diatur. Hanya menjalankan Bot CS/Notif listener.")
        while running:
            time.sleep(1)
        return

    # Validasi token Bot 3
    try:
        me_res = requests.get(f"https://api.telegram.org/bot{admin_token}/getMe", timeout=15)
        me_data = me_res.json()
        if me_data.get('ok'):
            bot_user = me_data.get('result', {}).get('username', 'UnknownBot')
            logger.info(f"✅ Bot 3 Admin Terhubung: @{bot_user}")
        else:
            logger.error(f"❌ Gagal verifikasi Bot Admin Token: {me_data.get('description')}")
    except Exception as e:
        logger.warning(f"Koneksi awal Bot 3 mengalami kendala: {e}. Tetap melanjutkan polling loop...")

    offset = 0
    poll_url = f"https://api.telegram.org/bot{admin_token}/getUpdates"
    logger.info("🟢 Bot 3 Siap! Memulai Long Polling Panel Admin...")

    while running:
        try:
            params = {
                'offset': offset,
                'timeout': 20,
                'allowed_updates': ['message', 'callback_query']
            }
            resp = requests.get(poll_url, params=params, timeout=30)
            if resp.status_code != 200:
                logger.warning(f"Telegram returned HTTP {resp.status_code}: {resp.text}")
                time.sleep(3)
                continue

            data = resp.json()
            if not data.get('ok'):
                logger.warning(f"Telegram error response: {data}")
                time.sleep(3)
                continue

            updates = data.get('result', [])
            for update in updates:
                offset = update['update_id'] + 1

                # 1. Handle Callback Query (Klik Tombol Inline)
                if 'callback_query' in update:
                    cb = update['callback_query']
                    user_sender = cb.get('from', {}).get('username') or cb.get('from', {}).get('id')
                    action = cb.get('data', '')
                    logger.info(f"[Bot 3 Tombol] Klik dari @{user_sender}: '{action}'")

                    # Jika callback restore diklik pada bot ini
                    if action.startswith('restore_'):
                        try:
                            handle_notif_callback(app, cb)
                        except Exception as err:
                            logger.error(f"Error executing restore callback {action}: {err}")
                    else:
                        try:
                            handle_admin_callback(app, cb)
                        except Exception as err:
                            logger.error(f"Error executing admin callback {action}: {err}")

                # 2. Handle Text Message (/start, /menu, /otp)
                elif 'message' in update:
                    msg = update['message']
                    user_sender = msg.get('from', {}).get('username') or msg.get('from', {}).get('id')
                    text = msg.get('text', '')
                    logger.info(f"[Bot 3 Pesan] Pesan dari @{user_sender}: '{text}'")
                    try:
                        handle_admin_message(app, msg)
                    except Exception as err:
                        logger.error(f"Error executing message {text}: {err}")

        except requests.exceptions.Timeout:
            continue
        except requests.exceptions.RequestException as net_err:
            logger.warning(f"Kendala jaringan Telegram: {net_err}. Reconnecting in 3s...")
            time.sleep(3)
        except Exception as general_err:
            logger.error(f"Unexpected error in polling loop: {general_err}")
            time.sleep(3)

    logger.info("Bot Daemon dimatikan dengan tertib. Sampai jumpa!")


if __name__ == '__main__':
    main()
