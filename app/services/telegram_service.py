import os
import requests
import logging

logger = logging.getLogger(__name__)

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
        lines.append(f"👉 <a href=\"https://wa.me/{wa_num}?text=Halo%20{ticket.user_name},%20terkait%20tiket%20bantuan%20{ticket.ticket_number}%20di%20GarudaTel:\">Klik untuk Balas via WhatsApp Pelapor</a>")

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
    from datetime import datetime

    token, chat_id = get_bot_cs_credentials()

    # Bersihkan dan format nomor WhatsApp (awalan 62)
    clean_num = ''.join(filter(str.isdigit, str(phone or '')))
    if clean_num.startswith('0'):
        clean_num = '62' + clean_num[1:]

    display_name = user_name or 'Pengguna / Calon Member'
    wib_now = datetime.utcnow().strftime('%d/%m/%Y %H:%M WIB')

    # Susun Teks Pesan WhatsApp jika kode OTP tersedia
    wa_direct_link = ""
    if otp_code:
        wa_message = (
            f"Halo kak {display_name}!\n\n"
            f"Berikut adalah *Kode OTP Darurat* Anda untuk akun GarudaTel:\n\n"
            f"👉 *{otp_code}*\n\n"
            f"⚠️ *PENTING:* Kode OTP ini bersifat rahasia dan *HANYA BERLAKU {expiry_minutes} MENIT* "
            f"khusus untuk nomor ini ({clean_num}).\n\n"
            f"Silakan masukkan kode pada formulir verifikasi Anda di website GarudaTel. Terima kasih!"
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

    from datetime import datetime
    wib_now = datetime.utcnow().strftime('%d/%m/%Y %H:%M WIB')

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


def send_backup_notification(backup_file_path=None, status="SUKSES", details=""):
    """
    Mengirimkan laporan backup database ke Bot 2 (Notifikasi),
    dan jika file backup tersedia, mengunggah file .db/.gz langsung ke Telegram.
    """
    token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        return False, "Kredensial BOT_NOTIF belum diatur di .env"

    from datetime import datetime
    wib_now = datetime.utcnow().strftime('%d/%m/%Y %H:%M WIB')

    file_size_str = "-"
    if backup_file_path and os.path.exists(backup_file_path):
        size_bytes = os.path.getsize(backup_file_path)
        if size_bytes > 1024 * 1024:
            file_size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
        else:
            file_size_str = f"{size_bytes / 1024:.2f} KB"

    icon = "✅" if status == "SUKSES" else "🚨"
    caption = (
        f"{icon} <b>LAPORAN BACKUP DATABASE GARUDATEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Status:</b> {status}\n"
        f"⏰ <b>Waktu:</b> {wib_now}\n"
        f"📦 <b>Ukuran:</b> {file_size_str}\n"
        f"ℹ️ <b>Info:</b> {details or 'Backup non-blocking SQLite WAL berhasil'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    try:
        # Jika ada file dan ukuran < 45MB, kirim sebagai Dokumen Telegram (Offsite Cloud Backup)
        if backup_file_path and os.path.exists(backup_file_path):
            doc_url = f"https://api.telegram.org/bot{token}/sendDocument"
            with open(backup_file_path, 'rb') as f:
                files = {'document': f}
                data = {'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}
                res = requests.post(doc_url, files=files, data=data, timeout=60)
                return res.status_code == 200, res.text
        else:
            # Kirim pesan teks jika file tidak dilampirkan
            msg_url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': caption, 'parse_mode': 'HTML'}
            res = requests.post(msg_url, json=payload, timeout=10)
            return res.status_code == 200, res.text
    except Exception as e:
        logger.error(f"[Bot 2 Backup] Gagal kirim laporan backup: {e}")
        return False, str(e)


# ==============================================================================
# BOT 3 : PANEL & FITUR ADMIN TELEGRAM (INLINE BUTTON INTERAKTIF)
# ==============================================================================
def get_bot_admin_credentials():
    """Mengambil Token dan Chat ID untuk Bot 3 : Panel Admin."""
    token = clean_str(os.getenv('BOT_ADMIN_TOKEN'))
    chat_id = clean_str(os.getenv('BOT_ADMIN_CHAT_ID'))
    return token, chat_id


def get_admin_inline_keyboard():
    """Menghasilkan struktur tombol inline keyboard untuk menu utama Bot Admin."""
    return {
        "inline_keyboard": [
            [
                {"text": "💰 Saldo Digiflazz", "callback_data": "cmd_saldo"},
                {"text": "📊 Omset Hari Ini", "callback_data": "cmd_stats"}
            ],
            [
                {"text": "⏳ Trx Pending", "callback_data": "cmd_pending"},
                {"text": "🎫 Tiket CS Masuk", "callback_data": "cmd_tickets"}
            ],
            [
                {"text": "🔄 Sync Digiflazz", "callback_data": "cmd_sync_digi"},
                {"text": "🔄 Sync VIP Games", "callback_data": "cmd_sync_vip"}
            ],
            [
                {"text": "🆘 Buat OTP Darurat", "callback_data": "cmd_otp_info"},
                {"text": "💾 Backup DB Sekarang", "callback_data": "cmd_backup"}
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

        elif data == 'cmd_saldo':
            is_ok, bal, msg = check_balance()
            if is_ok:
                text = (
                    "💰 <b>INFORMASI SALDO DIGIFLAZZ</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Saldo Tersedia:</b> <code>Rp {bal:,.0f}</code>\n"
                    f"• <b>Status API:</b> Terhubung Normal (200 OK)\n"
                    f"• <b>Update:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S WIB')}"
                )
            else:
                text = f"🚨 <b>GAGAL CEK SALDO:</b>\n{msg}"
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_stats':
            today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
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
                f"⏰ <i>Waktu: {datetime.now().strftime('%d/%m/%Y %H:%M WIB')}</i>"
            )
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_pending':
            pendings = Transaction.query.filter_by(status='PENDING').order_by(Transaction.id.desc()).limit(5).all()
            if not pendings:
                text = "✅ <b>TIDAK ADA TRANSAKSI PENDING</b>\n\nSemua transaksi telah selesai diproses."
            else:
                lines = ["⏳ <b>DAFTAR TRANSAKSI PENDING TERKINI:</b>", "━━━━━━━━━━━━━━━━━━━━━━"]
                for p in pendings:
                    t_time = p.created_at.strftime('%H:%M') if p.created_at else '-'
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
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang membuat snapshot cadangan database SQLite...</i>", None)
            try:
                backup_path = perform_database_backup()
                f_size = os.path.getsize(backup_path) / 1024
                caption = (
                    f"💾 <b>BACKUP DATABASE INSTAN BERHASIL</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📁 <b>File:</b> <code>{os.path.basename(backup_path)}</code>\n"
                    f"📦 <b>Ukuran:</b> {f_size:.2f} KB\n"
                    f"⏰ <b>Waktu:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S WIB')}\n\n"
                    f"File cadangan dilampirkan langsung di bawah ini:"
                )
                doc_url = f"https://api.telegram.org/bot{token}/sendDocument"
                with open(backup_path, 'rb') as f:
                    requests.post(doc_url, files={'document': f}, data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'}, timeout=60)
                
                # Kirim juga salinan laporan ke Bot 2 Notifikasi
                send_backup_notification(backup_path, status="SUKSES", details="Manual trigger via Bot 3 Admin Telegram")
                _edit_message(token, chat_id, message_id, "✅ Backup database berhasil dan file telah dikirimkan ke chat ini!", get_back_button())
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
                f"⏰ <b>Waktu Server:</b> {datetime.now().strftime('%d/%m/%Y %H:%M:%S WIB')}\n"
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
