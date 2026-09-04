#!/usr/bin/env python3
"""
================================================================================
GARUDATEL v2 - TELEGRAM BOT 3 : RUNNER PANEL ADMIN INTERAKTIF
================================================================================
Menjalankan daemon long-polling Telegram untuk Bot 3 (Panel Admin).
Mendukung interaksi tombol inline button, pemrosesan callback query,
serta perintah darurat seperti /otp <nomor> dan perintah menu utama.
================================================================================
"""

import sys
import os
import time
import signal
import logging
import requests
from dotenv import load_dotenv

# Set base dir
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [Bot 3 Admin] %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

from app import create_app
from app.services.telegram_service import (
    get_bot_admin_credentials,
    handle_admin_callback,
    handle_admin_message
)

# Flag stop
running = True

def handle_exit(signum, frame):
    global running
    logger.info("Menerima sinyal keluar. Menghentikan Bot Admin secara aman...")
    running = False

signal.signal(signal.SIGINT, handle_exit)
signal.signal(signal.SIGTERM, handle_exit)


def main():
    token, allowed_chat = get_bot_admin_credentials()
    if not token:
        logger.error("BOT_ADMIN_TOKEN belum diatur di file .env! Bot tidak dapat dijalankan.")
        logger.info("Silakan atur BOT_ADMIN_TOKEN dan BOT_ADMIN_CHAT_ID di .env terlebih dahulu.")
        sys.exit(1)

    logger.info("=======================================================")
    logger.info("   GARUDATEL v2 - BOT 3 ADMIN TELEGRAM DAEMON")
    logger.info("=======================================================")
    logger.info(f"Target Chat ID Admin Terdaftar: {allowed_chat or 'Semua (Perlu dikunci ke ID Admin demi keamanan)'}")
    logger.info("Menghubungkan ke Telegram API...")

    app = create_app()

    # Validasi token ke Telegram getMe
    try:
        me_res = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=15)
        me_data = me_res.json()
        if me_data.get('ok'):
            bot_user = me_data.get('result', {}).get('username', 'UnknownBot')
            logger.info(f"✅ Bot Terhubung: @{bot_user}")
        else:
            logger.error(f"❌ Gagal verifikasi Bot Token: {me_data.get('description')}")
            sys.exit(1)
    except Exception as e:
        logger.warning(f"Koneksi awal ke Telegram mengalami kendala: {e}. Tetap melanjutkan polling loop...")

    offset = 0
    poll_url = f"https://api.telegram.org/bot{token}/getUpdates"

    logger.info("🟢 Bot 3 Siap! Memulai Long Polling...")

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
                    logger.info(f"[Tombol] Klik dari @{user_sender}: '{action}'")
                    try:
                        handle_admin_callback(app, cb)
                    except Exception as err:
                        logger.error(f"Error executing callback {action}: {err}")

                # 2. Handle Text Message (/start, /menu, /otp)
                elif 'message' in update:
                    msg = update['message']
                    user_sender = msg.get('from', {}).get('username') or msg.get('from', {}).get('id')
                    text = msg.get('text', '')
                    logger.info(f"[Pesan] Pesan dari @{user_sender}: '{text}'")
                    try:
                        handle_admin_message(app, msg)
                    except Exception as err:
                        logger.error(f"Error executing message {text}: {err}")

        except requests.exceptions.Timeout:
            # Timeout biasa pada long-polling, lanjutkan
            continue
        except requests.exceptions.RequestException as net_err:
            logger.warning(f"Kendala jaringan Telegram: {net_err}. Reconnecting in 3s...")
            time.sleep(3)
        except Exception as general_err:
            logger.error(f"Unexpected error in polling loop: {general_err}")
            time.sleep(3)

    logger.info("Bot 3 Admin dimatikan dengan tertib. Sampai jumpa!")

if __name__ == '__main__':
    main()
