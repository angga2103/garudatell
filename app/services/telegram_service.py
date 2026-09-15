import os
import json
import requests
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

# Standardisasi Timezone WIB (Waktu Indonesia Barat / GMT+7)
WIB_TZ = timezone(timedelta(hours=7))

def get_wib_now():
    """Mengembalikan objek datetime saat ini dalam Waktu Indonesia Barat (WIB / GMT+7)."""
    return datetime.now(WIB_TZ)

def format_wib(dt=None, fmt='%Y-%m-%d %H:%M:%S'):
    """Format datetime ke string WIB yang akurat tanpa selisih jam."""
    if dt is None:
        dt = get_wib_now()
    elif isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt)
        except Exception:
            return dt
    if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
        # Jika waktu naive dari database (standar UTC), konversi ke UTC lalu ke WIB
        dt = dt.replace(tzinfo=timezone.utc).astimezone(WIB_TZ)
    elif hasattr(dt, 'astimezone'):
        dt = dt.astimezone(WIB_TZ)
    return dt.strftime(fmt)

def clean_str(val):
    if val is None:
        return ""
    return str(val).strip().strip("'").strip('"')

def get_bot_cs_credentials():
    """Mengambil Token dan Chat ID untuk Bot 1 : CS & Balas Inbox."""
    token = clean_str(os.getenv('BOT_CS_TOKEN'))
    chat_id = clean_str(os.getenv('BOT_CS_CHAT_ID'))
    return token, chat_id

def send_cs_ticket(ticket, transaction=None):
    """
    Mengirimkan laporan tiket bantuan CS ke Bot 1 : CS & Balas Inbox di Telegram.
    
    Args:
        ticket (SupportTicket): Objek tiket keluhan
        transaction (Transaction, optional): Objek transaksi terkait jika ada
        
    Returns:
        tuple (bool, str): (Status keberhasilan, Pesan hasil)
    """
    token, chat_id = get_bot_cs_credentials()
    if not token or not chat_id:
        err_msg = "BOT_CS_TOKEN atau BOT_CS_CHAT_ID belum dikonfigurasi di file .env"
        logger.warning(err_msg)
        return False, err_msg

    # Susun Pesan HTML Telegram yang Rapi
    lines = [
        f"🎫 <b>TIKET BANTUAN CS BARU #{ticket.ticket_number}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>Pelapor:</b> {ticket.user_name}",
        f"📱 <b>No. HP:</b> <code>{ticket.user_phone}</code>",
        f"📂 <b>Kategori:</b> {ticket.category}",
        f"⏰ <b>Waktu:</b> {ticket.created_at_wib}",
        ""
    ]

    if transaction:
        lines.append("📦 <b>DATA TRANSAKSI TERKAIT:</b>")
        lines.append(f"• <b>Ref ID:</b> <code>{transaction.ref_id}</code>")
        lines.append(f"• <b>Produk:</b> {transaction.product_name or '-'}")
        lines.append(f"• <b>Tujuan:</b> <code>{transaction.target_number or '-'}</code>")
        lines.append(f"• <b>Status:</b> <b>{transaction.status}</b>")
        lines.append(f"• <b>Nominal:</b> Rp {transaction.amount:,.0f}")
        if transaction.sn:
            lines.append(f"• <b>SN/Ket:</b> <code>{transaction.sn}</code>")
        lines.append("")
    else:
        lines.append("ℹ️ <i>Tiket Pertanyaan Umum (Tanpa Spesifik Transaksi)</i>")
        lines.append("")

    lines.append("💬 <b>DETAIL KELUHAN / PERTANYAAN:</b>")
    lines.append(f"<i>\"{ticket.message}\"</i>")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    # Link direct WhatsApp
    wa_num = ticket.clean_phone_for_wa
    if wa_num:
        try:
            from app.services.setting_service import get_store_name
            s_name = get_store_name()
        except Exception:
            s_name = "GarudaTel"
        lines.append(f"👉 <a href=\"https://wa.me/{wa_num}?text=Halo%20{ticket.user_name},%20terkait%20tiket%20bantuan%20{ticket.ticket_number}%20di%20{urllib.parse.quote(s_name)}:\">Klik untuk Balas via WhatsApp Pelapor</a>")

    full_text = "\n".join(lines)

    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": full_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        resp = requests.post(api_url, json=payload, timeout=12)
        res_data = resp.json()

        if res_data.get('ok'):
            ticket.telegram_sent = True
            ticket.telegram_response = f"Pesan terkirim ke Telegram ID {chat_id}"
            return True, "Tiket berhasil dikirim ke Bot CS Telegram!"
        else:
            ticket.telegram_sent = False
            desc = res_data.get('description', 'Unknown error')
            ticket.telegram_response = f"Telegram Error: {desc}"
            logger.error(f"Gagal kirim ke Bot CS Telegram: {desc}")
            return False, f"Gagal kirim ke Telegram: {desc}"

    except Exception as e:
        ticket.telegram_sent = False
        ticket.telegram_response = f"Exception: {str(e)}"
        logger.error(f"Koneksi ke Bot CS Telegram gagal: {str(e)}")
        return False, f"Koneksi error: {str(e)}"


def send_emergency_otp_request(phone, otp_code=None, user_name=None, action_type='Pendaftaran / Masuk', expiry_minutes=10, request_id=None, status='PENDING'):
    """
    Mengirimkan laporan Permintaan Bantuan OTP Darurat (Manual) ke Bot 1 : CS & Balas Inbox di Telegram.
    Mendukung status PENDING (Menunggu persetujuan admin) dan tautan direct WhatsApp saat disetujui.
    """
    import urllib.parse

    token, chat_id = get_bot_cs_credentials()

    # Bersihkan dan format nomor WhatsApp (awalan 62)
    clean_num = ''.join(filter(str.isdigit, str(phone or '')))
    if clean_num.startswith('0'):
        clean_num = '62' + clean_num[1:]

    display_name = user_name or 'Pengguna / Calon Member'
    wib_now = format_wib(fmt='%d/%m/%Y %H:%M WIB')

    # Susun Teks Pesan WhatsApp jika kode OTP tersedia
    wa_direct_link = ""
    if otp_code:
        try:
            from app.services.setting_service import get_store_name
            s_name = get_store_name()
        except Exception:
            s_name = "GarudaTel"

        wa_message = (
            f"Halo kak {display_name}!\n\n"
            f"Berikut adalah *Kode OTP Darurat* Anda untuk akun {s_name}:\n\n"
            f"👉 *{otp_code}*\n\n"
            f"⚠️ *PENTING:* Kode OTP ini bersifat rahasia dan *HANYA BERLAKU {expiry_minutes} MENIT* "
            f"khusus untuk nomor ini ({clean_num}).\n\n"
            f"Silakan masukkan kode pada formulir verifikasi Anda di website {s_name}. Terima kasih!"
        )
        encoded_wa_msg = urllib.parse.quote(wa_message)
        wa_direct_link = f"https://wa.me/{clean_num}?text={encoded_wa_msg}"

    # Susun Pesan Telegram untuk Tim CS
    status_badge = "⏳ <b>MENUNGGU PERSETUJUAN ADMIN</b>" if status == 'PENDING' else f"✅ <b>{status}</b>"
    lines = [
        "🚨 <b>PERMINTAAN BANTUAN OTP MANUAL BARU</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🆔 <b>ID Request:</b> #{request_id or '-'}",
        f"👤 <b>Nama:</b> {display_name}",
        f"📱 <b>Nomor WhatsApp:</b> <code>{clean_num}</code>",
        f"🎯 <b>Keperluan:</b> {action_type}",
        f"📊 <b>Status:</b> {status_badge}",
        f"⏰ <b>Waktu Request:</b> {wib_now}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ <i>Layanan Bot WhatsApp otomatis terdeteksi sedang offline/antrean.</i>",
        "👉 Buka Panel Web Admin di menu <b>Bantuan OTP Manual</b> untuk menyetujui atau menolak permohonan ini."
    ]

    if wa_direct_link and status == 'APPROVED':
        lines.append("")
        lines.append(f"👉 <a href=\"{wa_direct_link}\">KLIK UNTUK KIRIM KODE OTP VIA WHATSAPP</a>")

    full_text = "\n".join(lines)

    if not token or not chat_id:
        err_msg = "BOT_CS_TOKEN atau BOT_CS_CHAT_ID belum dikonfigurasi di file .env"
        logger.warning(err_msg)
        return False, err_msg, wa_direct_link

    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": full_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        resp = requests.post(api_url, json=payload, timeout=12)
        res_data = resp.json()

        if res_data.get('ok'):
            return True, "Permintaan OTP Darurat berhasil dikirim ke Bot CS Telegram!", wa_direct_link
        else:
            desc = res_data.get('description', 'Unknown error')
            logger.error(f"Gagal kirim OTP Darurat ke Bot CS Telegram: {desc}")
            return False, f"Telegram Error: {desc}", wa_direct_link

    except Exception as e:
        logger.error(f"Koneksi ke Bot CS Telegram gagal: {str(e)}")
        return False, f"Koneksi error: {str(e)}", wa_direct_link


# ==============================================================================
# BOT 2 : NOTIFIKASI TRANSAKSI MASUK & LAPORAN BACKUP
# ==============================================================================
def get_bot_notif_credentials():
    """Mengambil Token dan Chat ID untuk Bot 2 : Notifikasi."""
    token = clean_str(os.getenv('BOT_NOTIF_TOKEN'))
    chat_id = clean_str(os.getenv('BOT_NOTIF_CHAT_ID'))
    return token, chat_id

def send_trx_notification(trx, title="TRANSAKSI MASUK"):
    """
    Mengirimkan notifikasi transaksi ke Bot 2 (Notifikasi) di Telegram.
    
    Args:
        trx (Transaction): Objek transaksi
        title (str): Judul notifikasi (misal: TRANSAKSI BARU, TRANSAKSI BERHASIL, TRANSAKSI GAGAL)
    """
    token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        return False, "Kredensial BOT_NOTIF belum diatur di .env"

    wib_now = format_wib(fmt='%d/%m/%Y %H:%M WIB')

    # Status Emoji
    status_val = getattr(trx, 'status', '')
    status_upper = str(status_val or '').upper()
    if status_upper == 'SUCCESS':
        icon = "✅"
    elif status_upper in ['FAILED', 'EXPIRED', 'CANCELLED']:
        icon = "❌"
    elif status_upper in ['PROCESSING', 'PAID']:
        icon = "⚡"
    else:
        icon = "⏳"

    ref_id = getattr(trx, 'ref_id', '-')
    product_name = getattr(trx, 'product_name', '-') or '-'
    target_number = getattr(trx, 'target_number', '-') or '-'
    amount = float(getattr(trx, 'amount', 0) or 0)
    payment_method = getattr(trx, 'payment_method', '-') or '-'
    payment_status = getattr(trx, 'payment_status', 'UNPAID') or 'UNPAID'
    user_id = getattr(trx, 'user_id', '-')
    sn = getattr(trx, 'sn', None)

    lines = [
        f"{icon} <b>{title.upper()}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 <b>Ref ID:</b> <code>{ref_id}</code>",
        f"📦 <b>Produk:</b> {product_name}",
        f"📱 <b>Tujuan:</b> <code>{target_number}</code>",
        f"💰 <b>Nominal:</b> Rp {amount:,.0f}",
        f"💳 <b>Metode:</b> {payment_method} (<b>{payment_status}</b>)",
        f"📊 <b>Status:</b> <b>{status_upper}</b>",
        f"👤 <b>User ID:</b> #{user_id}",
        f"⏰ <b>Waktu:</b> {wib_now}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    if sn:
        lines.append(f"🔖 <b>SN/Keterangan:</b> <code>{sn}</code>")

    if "SALDO PROVIDER HABIS" in title.upper():
        lines.append("")
        lines.append("🚨 <b>PERHATIAN SERVER ADMIN:</b>")
        lines.append("⚠️ Transaksi ini GAGAL karena <b>SALDO DEPOSIT PROVIDER HABIS / KURANG</b>!")
        lines.append("👉 Harap segera lakukan Top Up saldo deposit di portal provider terkait (VIP-Reseller / Digiflazz) agar transaksi pengguna tidak terus gagal.")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    full_text = "\n".join(lines)

    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": full_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        r = requests.post(api_url, json=payload, timeout=10)
        return r.status_code == 200, r.text
    except Exception as e:
        logger.error(f"[Bot 2 Notif] Gagal kirim notifikasi transaksi: {e}")
        return False, str(e)


def async_send_trx_notification(trx, title="TRANSAKSI MASUK"):
    """
    Mengirimkan notifikasi transaksi ke Bot 2 secara asinkron di background thread
    agar tidak memperlambat respon web atau callback transaksi.
    """
    import threading
    try:
        trx_snapshot = {
            'ref_id': getattr(trx, 'ref_id', '-'),
            'product_name': getattr(trx, 'product_name', '-'),
            'target_number': getattr(trx, 'target_number', '-'),
            'amount': float(getattr(trx, 'amount', 0) or 0),
            'payment_method': getattr(trx, 'payment_method', '-'),
            'payment_status': getattr(trx, 'payment_status', 'UNPAID'),
            'status': getattr(trx, 'status', '-'),
            'user_id': getattr(trx, 'user_id', '-'),
            'sn': getattr(trx, 'sn', None)
        }
        
        class TrxProxy:
            def __init__(self, d):
                for k, v in d.items():
                    setattr(self, k, v)

        proxy = TrxProxy(trx_snapshot)
        thread = threading.Thread(target=send_trx_notification, args=(proxy, title), daemon=True)
        thread.start()
        return True
    except Exception as e:
        logger.error(f"[Bot 2 Async] Error starting notification thread: {e}")
        return False


def send_backup_notification(backup_file_path=None, status="SUKSES", details="", display_filename=None):
    """
    Mengirimkan laporan auto-backup ke Bot 2 (Notifikasi & Backup) di Telegram,
    melampirkan file zip portabel dengan tombol inline '🔄 Restore Data ke VPS Ini'
    dan panduan migrasi bencana untuk VPS baru persis seperti referensi template.
    """
    token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        return False, "Kredensial BOT_NOTIF belum diatur di .env"

    wib_now_str = format_wib(fmt='%Y-%m-%d %H:%M:%S')

    if display_filename:
        filename_only = display_filename
    elif backup_file_path:
        filename_only = os.path.basename(backup_file_path)
    else:
        filename_only = f"GarudaTell_Backup_{format_wib(fmt='%Y%m%d_%H%M%S')}.zip"

    # Jika file fisik adalah 'latest_backup.zip', tampilkan nama bertanggal di Telegram
    if filename_only == "latest_backup.zip":
        filename_only = f"GarudaTell_Backup_{format_wib(fmt='%Y%m%d_%H%M%S')}.zip"

    status_badge = "✅ <b>Backup berhasil!</b>" if status == "SUKSES" else f"🚨 <b>Backup status: {status}</b>"

    caption = (
        f"🛡️ <b>GARUDA TELL - AUTO BACKUP</b>\n\n"
        f"📦 <b>File:</b> <code>{filename_only}</code>\n"
        f"🕒 <b>Waktu:</b> {wib_now_str}\n\n"
        f"{status_badge}\n\n"
        f"🛠️ <b>PANDUAN MIGRASI VPS BARU:</b>\n"
        f"1. Sewa VPS Ubuntu 20.04/22.04/24.04 baru\n"
        f"2. Upload ZIP ini ke folder /root/\n"
        f"3. Ekstrak: <code>unzip -o {filename_only} -d /</code>\n"
        f"4. Jalankan: <code>bash /var/www/garudatel/tools/installer_vps_baru.sh</code>"
    )

    if details and status != "SUKSES":
        caption += f"\n\nℹ️ <b>Info:</b> {details}"

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🔄 Restore Data ke VPS Ini", "callback_data": "restore_confirm_prompt"}
            ]
        ]
    }

    try:
        # Jika ada file fisik dan ukuran wajar (< 48MB), kirim sebagai Dokumen Telegram
        if backup_file_path and os.path.exists(backup_file_path):
            doc_url = f"https://api.telegram.org/bot{token}/sendDocument"
            with open(backup_file_path, 'rb') as f:
                files = {'document': (filename_only, f, 'application/zip')}
                data = {
                    'chat_id': chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML',
                    'reply_markup': json.dumps(reply_markup)
                }
                res = requests.post(doc_url, files=files, data=data, timeout=90)
                return res.status_code == 200, res.text
        else:
            msg_url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {
                'chat_id': chat_id,
                'text': caption,
                'parse_mode': 'HTML',
                'reply_markup': reply_markup
            }
            res = requests.post(msg_url, json=payload, timeout=10)
            return res.status_code == 200, res.text
    except Exception as e:
        logger.error(f"[Bot 2 Backup] Gagal kirim laporan backup: {e}")
        return False, str(e)


def handle_notif_callback(app, callback_query):
    """
    Memproses aksi saat tombol inline di Bot 2 (Notifikasi & Backup) ditekan.
    Mendukung verifikasi otorisasi dan 1-Click Restore database ke VPS.
    """
    token, allowed_chat = get_bot_notif_credentials()
    if not token:
        return

    query_id = callback_query.get('id')
    message = callback_query.get('message', {})
    chat_id = str(message.get('chat', {}).get('id', ''))
    message_id = message.get('message_id')
    data = callback_query.get('data', '')

    admin_chat = clean_str(os.getenv('BOT_ADMIN_CHAT_ID'))
    # Validasi otorisasi admin (boleh dari NOTIF_CHAT_ID atau ADMIN_CHAT_ID)
    if (allowed_chat and chat_id != str(allowed_chat)) and (admin_chat and chat_id != str(admin_chat)):
        _answer_callback(token, query_id, "Akses ditolak! Anda bukan Admin terdaftar.")
        return

    if data == 'restore_confirm_prompt':
        _answer_callback(token, query_id, "Menyiapkan verifikasi restore...")
        confirm_text = (
            "⚠️ <b>KONFIRMASI RESTORE DATABASE KE VPS INI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Apakah Anda yakin ingin memulihkan database dari file cadangan terbaru ini?\n\n"
            "⚠️ <b>PERINGATAN:</b>\n"
            "• Database saat ini di VPS akan ditimpa dengan data backup ini.\n"
            "• Layanan server web GarudaTel akan otomatis direstart.\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Pilih tindakan Anda di bawah ini:"
        )
        confirm_markup = {
            "inline_keyboard": [
                [
                    {"text": "✅ YA, RESTORE SEKARANG", "callback_data": "restore_do_execute"},
                    {"text": "❌ BATAL", "callback_data": "restore_cancel"}
                ]
            ]
        }
        _send_message(token, chat_id, confirm_text, reply_markup=confirm_markup)

    elif data == 'restore_cancel':
        _answer_callback(token, query_id, "Pemulihan dibatalkan.")
        cancel_text = (
            "❌ <b>PEMULIHAN DATABASE DIBATALKAN</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Operasi pemulihan database tidak dijalankan. Database aktif Anda tetap aman."
        )
        _edit_message(token, chat_id, message_id, cancel_text, None)

    elif data == 'restore_do_execute':
        _answer_callback(token, query_id, "Sedang memulihkan database...")
        _edit_message(token, chat_id, message_id, "⏳ <i>Sedang memulihkan database dari latest_backup.zip dan merestart server... Harap tunggu sebentar.</i>", None)

        from app.core.backup.backup_engine import BackupEngine
        engine = BackupEngine()
        ok, msg = engine.restore_from_latest_backup()

        wib_time = format_wib(fmt='%Y-%m-%d %H:%M:%S WIB')
        if ok:
            # Restart service web agar koneksi db baru termuat
            try:
                import subprocess
                subprocess.run(["sudo", "systemctl", "restart", "garudatel"], check=False, timeout=15)
            except Exception as e:
                logger.warning(f"Gagal restart service web via subprocess: {e}")

            success_text = (
                "✅ <b>RESTORE DATABASE BERHASIL!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Database GarudaTel telah berhasil dipulihkan dari backup terbaru.\n"
                "Layanan web server telah direstart dan berjalan normal kembali.\n\n"
                f"⏰ <b>Waktu:</b> {wib_time}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🌐 <i>Website aktif kembali dan siap melayani transaksi.</i>"
            )
            _edit_message(token, chat_id, message_id, success_text, None)
        else:
            fail_text = (
                "🚨 <b>RESTORE DATABASE GAGAL!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Keterangan kendala:\n<code>{msg}</code>\n\n"
                f"⏰ <b>Waktu:</b> {wib_time}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Database aktif telah dipulihkan ke kondisi sebelum restore (Safety Rollback)."
            )
            _edit_message(token, chat_id, message_id, fail_text, None)


# ==============================================================================
# BOT 3 : PANEL & FITUR ADMIN TELEGRAM (INLINE BUTTON INTERAKTIF)
# ==============================================================================
def get_bot_admin_credentials():
    """Mengambil Token dan Chat ID untuk Bot 3 : Panel Admin."""
    token = clean_str(os.getenv('BOT_ADMIN_TOKEN'))
    chat_id = clean_str(os.getenv('BOT_ADMIN_CHAT_ID'))
    return token, chat_id


def send_sync_report_to_admin_bot(msg, is_cron=True):
    """
    Mengirimkan laporan hasil sinkronisasi produk otomatis Digiflazz ke Bot 3 : Panel & Fitur Admin.
    """
    token, chat_id = get_bot_admin_credentials()
    if not token or not chat_id:
        logger.warning("[Bot 3 Admin] BOT_ADMIN_TOKEN atau BOT_ADMIN_CHAT_ID belum diset di .env")
        return False, "Kredensial Bot 3 belum diatur"

    wib_now = format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')
    title = "🔄 <b>AUTO SINKRONISASI DIGIFLAZZ</b>" if is_cron else "🔄 <b>SINKRONISASI PRODUK DIGIFLAZZ</b>"
    text = (
        f"{title}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📢 <b>Laporan Sistem:</b>\n"
        f"<b>{msg}</b>\n\n"
        f"⏰ <b>Waktu Eksekusi:</b> {wib_now}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "✅ <i>Katalog produk dan status gangguan operator telah tersinkronisasi otomatis.</i>"
    )
    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res = requests.post(api_url, json=payload, timeout=15)
        return res.status_code == 200, res.text
    except Exception as e:
        logger.error(f"[Bot 3 Sync Report] Gagal kirim laporan ke Telegram: {e}")
        return False, str(e)


def get_admin_inline_keyboard():
    """Menghasilkan struktur tombol inline keyboard untuk menu utama Bot Admin."""
    return {
        "inline_keyboard": [
            [
                {"text": "🏪 Cek Toko", "callback_data": "cmd_list_stores"},
                {"text": "📊 Omset Hari Ini", "callback_data": "cmd_stats"}
            ],
            [
                {"text": "💰 Saldo Digiflazz", "callback_data": "cmd_saldo"},
                {"text": "⏳ Trx Pending", "callback_data": "cmd_pending"}
            ],
            [
                {"text": "⚠️ Cek Saldo Minim", "callback_data": "cmd_scan_low_bal"},
                {"text": "🔄 Sync Digiflazz", "callback_data": "cmd_sync_digi"}
            ],
            [
                {"text": "🎫 Tiket CS Masuk", "callback_data": "cmd_tickets"},
                {"text": "💾 Backup DB Sekarang", "callback_data": "cmd_backup"}
            ],
            [
                {"text": "🔄 Sync VIP Games", "callback_data": "cmd_sync_vip"},
                {"text": "🆘 Buat OTP Darurat", "callback_data": "cmd_otp_info"}
            ],
            [
                {"text": "📱 Status / Pairing WA", "callback_data": "cmd_wa_status"},
                {"text": "🩺 Status Sistem VPS", "callback_data": "cmd_system"}
            ],
            [
                {"text": "🔄 Refresh Menu", "callback_data": "cmd_menu"}
            ]
        ]
    }


def render_stores_keyboard(page=1, per_page=8):
    """Menghasilkan struktur keyboard daftar toko/member dengan penomoran halaman."""
    from app.models.user import User
    import math

    stores = User.query.order_by(User.name.asc()).all()
    total_stores = len(stores)
    total_pages = max(1, math.ceil(total_stores / per_page))
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    current_stores = stores[start_idx:end_idx]

    keyboard = []
    # 2 toko per baris
    row = []
    for s in current_stores:
        s_name = (s.name or f"User #{s.id}")[:18]
        row.append({"text": f"🏢 {s_name}", "callback_data": f"store_view_{s.id}"})
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Navigasi halaman jika lebih dari 1 halaman
    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"cmd_stores_p_{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"cmd_stores_p_{page + 1}"})
    if nav_row:
        keyboard.append(nav_row)

    # Tombol kembali ke menu utama
    keyboard.append([{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}])

    return {
        "keyboard": {"inline_keyboard": keyboard},
        "page": page,
        "total_pages": total_pages,
        "total_stores": total_stores
    }


def get_back_button():
    """Tombol kembali ke menu utama admin."""
    return {
        "inline_keyboard": [
            [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
        ]
    }


def perform_database_backup():
    """
    Melakukan snapshot database SQLite secara online (non-blocking WAL mode)
    dan mengompresinya dengan gzip ke storage/backups/.
    Mengembalikan path file hasil backup (.gz).
    """
    import sqlite3
    import gzip
    import shutil
    import time

    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    db_source = os.path.join(base_dir, 'app', 'garudatel.db')
    backup_dir = os.path.join(base_dir, 'storage', 'backups')
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = time.strftime('%Y%m%d_%H%M%S')
    raw_dest = os.path.join(backup_dir, f"garudatel_{timestamp}.db")
    gz_dest = raw_dest + ".gz"

    if not os.path.exists(db_source):
        raise FileNotFoundError(f"Database sumber {db_source} tidak ditemukan!")

    # Online SQLite Backup API (WAL-safe)
    src_conn = sqlite3.connect(db_source)
    dst_conn = sqlite3.connect(raw_dest)
    with dst_conn:
        src_conn.backup(dst_conn, pages=100)
    dst_conn.close()
    src_conn.close()

    # Gzip compress
    with open(raw_dest, 'rb') as f_in:
        with gzip.open(gz_dest, 'wb') as f_out:
            shutil.copyfileobj(f_in, f_out)

    if os.path.exists(raw_dest):
        os.remove(raw_dest)

    return gz_dest


def handle_admin_callback(app, callback_query):
    """
    Memproses aksi saat tombol inline ditekan oleh Admin di Telegram Bot 3.
    """
    token, allowed_chat = get_bot_admin_credentials()
    if not token:
        return

    query_id = callback_query.get('id')
    message = callback_query.get('message', {})
    chat_id = str(message.get('chat', {}).get('id', ''))
    message_id = message.get('message_id')
    data = callback_query.get('data', '')

    # Validasi otorisasi chat_id admin
    if allowed_chat and chat_id != str(allowed_chat):
        _answer_callback(token, query_id, "Akses ditolak! Anda bukan Admin terdaftar.")
        return

    _answer_callback(token, query_id, "Memproses...")

    with app.app_context():
        from app.models.transaction import Transaction
        from app.models.user import User
        from app.models.support_ticket import SupportTicket
        from app.models.product import Product
        from app.services.digiflazz import check_balance, sync_products
        from app.services.vip_reseller import VIPReseller
        from datetime import datetime

        if data == 'cmd_menu':
            text = (
                "🦅 <b>PANEL KONTROL ADMIN GARUDATEL v2</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Selamat datang di Panel Cepat Telegram Admin.\n"
                "Pilih salah satu tombol di bawah untuk menjalankan fitur:"
            )
            _edit_message(token, chat_id, message_id, text, get_admin_inline_keyboard())

        # ==========================================================
        # FITUR TOKO / MEMBER (CEK TOKO, OMSET, TRX GAGAL, SALDO)
        # ==========================================================
        elif data == 'cmd_list_stores' or data.startswith('cmd_stores_p_'):
            try:
                page = int(data.replace('cmd_stores_p_', '')) if data.startswith('cmd_stores_p_') else 1
            except Exception:
                page = 1
            rendered = render_stores_keyboard(page=page, per_page=8)
            text = (
                f"🏪 <b>DAFTAR TOKO / MEMBER (Hal {rendered['page']}/{rendered['total_pages']})</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Ditemukan <b>{rendered['total_stores']}</b> toko/member terdaftar.\n\n"
                "Silakan klik salah satu toko di bawah untuk melihat:\n"
                "• Omset & performa transaksi hari ini\n"
                "• Riwayat produk apa saja yang gagal\n"
                "• Tambah / potong saldo manual toko\n"
            )
            _edit_message(token, chat_id, message_id, text, rendered['keyboard'])

        elif data.startswith('store_view_'):
            try:
                u_id = int(data.replace('store_view_', ''))
                target_user = User.query.get(u_id)
            except Exception:
                target_user = None

            if not target_user:
                _edit_message(token, chat_id, message_id, "❌ Data toko tidak ditemukan!", get_back_button())
                return

            wib_now = get_wib_now()
            today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start = today_start_wib.astimezone(timezone.utc).replace(tzinfo=None)

            from app.extensions import db
            today_total = Transaction.query.filter(Transaction.user_id == target_user.id, Transaction.created_at >= today_start).count()
            today_success = Transaction.query.filter(Transaction.user_id == target_user.id, Transaction.created_at >= today_start, Transaction.status == 'SUCCESS').count()
            today_failed = Transaction.query.filter(
                Transaction.user_id == target_user.id,
                Transaction.created_at >= today_start,
                Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL'])
            ).count()
            today_revenue = db.session.query(db.func.sum(Transaction.amount)).filter(
                Transaction.user_id == target_user.id,
                Transaction.created_at >= today_start,
                Transaction.status == 'SUCCESS',
                ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT'])
            ).scalar() or 0.0

            text = (
                f"🏪 <b>PROFIL & ANALISA TOKO</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏢 <b>Nama Toko:</b> {target_user.name}\n"
                f"🆔 <b>ID Pengguna:</b> <code>#{target_user.id}</code>\n"
                f"📱 <b>WhatsApp:</b> <code>{target_user.phone}</code>\n"
                f"👑 <b>Golongan:</b> {target_user.role.upper()}\n"
                f"💰 <b>Saldo Saat Ini:</b> <code>Rp {target_user.balance:,.0f}</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>PERFORMA TRANSAKSI HARI INI:</b>\n"
                f"• <b>Omset Penjualan:</b> <code>Rp {today_revenue:,.0f}</code>\n"
                f"• <b>Total Transaksi:</b> {today_total} transaksi\n"
                f"• <b>Status:</b> ✅ {today_success} Sukses  |  ❌ {today_failed} Gagal\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Silakan pilih aksi di bawah ini:"
            )

            store_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "❌ Cek Trx Gagal", "callback_data": f"store_failed_{target_user.id}"},
                        {"text": "📋 5 Trx Terakhir", "callback_data": f"store_recent_{target_user.id}"}
                    ],
                    [
                        {"text": "➕ Tambah Saldo", "callback_data": f"store_topup_{target_user.id}"},
                        {"text": "➖ Kurangi Saldo", "callback_data": f"store_deduct_{target_user.id}"}
                    ],
                    [
                        {"text": "« Daftar Toko", "callback_data": "cmd_list_stores"},
                        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
                    ]
                ]
            }
            _edit_message(token, chat_id, message_id, text, store_keyboard)

        elif data.startswith('store_failed_'):
            try:
                u_id = int(data.replace('store_failed_', ''))
                target_user = User.query.get(u_id)
            except Exception:
                target_user = None

            if not target_user:
                _edit_message(token, chat_id, message_id, "❌ Toko tidak ditemukan!", get_back_button())
                return

            failed_trxs = Transaction.query.filter(
                Transaction.user_id == target_user.id,
                Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL'])
            ).order_by(Transaction.id.desc()).limit(8).all()

            if not failed_trxs:
                text = (
                    f"✅ <b>TIDAK ADA TRANSAKSI GAGAL</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Toko <b>{target_user.name}</b> tidak memiliki riwayat transaksi gagal terkini."
                )
            else:
                lines = [
                    f"❌ <b>RIWAYAT PRODUK GAGAL: {target_user.name}</b>",
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ]
                for idx, t in enumerate(failed_trxs, 1):
                    t_time = format_wib(t.created_at, '%d/%m %H:%M') if t.created_at else '-'
                    reason = t.sn or 'Ditolak provider / Saldo tidak cukup'
                    lines.append(
                        f"<b>{idx}. {t.product_name or 'Produk'}</b>\n"
                        f"• Ref: <code>{t.ref_id}</code> | Rp {t.amount:,.0f}\n"
                        f"• Tujuan: <code>{t.target_number or '-'}</code> | {t_time} WIB\n"
                        f"• ⚠️ Alasan: <i>{reason}</i>\n"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                text = "\n".join(lines)

            markup = {
                "inline_keyboard": [
                    [{"text": "« Kembali ke Profil Toko", "callback_data": f"store_view_{target_user.id}"}],
                    [{"text": "« Daftar Toko", "callback_data": "cmd_list_stores"}]
                ]
            }
            _edit_message(token, chat_id, message_id, text, markup)

        elif data.startswith('store_recent_'):
            try:
                u_id = int(data.replace('store_recent_', ''))
                target_user = User.query.get(u_id)
            except Exception:
                target_user = None

            if not target_user:
                _edit_message(token, chat_id, message_id, "❌ Toko tidak ditemukan!", get_back_button())
                return

            recents = Transaction.query.filter_by(user_id=target_user.id).order_by(Transaction.id.desc()).limit(5).all()
            if not recents:
                text = f"ℹ️ Toko <b>{target_user.name}</b> belum memiliki riwayat transaksi apapun."
            else:
                lines = [
                    f"📋 <b>5 TRANSAKSI TERAKHIR: {target_user.name}</b>",
                    "━━━━━━━━━━━━━━━━━━━━━━"
                ]
                for idx, r in enumerate(recents, 1):
                    icon = "✅" if r.status == 'SUCCESS' else ("❌" if r.status in ['FAILED', 'CANCELLED'] else "⏳")
                    r_time = format_wib(r.created_at, '%d/%m %H:%M') if r.created_at else '-'
                    lines.append(
                        f"{icon} <b>{r.product_name or 'Produk'}</b> ({r.status})\n"
                        f"• Ref: <code>{r.ref_id}</code> | Rp {r.amount:,.0f}\n"
                        f"• Tujuan: <code>{r.target_number or '-'}</code> | {r_time} WIB\n"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                text = "\n".join(lines)

            markup = {
                "inline_keyboard": [
                    [{"text": "« Kembali ke Profil Toko", "callback_data": f"store_view_{target_user.id}"}],
                    [{"text": "« Daftar Toko", "callback_data": "cmd_list_stores"}]
                ]
            }
            _edit_message(token, chat_id, message_id, text, markup)

        elif data.startswith('store_topup_'):
            try:
                u_id = int(data.replace('store_topup_', ''))
                target_user = User.query.get(u_id)
            except Exception:
                target_user = None

            if not target_user:
                _edit_message(token, chat_id, message_id, "❌ Toko tidak ditemukan!", get_back_button())
                return

            text = (
                f"➕ <b>TAMBAH SALDO TOKO (TOPUP MANUAL)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏢 <b>Toko:</b> {target_user.name} (User #{target_user.id})\n"
                f"💰 <b>Saldo Saat Ini:</b> <code>Rp {target_user.balance:,.0f}</code>\n\n"
                "Pilih nominal cepat di bawah, atau ketik langsung di chat:\n"
                f"👉 <code>/topup {target_user.id} &lt;nominal&gt;</code>\n"
                f"Contoh: <code>/topup {target_user.id} 250000</code>"
            )

            markup = {
                "inline_keyboard": [
                    [
                        {"text": "+50.000", "callback_data": f"store_do_add_{target_user.id}_50000"},
                        {"text": "+100.000", "callback_data": f"store_do_add_{target_user.id}_100000"}
                    ],
                    [
                        {"text": "+200.000", "callback_data": f"store_do_add_{target_user.id}_200000"},
                        {"text": "+500.000", "callback_data": f"store_do_add_{target_user.id}_500000"}
                    ],
                    [
                        {"text": "+1.000.000", "callback_data": f"store_do_add_{target_user.id}_1000000"},
                        {"text": "+2.000.000", "callback_data": f"store_do_add_{target_user.id}_2000000"}
                    ],
                    [
                        {"text": "« Batal / Kembali ke Profil", "callback_data": f"store_view_{target_user.id}"}
                    ]
                ]
            }
            _edit_message(token, chat_id, message_id, text, markup)

        elif data.startswith('store_deduct_'):
            try:
                u_id = int(data.replace('store_deduct_', ''))
                target_user = User.query.get(u_id)
            except Exception:
                target_user = None

            if not target_user:
                _edit_message(token, chat_id, message_id, "❌ Toko tidak ditemukan!", get_back_button())
                return

            text = (
                f"➖ <b>KURANGI / POTONG SALDO TOKO</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏢 <b>Toko:</b> {target_user.name} (User #{target_user.id})\n"
                f"💰 <b>Saldo Saat Ini:</b> <code>Rp {target_user.balance:,.0f}</code>\n\n"
                "Pilih nominal potongan di bawah, atau ketik langsung di chat:\n"
                f"👉 <code>/potong {target_user.id} &lt;nominal&gt;</code>\n"
                f"Contoh: <code>/potong {target_user.id} 75000</code>"
            )

            markup = {
                "inline_keyboard": [
                    [
                        {"text": "-50.000", "callback_data": f"store_do_deduct_{target_user.id}_50000"},
                        {"text": "-100.000", "callback_data": f"store_do_deduct_{target_user.id}_100000"}
                    ],
                    [
                        {"text": "-200.000", "callback_data": f"store_do_deduct_{target_user.id}_200000"},
                        {"text": "-500.000", "callback_data": f"store_do_deduct_{target_user.id}_500000"}
                    ],
                    [
                        {"text": "-1.000.000", "callback_data": f"store_do_deduct_{target_user.id}_1000000"}
                    ],
                    [
                        {"text": "« Batal / Kembali ke Profil", "callback_data": f"store_view_{target_user.id}"}
                    ]
                ]
            }
            _edit_message(token, chat_id, message_id, text, markup)

        elif data.startswith('store_do_add_'):
            parts = data.split('_')
            try:
                u_id = int(parts[3])
                amt = float(parts[4])
            except Exception:
                _edit_message(token, chat_id, message_id, "❌ Parameter saldo tidak valid!", get_back_button())
                return

            from app.services.balance_service import adjust_user_balance_manual
            ok, new_bal, msg, trx = adjust_user_balance_manual(
                user_id=u_id,
                amount=amt,
                action='add',
                note='Topup Cepat via Bot Telegram Admin',
                admin_source='Bot Telegram Admin'
            )

            target_user = User.query.get(u_id)
            store_name = target_user.name if target_user else f"User #{u_id}"

            if ok:
                ref_id = trx.ref_id if trx else '-'
                text = (
                    "✅ <b>TOPUP SALDO TOKO BERHASIL!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏢 <b>Toko:</b> {store_name} (User #{u_id})\n"
                    f"➕ <b>Nominal:</b> <code>+Rp {amt:,.0f}</code>\n"
                    f"💰 <b>Saldo Baru:</b> <code>Rp {new_bal:,.0f}</code>\n"
                    f"🔖 <b>Ref ID:</b> <code>{ref_id}</code>\n"
                    f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Transaksi resmi & mutasi akun toko telah tersinkronisasi."
                )
            else:
                text = f"🚨 <b>GAGAL MENAMBAH SALDO:</b>\n{msg}"

            markup = {
                "inline_keyboard": [
                    [{"text": "« Lihat Profil Toko", "callback_data": f"store_view_{u_id}"}],
                    [{"text": "« Daftar Toko", "callback_data": "cmd_list_stores"}]
                ]
            }
            _edit_message(token, chat_id, message_id, text, markup)

        elif data.startswith('store_do_deduct_'):
            parts = data.split('_')
            try:
                u_id = int(parts[3])
                amt = float(parts[4])
            except Exception:
                _edit_message(token, chat_id, message_id, "❌ Parameter saldo tidak valid!", get_back_button())
                return

            from app.services.balance_service import adjust_user_balance_manual
            ok, new_bal, msg, trx = adjust_user_balance_manual(
                user_id=u_id,
                amount=amt,
                action='deduct',
                note='Penyesuaian Saldo via Bot Telegram Admin',
                admin_source='Bot Telegram Admin'
            )

            target_user = User.query.get(u_id)
            store_name = target_user.name if target_user else f"User #{u_id}"

            if ok:
                ref_id = trx.ref_id if trx else '-'
                text = (
                    "✅ <b>PENGURANGAN SALDO BERHASIL!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏢 <b>Toko:</b> {store_name} (User #{u_id})\n"
                    f"➖ <b>Nominal:</b> <code>-Rp {amt:,.0f}</code>\n"
                    f"💰 <b>Saldo Baru:</b> <code>Rp {new_bal:,.0f}</code>\n"
                    f"🔖 <b>Ref ID:</b> <code>{ref_id}</code>\n"
                    f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Transaksi resmi & mutasi akun toko telah tersinkronisasi."
                )
            else:
                text = f"🚨 <b>GAGAL MENGURANGI SALDO:</b>\n{msg}"

            markup = {
                "inline_keyboard": [
                    [{"text": "« Lihat Profil Toko", "callback_data": f"store_view_{u_id}"}],
                    [{"text": "« Daftar Toko", "callback_data": "cmd_list_stores"}]
                ]
            }
            _edit_message(token, chat_id, message_id, text, markup)

        elif data == 'cmd_saldo':
            is_ok, bal, msg = check_balance()
            if is_ok:
                text = (
                    "💰 <b>INFORMASI SALDO DIGIFLAZZ</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Saldo Tersedia:</b> <code>Rp {bal:,.0f}</code>\n"
                    f"• <b>Status API:</b> Terhubung Normal (200 OK)\n"
                    f"• <b>Update:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}"
                )
            else:
                text = f"🚨 <b>GAGAL CEK SALDO:</b>\n{msg}"
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_stats':
            wib_now = get_wib_now()
            today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start = today_start_wib.astimezone(timezone.utc).replace(tzinfo=None)
            total_trx_today = Transaction.query.filter(Transaction.created_at >= today_start).count()
            success_today = Transaction.query.filter(Transaction.created_at >= today_start, Transaction.status == 'SUCCESS').count()
            pending_today = Transaction.query.filter(Transaction.created_at >= today_start, Transaction.status == 'PENDING').count()
            failed_today = Transaction.query.filter(Transaction.created_at >= today_start, Transaction.status.in_(['FAILED', 'CANCELLED'])).count()
            
            from app.extensions import db
            omset_today = db.session.query(db.func.sum(Transaction.amount)).filter(
                Transaction.created_at >= today_start,
                Transaction.status == 'SUCCESS',
                Transaction.payment_method != 'admin_manual'
            ).scalar() or 0.0

            total_users = User.query.count()
            total_balance = db.session.query(db.func.sum(User.balance)).scalar() or 0.0

            rate = round((success_today / total_trx_today * 100), 1) if total_trx_today > 0 else 0

            text = (
                "📊 <b>RINGKASAN OMSET & TRANSAKSI HARI INI</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💵 <b>Omset Berhasil:</b> <code>Rp {omset_today:,.0f}</code>\n"
                f"🔄 <b>Total Transaksi:</b> {total_trx_today} transaksi\n"
                f"✅ <b>Sukses:</b> {success_today} | ⏳ <b>Pending:</b> {pending_today} | ❌ <b>Gagal:</b> {failed_today}\n"
                f"📈 <b>Success Rate:</b> {rate}%\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Total Member:</b> {total_users} orang\n"
                f"💳 <b>Total Saldo Member:</b> Rp {total_balance:,.0f}\n"
                f"⏰ <i>Waktu: {format_wib(fmt='%d/%m/%Y %H:%M WIB')}</i>"
            )
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_pending':
            pendings = Transaction.query.filter_by(status='PENDING').order_by(Transaction.id.desc()).limit(5).all()
            if not pendings:
                text = "✅ <b>TIDAK ADA TRANSAKSI PENDING</b>\n\nSemua transaksi telah selesai diproses."
            else:
                lines = ["⏳ <b>DAFTAR TRANSAKSI PENDING TERKINI:</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
                for p in pendings:
                    t_time = format_wib(p.created_at, '%H:%M') if p.created_at else '-'
                    lines.append(
                        f"• <code>{p.ref_id}</code> | Rp {p.amount:,.0f}\n"
                        f"  Produk: {p.product_name or '-'}\n"
                        f"  Tujuan: <code>{p.target_number or '-'}</code> | {t_time} WIB"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                lines.append("💡 <i>Kelola status lengkap di panel web /admin/transactions</i>")
                text = "\n".join(lines)
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_tickets':
            tickets = SupportTicket.query.filter(SupportTicket.status.in_(['OPEN', 'PROCESS'])).order_by(SupportTicket.id.desc()).limit(5).all()
            if not tickets:
                text = "✅ <b>TIDAK ADA TIKET KELUHAN TERBUKA</b>\n\nSemua tiket bantuan telah diselesaikan."
            else:
                lines = ["🎫 <b>TIKET CS BELUM SELESAI:</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
                for t in tickets:
                    lines.append(
                        f"• <b>#{t.ticket_number}</b> [{t.status}]\n"
                        f"  👤 {t.user_name} (<code>{t.user_phone}</code>)\n"
                        f"  📂 {t.category}\n"
                        f"  💬 <i>\"{t.message[:60]}...\"</i>\n"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                text = "\n".join(lines)
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_scan_low_bal':
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang memindai seluruh user dengan saldo < Rp 100.000 dan mengirim notifikasi WhatsApp...</i>", None)
            from app.services.balance_notification_service import scan_and_notify_all_low_balance_users
            res = scan_and_notify_all_low_balance_users(force_all=False)

            lines = [
                "⚠️ <b>HASIL PEMERIKSAAN SISA SALDO MINIM</b>",
                "━━━━━━━━━━━━━━━━━━━━━━",
                f"👥 <b>Total Toko Saldo Minim:</b> {res['total_low']} toko/user",
                f"📲 <b>Notifikasi WA Terkirim ke User:</b> {res['notified_users']} pesan",
                f"🌟 <b>Notifikasi WA Terkirim ke Upline:</b> {res['notified_uplines']} pesan",
                f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}",
                "━━━━━━━━━━━━━━━━━━━━━━"
            ]
            if res['details']:
                lines.append("📋 <b>Daftar Toko yang Dinotifikasi:</b>")
                for d in res['details'][:8]:
                    lines.append(f"• <b>{d['name']}</b>: Rp {d['balance']:,.0f} (<code>{d['phone']}</code>)")
                if len(res['details']) > 8:
                    lines.append(f"<i>...dan {len(res['details']) - 8} toko lainnya.</i>")
            else:
                if res['total_low'] > 0:
                    lines.append("ℹ️ <i>Semua toko tersebut sudah dinotifikasi sebelumnya (< 12 jam cooldown). Untuk mengirim ulang sekarang, klik tombol di bawah:</i>")
                else:
                    lines.append("🎉 <i>Alhamdulillah, seluruh saldo akun toko saat ini aman di atas Rp 100.000!</i>")

            markup = {
                "inline_keyboard": [
                    [{"text": "⚡ Paksa Kirim Ulang Sekarang", "callback_data": "cmd_scan_low_bal_force"}],
                    [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
                ]
            }
            _edit_message(token, chat_id, message_id, "\n".join(lines), markup)

        elif data == 'cmd_scan_low_bal_force':
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang memaksa pengiriman notifikasi WhatsApp saldo minim ke seluruh toko...</i>", None)
            from app.services.balance_notification_service import scan_and_notify_all_low_balance_users
            res = scan_and_notify_all_low_balance_users(force_all=True)
            text = (
                "⚡ <b>NOTIFIKASI SALDO MINIM DIPAKSA TERKIRIM!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Total Toko Saldo Minim:</b> {res['total_low']} toko\n"
                f"📲 <b>WA Terkirim ke User:</b> {res['notified_users']} pesan\n"
                f"🌟 <b>WA Terkirim ke Upline:</b> {res['notified_uplines']} pesan\n"
                f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}\n"
                "━━━━━━━━━━━━━━━━━━━━━━"
            )
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_sync_digi':
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang menarik data produk dari Digiflazz... Harap tunggu sebentar.</i>", None)
            ok, msg = sync_products()
            res_icon = "✅" if ok else "🚨"
            text = f"{res_icon} <b>HASIL SINKRONISASI DIGIFLAZZ:</b>\n\n{msg}"
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_sync_vip':
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang menarik layanan game dari VIP-Reseller... Harap tunggu sebentar.</i>", None)
            vip = VIPReseller()
            res = vip.get_services()
            if res and res.get('result'):
                count = len(res.get('data', []))
                text = f"✅ <b>SINKRONISASI VIP-RESELLER BERHASIL!</b>\n\nBerhasil memvalidasi {count} produk/layanan game dari API VIP-Reseller."
            else:
                text = "🚨 <b>GAGAL SINKRONISASI VIP-RESELLER:</b>\nKoneksi atau kredensial API VIP-Reseller salah."
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_backup':
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang membuat paket backup portabel GarudaTel...</i>", None)
            try:
                from app.core.backup.backup_engine import BackupEngine
                engine = BackupEngine()
                backup_path, display_name = engine.create_full_portable_backup()
                f_size = os.path.getsize(backup_path) / (1024 * 1024)
                caption = (
                    f"💾 <b>BACKUP PORTABEL INSTAN BERHASIL</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📁 <b>File:</b> <code>{display_name}</code>\n"
                    f"📦 <b>Ukuran:</b> {f_size:.2f} MB\n"
                    f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}\n\n"
                    f"File cadangan dilampirkan langsung di bawah ini:"
                )
                doc_url = f"https://api.telegram.org/bot{token}/sendDocument"
                with open(backup_path, 'rb') as f:
                    requests.post(doc_url, files={'document': (display_name, f, 'application/zip')}, data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}, timeout=90)
                
                # Kirim juga salinan laporan ke Bot 2 Notifikasi (dengan tombol restore)
                send_backup_notification(backup_path, status="SUKSES", details="Trigger instan via Bot 3 Admin Telegram", display_filename=display_name)
                _edit_message(token, chat_id, message_id, "✅ Backup portabel berhasil dan file telah dikirimkan ke Bot 3 dan Bot 2!", get_back_button())
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"🚨 Gagal membuat backup: {str(e)}", get_back_button())

        elif data == 'cmd_system':
            import platform
            base_dir = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
            db_file = os.path.join(base_dir, 'app', 'garudatel.db')
            db_size_mb = (os.path.getsize(db_file) / (1024*1024)) if os.path.exists(db_file) else 0

            text = (
                "🩺 <b>STATUS SISTEM & SERVER VPS</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🖥️ <b>OS Platform:</b> {platform.system()} {platform.release()}\n"
                f"🐍 <b>Python:</b> {platform.python_version()}\n"
                f"📦 <b>Ukuran Database:</b> {db_size_mb:.2f} MB\n"
                f"🏷️ <b>Total Produk Aktif:</b> {Product.query.filter_by(is_active=True).count():,} item\n"
                f"👥 <b>Total Pengguna:</b> {User.query.count():,} member\n"
                f"📋 <b>Total Transaksi:</b> {Transaction.query.count():,} data\n"
                f"⏰ <b>Waktu Server:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "🟢 <i>Status: Berjalan Normal (Healthy)</i>"
            )
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_otp_info':
            text = (
                "🆘 <b>BANTUAN OTP DARURAT (MANUAL)</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Untuk membuat kode OTP darurat secara instan untuk pengguna yang tidak menerima WhatsApp:\n\n"
                "Ketikkan perintah berikut di chat ini:\n"
                "👉 <code>/otp &lt;nomor_whatsapp&gt;</code>\n\n"
                "Contoh:\n"
                "<code>/otp 081234567890</code>\n"
                "atau\n"
                "<code>/otp 6281234567890</code>\n\n"
                "Kode 6 digit akan langsung diciptakan dan berlaku selama 15 menit."
            )
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_wa_status':
            try:
                res = requests.get('http://127.0.0.1:3000/api/status', timeout=5)
                wa_data = res.json()
                is_conn = wa_data.get('connected', False)
                state = wa_data.get('state', 'unknown')
                u_info = wa_data.get('user', {}) or {}
                wa_phone = u_info.get('id', '').split(':')[0] if u_info else '-'
                if is_conn:
                    st_badge = "🟢 <b>TERHUBUNG (CONNECTED)</b>"
                    detail = f"• <b>Nomor Bot:</b> <code>{wa_phone}</code>\n• <b>Status:</b> Siap Kirim OTP & Notifikasi"
                    markup = {
                        "inline_keyboard": [
                            [{"text": "📱 Tautkan Nomor Baru", "callback_data": "cmd_pair_new"}],
                            [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
                        ]
                    }
                else:
                    st_badge = "🔴 <b>TERPUTUS / BELUM TERTAUT</b>"
                    detail = f"• <b>Status Soket:</b> <code>{state}</code>\n• Klik tombol di bawah untuk menautkan nomor WhatsApp bot Anda."
                    markup = {
                        "inline_keyboard": [
                            [{"text": "📱 TAUTKAN NOMOR BARU", "callback_data": "cmd_pair_new"}],
                            [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
                        ]
                    }
                text = (
                    f"📱 <b>STATUS BOT WHATSAPP (BAILEYS)</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Status: {st_badge}\n"
                    f"{detail}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━"
                )
            except Exception as e:
                text = f"🚨 <b>Gagal menghubungi mesin Baileys di port 3000:</b>\n<code>{str(e)}</code>"
                markup = get_back_button()
            _edit_message(token, chat_id, message_id, text, markup)

        elif data == 'cmd_pair_new':
            text = (
                "📲 <b>TAUTKAN NOMOR WHATSAPP BARU</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Silakan ketik dan kirimkan nomor WhatsApp bot ke chat ini:\n\n"
                "👉 Awali dengan <code>62</code>, contoh: <code>6281234567890</code>\n\n"
                "Mesin Baileys akan menstabilkan socket dan memberikan 8 digit kode pairing."
            )
            _edit_message(token, chat_id, message_id, text, get_back_button())


def handle_admin_message(app, message):
    """
    Memproses perintah teks dari Admin di Bot 3 (seperti /start, /menu, /otp <nomor>, nomor WA pairing).
    """
    token, allowed_chat = get_bot_admin_credentials()
    if not token:
        return

    chat_id = str(message.get('chat', {}).get('id', ''))
    text = message.get('text', '').strip()

    # Validasi otorisasi chat_id admin
    if allowed_chat and chat_id != str(allowed_chat):
        _send_message(token, chat_id, "⛔ <b>Akses Ditolak!</b>\nAkun Telegram Anda tidak terdaftar sebagai Admin GarudaTel.")
        return

    # Tangkap balasan nomor telepon untuk pairing WhatsApp (awalan 62 dan panjang 10-16 digit)
    clean_digits = ''.join(c for c in text if c.isdigit())
    if clean_digits.startswith('62') and 10 <= len(clean_digits) <= 16 and not text.startswith('/'):
        _send_message(token, chat_id, f"⏳ <i>Sedang memproses Pairing Code untuk nomor <code>{clean_digits}</code>... Harap tunggu 3 detik untuk menstabilkan soket WhatsApp...</i>")
        try:
            res = requests.post('http://127.0.0.1:3000/api/pair', json={'number': clean_digits}, timeout=35)
            res_data = res.json()
            if res_data.get('status') == 'success':
                p_code = res_data.get('code')
                reply = (
                    f"🔗 <b>KODE PAIRING WHATSAPP:</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔑 <code>{p_code}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📌 <b>Langkah Tautkan di HP:</b>\n"
                    f"1. Buka WhatsApp di HP Anda\n"
                    f"2. Buka menu titik tiga ➜ <b>Perangkat Tertaut</b>\n"
                    f"3. Pilih <b>Tautkan Perangkat</b> ➜ <b>Tautkan dengan nomor telepon saja</b>\n"
                    f"4. Masukkan kode 8 digit di atas."
                )
                _send_message(token, chat_id, reply)
            else:
                _send_message(token, chat_id, f"🚨 <b>Gagal meminta kode pairing:</b> {res_data.get('message', 'Terjadi kendala soket')}")
        except Exception as e:
            _send_message(token, chat_id, f"🚨 <b>Gagal menghubungi mesin WhatsApp (port 3000):</b> {str(e)}")
        return

    # Perintah /otp <nomor> (Fitur Bantuan OTP Darurat)
    if text.startswith('/otp'):
        parts = text.split()
        if len(parts) < 2:
            _send_message(token, chat_id, "⚠️ <b>Format salah!</b>\nGunakan: <code>/otp &lt;nomor_hp&gt;</code>\nContoh: <code>/otp 081234567890</code>")
            return

        target_no = parts[1]
        with app.app_context():
            from app.services.otp_service import create_otp
            otp_res = create_otp(target_no, action='manual', expiry_seconds=15*60)
            reply = (
                f"✅ <b>OTP DARURAT BERHASIL DICIPTAKAN!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📱 <b>Nomor HP:</b> <code>{target_no}</code>\n"
                f"🔑 <b>Kode OTP:</b> <code>{otp_res}</code>\n"
                f"⏳ <b>Masa Berlaku:</b> 15 Menit\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Berikan kode di atas kepada pengguna untuk dimasukkan pada kolom verifikasi."
            )
            _send_message(token, chat_id, reply)
    # Perintah /topup <id_user> <nominal>
    if text.startswith('/topup'):
        parts = text.split()
        if len(parts) < 3:
            _send_message(token, chat_id, "⚠️ <b>Format salah!</b>\nGunakan: <code>/topup &lt;id_user&gt; &lt;nominal&gt;</code>\nContoh: <code>/topup 5 250000</code>")
            return
        try:
            u_id = int(parts[1])
            amt = float(parts[2])
        except ValueError:
            _send_message(token, chat_id, "⚠️ ID User dan nominal harus berupa angka!")
            return

        with app.app_context():
            from app.models.user import User
            from app.services.balance_service import adjust_user_balance_manual
            target_user = User.query.get(u_id)
            if not target_user:
                _send_message(token, chat_id, f"❌ Toko/User ID #{u_id} tidak ditemukan!")
                return
            ok, new_bal, msg, trx = adjust_user_balance_manual(
                user_id=u_id,
                amount=amt,
                action='add',
                note='Topup Chat Command via Bot Telegram Admin',
                admin_source='Bot Telegram Admin'
            )
            if ok:
                reply = (
                    "✅ <b>TOPUP SALDO TOKO BERHASIL!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏢 <b>Toko:</b> {target_user.name} (User #{u_id})\n"
                    f"➕ <b>Nominal:</b> <code>+Rp {amt:,.0f}</code>\n"
                    f"💰 <b>Saldo Baru:</b> <code>Rp {new_bal:,.0f}</code>\n"
                    f"🔖 <b>Ref ID:</b> <code>{trx.ref_id if trx else '-'}</code>\n"
                    f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}"
                )
            else:
                reply = f"🚨 <b>GAGAL MENAMBAH SALDO:</b>\n{msg}"
            _send_message(token, chat_id, reply)
        return

    # Perintah /potong <id_user> <nominal>
    if text.startswith('/potong'):
        parts = text.split()
        if len(parts) < 3:
            _send_message(token, chat_id, "⚠️ <b>Format salah!</b>\nGunakan: <code>/potong &lt;id_user&gt; &lt;nominal&gt;</code>\nContoh: <code>/potong 5 50000</code>")
            return
        try:
            u_id = int(parts[1])
            amt = float(parts[2])
        except ValueError:
            _send_message(token, chat_id, "⚠️ ID User dan nominal harus berupa angka!")
            return

        with app.app_context():
            from app.models.user import User
            from app.services.balance_service import adjust_user_balance_manual
            target_user = User.query.get(u_id)
            if not target_user:
                _send_message(token, chat_id, f"❌ Toko/User ID #{u_id} tidak ditemukan!")
                return
            ok, new_bal, msg, trx = adjust_user_balance_manual(
                user_id=u_id,
                amount=amt,
                action='deduct',
                note='Potong Saldo Chat Command via Bot Telegram Admin',
                admin_source='Bot Telegram Admin'
            )
            if ok:
                reply = (
                    "✅ <b>PENGURANGAN SALDO BERHASIL!</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏢 <b>Toko:</b> {target_user.name} (User #{u_id})\n"
                    f"➖ <b>Nominal:</b> <code>-Rp {amt:,.0f}</code>\n"
                    f"💰 <b>Saldo Baru:</b> <code>Rp {new_bal:,.0f}</code>\n"
                    f"🔖 <b>Ref ID:</b> <code>{trx.ref_id if trx else '-'}</code>\n"
                    f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}"
                )
            else:
                reply = f"🚨 <b>GAGAL MENGURANGI SALDO:</b>\n{msg}"
            _send_message(token, chat_id, reply)
        return

    # Perintah /toko atau /cektoko
    if text.startswith('/toko') or text.startswith('/cektoko'):
        parts = text.split()
        with app.app_context():
            from app.models.user import User
            from app.models.transaction import Transaction
            if len(parts) < 2:
                rendered = render_stores_keyboard(page=1, per_page=8)
                text_msg = (
                    f"🏪 <b>DAFTAR TOKO / MEMBER (Hal 1/{rendered['total_pages']})</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"Ditemukan <b>{rendered['total_stores']}</b> toko/member terdaftar.\n"
                    "Silakan klik salah satu toko di bawah untuk melihat performa:"
                )
                _send_message(token, chat_id, text_msg, reply_markup=rendered['keyboard'])
                return

            try:
                u_id = int(parts[1])
            except ValueError:
                _send_message(token, chat_id, "⚠️ ID Toko harus berupa angka!")
                return

            target_user = User.query.get(u_id)
            if not target_user:
                _send_message(token, chat_id, f"❌ Toko ID #{u_id} tidak ditemukan!")
                return

            wib_now = get_wib_now()
            today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
            today_start = today_start_wib.astimezone(timezone.utc).replace(tzinfo=None)

            from app.extensions import db
            today_total = Transaction.query.filter(Transaction.user_id == target_user.id, Transaction.created_at >= today_start).count()
            today_success = Transaction.query.filter(Transaction.user_id == target_user.id, Transaction.created_at >= today_start, Transaction.status == 'SUCCESS').count()
            today_failed = Transaction.query.filter(
                Transaction.user_id == target_user.id,
                Transaction.created_at >= today_start,
                Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL'])
            ).count()
            today_revenue = db.session.query(db.func.sum(Transaction.amount)).filter(
                Transaction.user_id == target_user.id,
                Transaction.created_at >= today_start,
                Transaction.status == 'SUCCESS',
                ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT'])
            ).scalar() or 0.0

            text_msg = (
                f"🏪 <b>PROFIL & ANALISA TOKO</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏢 <b>Nama Toko:</b> {target_user.name}\n"
                f"🆔 <b>ID Pengguna:</b> <code>#{target_user.id}</code>\n"
                f"📱 <b>WhatsApp:</b> <code>{target_user.phone}</code>\n"
                f"👑 <b>Golongan:</b> {target_user.role.upper()}\n"
                f"💰 <b>Saldo Saat Ini:</b> <code>Rp {target_user.balance:,.0f}</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📅 <b>PERFORMA TRANSAKSI HARI INI:</b>\n"
                f"• <b>Omset Penjualan:</b> <code>Rp {today_revenue:,.0f}</code>\n"
                f"• <b>Total Transaksi:</b> {today_total} transaksi\n"
                f"• <b>Status:</b> ✅ {today_success} Sukses  |  ❌ {today_failed} Gagal\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Silakan pilih aksi di bawah ini:"
            )

            store_keyboard = {
                "inline_keyboard": [
                    [
                        {"text": "❌ Cek Trx Gagal", "callback_data": f"store_failed_{target_user.id}"},
                        {"text": "📋 5 Trx Terakhir", "callback_data": f"store_recent_{target_user.id}"}
                    ],
                    [
                        {"text": "➕ Tambah Saldo", "callback_data": f"store_topup_{target_user.id}"},
                        {"text": "➖ Kurangi Saldo", "callback_data": f"store_deduct_{target_user.id}"}
                    ],
                    [
                        {"text": "« Daftar Toko", "callback_data": "cmd_list_stores"},
                        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
                    ]
                ]
            }
            _send_message(token, chat_id, text_msg, reply_markup=store_keyboard)
        return

    # Perintah /ceksaldo atau /ceksaldominim
    if text.startswith('/ceksaldo') or text.startswith('/ceksaldominim'):
        force_flag = 'force' in text.lower()
        _send_message(token, chat_id, "⏳ <i>Sedang memindai seluruh saldo akun toko dan mengirim notifikasi WhatsApp...</i>")
        with app.app_context():
            from app.services.balance_notification_service import scan_and_notify_all_low_balance_users
            res = scan_and_notify_all_low_balance_users(force_all=force_flag)
            reply = (
                "⚠️ <b>HASIL PEMERIKSAAN SISA SALDO MINIM</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 <b>Total Toko Saldo Minim:</b> {res['total_low']} toko\n"
                f"📲 <b>WA Terkirim ke User:</b> {res['notified_users']} pesan\n"
                f"🌟 <b>WA Terkirim ke Upline:</b> {res['notified_uplines']} pesan\n"
                f"⏰ <b>Waktu:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
            )
            if res['notified_users'] == 0 and res['total_low'] > 0 and not force_flag:
                reply += "ℹ️ <i>Seluruh toko telah dinotifikasi sebelumnya (< 12 jam). Ketik: <code>/ceksaldominim force</code> untuk memaksa kirim ulang sekarang.</i>"
            elif res['total_low'] == 0:
                reply += "🎉 <i>Alhamdulillah, seluruh saldo akun toko saat ini aman di atas Rp 100.000!</i>"
            else:
                reply += "✅ <i>Pemberitahuan ramah berhasil dikirimkan via WhatsApp ke toko dan pembina kemitraan.</i>"
            _send_message(token, chat_id, reply)
        return

    # Perintah /sync atau /syncdigi
    if text.startswith('/sync') or text.startswith('/syncdigi'):
        force_flag = 'force' in text.lower()
        _send_message(token, chat_id, "⏳ <i>Sedang melakukan sinkronisasi katalog produk dari Digiflazz...</i>")
        with app.app_context():
            from app.services.digiflazz import sync_products
            ok, msg = sync_products(force=force_flag, notify_admin_bot=False)
            icon = "✅" if ok else "🚨"
            _send_message(token, chat_id, f"{icon} <b>HASIL SINKRONISASI DIGIFLAZZ:</b>\n\n{msg}")
        return

    # Perintah Menu Utama (/start, /menu, /help)
    welcome_text = (
        "🦅 <b>PANEL KONTROL ADMIN GARUDATEL v2</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Selamat datang di Bot Panel Admin Telegram.\n"
        "Gunakan tombol interaktif di bawah ini untuk mengakses fitur secara cepat:"
    )
    _send_message(token, chat_id, welcome_text, reply_markup=get_admin_inline_keyboard())


def _answer_callback(token, callback_query_id, text=""):
    try:
        requests.post(f"https://api.telegram.org/bot{token}/answerCallbackQuery", json={
            "callback_query_id": callback_query_id,
            "text": text
        }, timeout=5)
    except Exception:
        pass


def _edit_message(token, chat_id, message_id, text, reply_markup=None):
    try:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"https://api.telegram.org/bot{token}/editMessageText", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"[Bot 3] Gagal edit pesan: {e}")


def _send_message(token, chat_id, text, reply_markup=None):
    try:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"[Bot 3] Gagal kirim pesan: {e}")
