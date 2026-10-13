import os
import json
import socket
import urllib.parse
import requests
import logging
from datetime import datetime, timezone, timedelta
import urllib3.util.connection as urllib3_conn
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

logger = logging.getLogger(__name__)

# ==============================================================================
# RESOLUSI KONEKSI TELEGRAM API DI VPS LINUX (FORCE IPv4 & RESILIENT SESSION)
# ==============================================================================
# Masalah: Di VPS Linux (Ubuntu), getaddrinfo mendahulukan AAAA (IPv6). Jika upstream
# IPv6 ISP/datacenter tidak merespons (blackhole), urllib3 akan gantung hingga timeout
# 10s (ConnectTimeoutError). Memaksa socket.AF_INET menjamin koneksi langsung ke IPv4.
try:
    urllib3_conn.allowed_gai_family = lambda: socket.AF_INET
except Exception as _e_af:
    pass

def get_telegram_api_url():
    """Mengembalikan Base URL API Telegram (mendukung custom proxy / Cloudflare Worker)."""
    custom = (os.getenv('TELEGRAM_API_BASE_URL') or os.getenv('TELEGRAM_API_URL') or '').strip().rstrip('/')
    if custom:
        return custom
    return "https://api.telegram.org"

def get_telegram_session():
    """
    Membuat session requests yang tangguh khusus untuk Telegram API:
    - Memaksa IPv4
    - Retry otomatis untuk kendala koneksi sementara
    - Mendukung proxy opsional jika disetel di TELEGRAM_PROXY atau HTTPS_PROXY
    """
    session = requests.Session()
    proxy = (os.getenv('TELEGRAM_PROXY') or os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or '').strip()
    if proxy:
        session.proxies = {
            'http': proxy,
            'https': proxy
        }
    retries = Retry(total=2, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session

def call_telegram_api(method, endpoint, **kwargs):
    """
    Helper terpadu untuk memanggil endpoint Telegram Bot API:
    - Menggunakan URL basis dinamis (get_telegram_api_url)
    - Memaksa IPv4 globally via urllib3.util.connection.allowed_gai_family
    - Mendukung proxy opsional jika disetel di TELEGRAM_PROXY atau HTTPS_PROXY
    - Kompatibel dengan unit test mocking requests.post / requests.get
    """
    base_url = get_telegram_api_url()
    clean_endpoint = endpoint.lstrip('/')
    url = f"{base_url}/{clean_endpoint}"
    
    # Timeout adaptif: connect 15s, read 35s jika tidak ditentukan
    if 'timeout' not in kwargs:
        kwargs['timeout'] = (15, 35)

    proxy = (os.getenv('TELEGRAM_PROXY') or os.getenv('HTTPS_PROXY') or os.getenv('HTTP_PROXY') or '').strip()
    if not proxy:
        fn = getattr(requests, method.lower())
        return fn(url, **kwargs)
        
    session = get_telegram_session()
    return session.request(method, url, **kwargs)

def is_admin_chat_authorized(chat_id, allowed_chat=None):
    """
    Memeriksa apakah chat_id berasal dari Admin terdaftar.
    Mendukung format multiple chat ID (dipisahkan koma), menghilangkan spasi,
    dan fallback ke BOT_ADMIN_CHAT_ID serta BOT_NOTIF_CHAT_ID.
    """
    chat_str = str(chat_id).strip()
    if not chat_str:
        return False
    
    admin_tokens, admin_c = get_bot_admin_credentials()
    notif_tokens, notif_c = get_bot_notif_credentials()
    
    targets = []
    if allowed_chat:
        targets.extend(str(allowed_chat).replace(';', ',').split(','))
    if admin_c:
        targets.extend(str(admin_c).replace(';', ',').split(','))
    if notif_c:
        targets.extend(str(notif_c).replace(';', ',').split(','))
        
    valid_ids = {t.strip() for t in targets if t and t.strip()}
    if not valid_ids:
        return True
    return chat_str in valid_ids

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
    Mengirimkan laporan tiket bantuan CS ke Bot 1 : CS & Balas Inbox di Telegram
    dengan rincian produk, transaksi, dan tombol aksi balas cepat.
    
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

    try:
        from app.services.setting_service import get_store_name
        s_name = get_store_name() or "GarudaTel"
    except Exception:
        s_name = "GarudaTel"

    # Susun Pesan HTML Telegram yang Lengkap & Informatif
    ticket_time = getattr(ticket, 'created_at_wib', None) or format_wib(fmt='%d %b %Y, %H:%M WIB')
    lines = [
        f"🎫 <b>TIKET BANTUAN CS BARU #{ticket.ticket_number}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"👤 <b>Pelapor:</b> {ticket.user_name}",
        f"📱 <b>No. HP/WA:</b> <code>{ticket.user_phone}</code>",
        f"📂 <b>Kategori:</b> {ticket.category}",
        f"⏰ <b>Waktu Masuk:</b> {ticket_time}",
        ""
    ]

    kb_rows = [
        [
            {"text": "✍️ Balas Manual", "callback_data": f"reply_prompt:{ticket.ticket_number}"},
            {"text": "⏳ Sedang Dicek", "callback_data": f"reply_tpl:{ticket.ticket_number}:process"}
        ],
        [
            {"text": "✅ Selesaikan Tiket", "callback_data": f"reply_tpl:{ticket.ticket_number}:resolved"}
        ]
    ]

    if transaction:
        prod_cat = "-"
        prod_brand = "-"
        prod_obj = None
        try:
            if hasattr(transaction, 'product') and transaction.product:
                prod_obj = transaction.product
                prod_cat = transaction.product.category or "-"
                prod_brand = transaction.product.brand or "-"
            else:
                from app.models.product import Product
                p = Product.query.filter_by(sku_code=transaction.sku_code).first()
                if p:
                    prod_obj = p
                    prod_cat = p.category or "-"
                    prod_brand = p.brand or "-"
        except Exception:
            pass

        # Pastikan metadata seller terisi dari Product jika belum ada di Transaction
        try:
            from app.services.digiflazz import apply_digiflazz_seller_metadata, build_seller_complaint_info
            apply_digiflazz_seller_metadata(transaction, product=prod_obj)
        except Exception:
            pass

        st = (transaction.status or "UNKNOWN").upper()
        st_icon = "⏳" if st in ["PENDING", "PROCESSING"] else ("✅" if st == "SUCCESS" else "🚨")
        trx_time = format_wib(transaction.created_at, "%d/%m/%Y %H:%M:%S WIB") if transaction.created_at else "-"

        # Deteksi mode komplain otomatis dari isi keluhan member atau status transaksi
        msg_low = (ticket.message or "").lower()
        cat_low = (ticket.category or "").lower()
        if st == "SUCCESS" or "belum masuk" in msg_low or "blm masuk" in msg_low or "tidak masuk" in msg_low or "belum masuk" in cat_low:
            complaint_mode = "sukses_belum_masuk"
        elif st in ["FAILED", "GAGAL", "ERROR"]:
            complaint_mode = "gagal"
        else:
            complaint_mode = "pending"

        seller_info = {}
        try:
            from app.services.digiflazz import build_seller_complaint_info
            seller_info = build_seller_complaint_info(transaction, mode=complaint_mode)
        except Exception:
            seller_info = {}

        seller_display = seller_info.get("seller_name") or getattr(transaction, "resolved_seller_name", None) or "-"
        seller_tele_disp = seller_info.get("seller_tele") or "-"
        seller_wa_disp = seller_info.get("seller_wa") or "-"
        complaint_fmt = seller_info.get("complaint_text") or (
            transaction.format_digiflazz_complaint(mode=complaint_mode)
            if hasattr(transaction, "format_digiflazz_complaint") else ""
        )

        lines.append("📦 <b>DETAIL PRODUK & TRANSAKSI KOMPLAIN:</b>")
        lines.append(f"• <b>Ref ID:</b> <code>{transaction.ref_id}</code>")
        lines.append(f"• <b>Nama Produk:</b> <b>{transaction.product_name or '-'}</b>")
        if transaction.sku_code:
            lines.append(f"• <b>SKU / Kode:</b> <code>{transaction.sku_code}</code>")
        if prod_cat != "-":
            lines.append(f"• <b>Kategori/Brand:</b> {prod_cat} {f'({prod_brand})' if prod_brand != '-' else ''}")
        lines.append(f"• <b>Seller Digiflazz:</b> 🏪 <b>{seller_display}</b>")
        if seller_tele_disp != "-" or seller_wa_disp != "-":
            lines.append(f"• <b>Kontak Seller:</b> ✈️ <code>{seller_tele_disp}</code> | 📱 <code>{seller_wa_disp}</code>")
        lines.append(f"• <b>Tujuan / No. Meter:</b> <code>{transaction.target_number or '-'}</code>")
        lines.append(f"• <b>Status Trx:</b> {st_icon} <b>{st}</b>")
        lines.append(f"• <b>Nominal / Harga:</b> Rp {float(transaction.amount or 0.0):,.0f}")
        if getattr(transaction, 'base_price', 0) and float(transaction.base_price or 0) > 0:
            lines.append(f"• <b>Harga Modal Seller:</b> Rp {float(transaction.base_price):,.0f}")
        if transaction.sn:
            lines.append(f"• <b>SN / Ket. Biller:</b> <code>{transaction.sn}</code>")
        else:
            lines.append("• <b>SN / Ket. Biller:</b> <i>(Belum ada SN dari provider)</i>")
        lines.append(f"• <b>Waktu Transaksi:</b> {trx_time}")
        lines.append("")

        if complaint_fmt and (transaction.sku_code or "") not in ["DEPOSIT_SALDO", "DEPOSIT_MANUAL"]:
            lines.append("📣 <b>FORMAT KOMPLAIN STANDAR DIGIFLAZZ KE SELLER (KLIK UNTUK COPY):</b>")
            lines.append(f"<code>{complaint_fmt}</code>")
            lines.append("")

            # Susun tombol 1-Klik Teruskan Komplain ke Seller
            seller_direct_row = []
            if seller_info.get("tele_url"):
                seller_direct_row.append({
                    "text": f"✈️ Tele Seller ({seller_info.get('seller_tele')})",
                    "url": seller_info["tele_url"]
                })
            if seller_info.get("wa_url"):
                seller_direct_row.append({
                    "text": "💬 WA Seller Manual",
                    "url": seller_info["wa_url"]
                })
            if seller_direct_row:
                kb_rows.append(seller_direct_row)

            kb_rows.append([
                {"text": "📲 Auto-Kirim WA ke Seller (Baileys)", "callback_data": f"fwd_seller_wa:{ticket.ticket_number}"}
            ])
            kb_rows.append([
                {"text": "🔄 Tarik Kontak Seller & Komplain", "callback_data": f"fwd_seller_sync:{ticket.ticket_number}"}
            ])
    else:
        lines.append("ℹ️ <i>Tiket Pertanyaan Umum (Tidak Terikat Transaksi Tertentu)</i>")
        lines.append("")

    lines.append("💬 <b>DETAIL KELUHAN PENGGUNA:</b>")
    lines.append(f"<i>\"{ticket.message}\"</i>")
    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    lines.append("💡 <b>CARA BALAS KE WEB PELAPOR / KOMPLAIN SELLER:</b>")
    lines.append("1. Klik <b>[📲 Auto-Kirim WA ke Seller]</b> atau <b>[✈️ Tele Seller]</b> untuk meneruskan komplain ke Seller Digiflazz.")
    lines.append("2. Cukup <b>Reply (Balas) pesan ini</b> di Telegram untuk membalas ke halaman web member.")
    lines.append(f"3. Atau ketik perintah: <code>/balas {ticket.ticket_number} [pesan]</code>")

    reply_markup = {
        "inline_keyboard": kb_rows
    }

    full_text = "\n".join(lines)

    try:
        payload = {
            "chat_id": chat_id,
            "text": full_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=12)
        res_data = resp.json()

        if res_data.get('ok'):
            ticket.telegram_sent = True
            ticket.telegram_response = f"Pesan terkirim ke Bot CS (Telegram ID {chat_id})"
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


def handle_cs_bot_update(app, update, bot_token=None):
    """
    Menangani pesan dan callback query yang masuk ke Bot 1 : CS & Balas Inbox di Telegram.
    Meneruskan balasan manual Admin langsung ke database tiket keluhan pengguna
    agar tampil di halaman web Pusat Bantuan & Tiket CS, serta fitur Smart Auto-Complaint ke Seller Digiflazz.
    """
    import re
    if not bot_token:
        bot_token, _ = get_bot_cs_credentials()
        if not bot_token:
            return

    with app.app_context():
        from app.extensions import db
        from app.models.support_ticket import SupportTicket
        from app.models.notification import Notification
        from app.models.transaction import Transaction

        # 1. TANGANI CALLBACK QUERY (KLIK TOMBOL INLINE TELEGRAM)
        if 'callback_query' in update:
            cb = update['callback_query']
            cb_id = cb.get('id')
            cb_data = cb.get('data', '')
            from_user = cb.get('from', {})
            first_n = from_user.get('first_name', '')
            last_n = from_user.get('last_name', '')
            admin_name = f"{first_n} {last_n}".strip() or from_user.get('username') or 'Admin CS'
            cb_msg = cb.get('message') or {}
            chat_id = cb_msg.get('chat', {}).get('id') if isinstance(cb_msg, dict) else from_user.get('id')
            orig_msg_id = cb_msg.get('message_id') if isinstance(cb_msg, dict) else None

            logger.info(f"[Bot 1 CS] Callback Query: data='{cb_data}' dari @{from_user.get('username')} ({admin_name})")

            def answer_cb(text, show_alert=False):
                try:
                    res = call_telegram_api(
                        'post',
                        f"bot{bot_token}/answerCallbackQuery",
                        json={"callback_query_id": cb_id, "text": text, "show_alert": show_alert},
                        timeout=8
                    )
                    if not res.json().get('ok'):
                        logger.warning(f"[Bot 1 CS] answerCallbackQuery warning: {res.text}")
                except Exception as ex:
                    logger.warning(f"[Bot 1 CS] answerCallbackQuery error: {ex}")

            def send_tg_msg(text, reply_to=None, reply_markup=None):
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True
                }
                if reply_to:
                    payload["reply_to_message_id"] = reply_to
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                try:
                    res = call_telegram_api(
                        'post',
                        f"bot{bot_token}/sendMessage",
                        json=payload,
                        timeout=10
                    )
                    if not res.json().get('ok'):
                        logger.error(f"[Bot 1 CS] Gagal sendMessage: {res.text}")
                except Exception as ex:
                    logger.error(f"[Bot 1 CS] sendMessage exception: {ex}")

            # A. Balas Manual Prompt
            if cb_data.startswith('reply_prompt:'):
                ticket_num = cb_data.split(':', 1)[1].replace('#', '').strip()
                answer_cb(f"Silakan ketik balasan untuk tiket #{ticket_num}")
                force_reply = {
                    "force_reply": True,
                    "input_field_placeholder": f"Ketik balasan untuk tiket #{ticket_num}..."
                }
                send_tg_msg(
                    f"✍️ <b>PANDUAN BALAS TIKET #{ticket_num}:</b>\n\n"
                    f"Silakan salin atau klik perintah berikut:\n"
                    f"<code>/balas {ticket_num} Tulis balasan Anda di sini</code>\n\n"
                    f"Atau cukup <b>Reply (Kutip) pesan ini</b> langsung dengan teks balasan Anda.\n\n"
                    f"📌 <i>Balasan Anda langsung muncul secara real-time di halaman Pusat Bantuan web pengguna!</i>",
                    reply_to=orig_msg_id,
                    reply_markup=force_reply
                )
                return

            # A2. Smart Auto-Complaint: Tarik Kontak Seller dari Digiflazz & Tampilkan Opsi Komplain Lengkap
            elif cb_data.startswith('fwd_seller_sync:'):
                ticket_num = cb_data.split(':', 1)[1].replace('#', '').strip()
                ticket = SupportTicket.query.filter_by(ticket_number=ticket_num).first()
                if not ticket:
                    answer_cb("Tiket tidak ditemukan!", show_alert=True)
                    return

                trx = getattr(ticket, 'transaction', None)
                if not trx and getattr(ticket, 'transaction_id', None):
                    trx = Transaction.query.get(ticket.transaction_id)
                if not trx and getattr(ticket, 'trx_ref_id', None):
                    trx = Transaction.query.filter_by(ref_id=ticket.trx_ref_id).first()
                if not trx:
                    answer_cb("Data transaksi terkait tiket ini tidak ditemukan!", show_alert=True)
                    return

                answer_cb("Menarik kontak Seller & status terbaru dari Digiflazz...")
                from app.services.digiflazz import check_transaction_status, apply_digiflazz_seller_metadata, build_seller_complaint_info
                bebas_sku_list = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']
                is_pasca_flow = (not trx.is_prepaid) or (trx.sku_code in bebas_sku_list)
                ok_chk, d_data, msg_chk = check_transaction_status(trx.sku_code, trx.target_number, trx.ref_id, is_pasca=is_pasca_flow)
                if ok_chk and isinstance(d_data, dict):
                    apply_digiflazz_seller_metadata(trx, d_data)
                    if d_data.get('sn'):
                        trx.sn = d_data.get('sn')
                    db.session.commit()
                else:
                    apply_digiflazz_seller_metadata(trx)
                    db.session.commit()

                msg_low = (ticket.message or "").lower()
                st_up = (trx.status or "").upper()
                if st_up == "SUCCESS" or "belum masuk" in msg_low or "blm masuk" in msg_low or "tidak masuk" in msg_low:
                    c_mode = "sukses_belum_masuk"
                elif st_up in ["FAILED", "GAGAL"]:
                    c_mode = "gagal"
                else:
                    c_mode = "pending"

                info = build_seller_complaint_info(trx, mode=c_mode)
                kb_sync = []
                row_links = []
                if info.get("tele_url"):
                    row_links.append({"text": f"✈️ Chat Tele Seller ({info['seller_tele']})", "url": info["tele_url"]})
                if info.get("wa_url"):
                    row_links.append({"text": "💬 Chat WA Seller Manual", "url": info["wa_url"]})
                if row_links:
                    kb_sync.append(row_links)
                if info.get("seller_wa_clean"):
                    kb_sync.append([{"text": "📲 Auto-Kirim WA ke Seller (Baileys)", "callback_data": f"fwd_seller_wa:{ticket.ticket_number}"}])

                sync_text = (
                    f"🏪 <b>DATA SELLER & FORMAT KOMPLAIN DIGIFLAZZ</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎫 <b>Tiket:</b> <code>#{ticket.ticket_number}</code>\n"
                    f"📋 <b>Ref ID:</b> <code>{trx.ref_id}</code>\n"
                    f"📦 <b>Produk:</b> {trx.product_name} (<code>{trx.sku_code}</code>)\n"
                    f"🏪 <b>Nama Seller:</b> <b>{info.get('seller_name') or '-'}</b>\n"
                    f"✈️ <b>Telegram Seller:</b> <code>{info.get('seller_tele') or 'Tidak dicantumkan seller'}</code>\n"
                    f"📱 <b>WhatsApp Seller:</b> <code>{info.get('seller_wa') or 'Tidak dicantumkan seller'}</code>\n"
                    f"📊 <b>Status Trx:</b> <b>{trx.status}</b> | SN: <code>{trx.sn or '-'}</code>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"📋 <b>1. Format Komplain (Sesuai Status Saat Ini):</b>\n"
                    f"<code>{info.get('complaint_text')}</code>\n\n"
                    f"⏳ <b>2. Format Komplain Pending:</b>\n"
                    f"<code>{info.get('complaint_pending')}</code>\n\n"
                    f"⚠️ <b>3. Format Sukses Tapi Belum Masuk:</b>\n"
                    f"<code>{info.get('complaint_sukses_belum_masuk')}</code>\n\n"
                    f"❌ <b>4. Format Komplain Gagal:</b>\n"
                    f"<code>{info.get('complaint_gagal')}</code>"
                )
                send_tg_msg(
                    sync_text,
                    reply_to=orig_msg_id,
                    reply_markup={"inline_keyboard": kb_sync} if kb_sync else None
                )
                return

            # A3. Smart Auto-Complaint: Auto-Kirim Pesan Komplain ke WA Seller via Baileys
            elif cb_data.startswith('fwd_seller_wa:'):
                ticket_num = cb_data.split(':', 1)[1].replace('#', '').strip()
                ticket = SupportTicket.query.filter_by(ticket_number=ticket_num).first()
                if not ticket:
                    answer_cb("Tiket tidak ditemukan!", show_alert=True)
                    return

                trx = getattr(ticket, 'transaction', None)
                if not trx and getattr(ticket, 'transaction_id', None):
                    trx = Transaction.query.get(ticket.transaction_id)
                if not trx and getattr(ticket, 'trx_ref_id', None):
                    trx = Transaction.query.filter_by(ref_id=ticket.trx_ref_id).first()
                if not trx:
                    answer_cb("Data transaksi terkait tiket ini tidak ditemukan!", show_alert=True)
                    return

                from app.services.digiflazz import check_transaction_status, apply_digiflazz_seller_metadata, build_seller_complaint_info
                # Jika nomor WA seller belum tersimpan di DB, tarik otomatis dari API Digiflazz terlebih dahulu
                if not getattr(trx, 'seller_wa', None):
                    bebas_sku_list = ['post685480', 'post685481', 'post685482', 'post685483', 'post685485', 'post706873']
                    is_pasca_flow = (not trx.is_prepaid) or (trx.sku_code in bebas_sku_list)
                    ok_chk, d_data, _ = check_transaction_status(trx.sku_code, trx.target_number, trx.ref_id, is_pasca=is_pasca_flow)
                    if ok_chk and isinstance(d_data, dict):
                        apply_digiflazz_seller_metadata(trx, d_data)
                        db.session.commit()
                    else:
                        apply_digiflazz_seller_metadata(trx)
                        db.session.commit()

                msg_low = (ticket.message or "").lower()
                st_up = (trx.status or "").upper()
                if st_up == "SUCCESS" or "belum masuk" in msg_low or "blm masuk" in msg_low or "tidak masuk" in msg_low:
                    c_mode = "sukses_belum_masuk"
                elif st_up in ["FAILED", "GAGAL"]:
                    c_mode = "gagal"
                else:
                    c_mode = "pending"

                info = build_seller_complaint_info(trx, mode=c_mode)
                wa_clean = info.get("seller_wa_clean")
                complaint_text = info.get("complaint_text")
                seller_name = info.get("seller_name") or "Seller Digiflazz"

                if not wa_clean:
                    answer_cb("Seller ini tidak mencantumkan nomor WA di Digiflazz. Gunakan tombol Telegram Seller!", show_alert=True)
                    kb_fallback = []
                    if info.get("tele_url"):
                        kb_fallback.append([{"text": f"✈️ Chat Tele Seller ({info['seller_tele']})", "url": info["tele_url"]}])
                    send_tg_msg(
                        f"ℹ️ <b>Nomor WA Seller Tidak Tersedia di Digiflazz</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🏪 <b>Seller:</b> <b>{seller_name}</b>\n"
                        f"✈️ <b>Telegram Seller:</b> <code>{info.get('seller_tele') or '-'}</code>\n\n"
                        f"📋 <b>Format Komplain Siap Kirim:</b>\n"
                        f"<code>{complaint_text}</code>\n\n"
                        f"💡 <i>Silakan klik tombol Telegram Seller di bawah untuk langsung membuka chat dengan teks komplain terisi otomatis.</i>",
                        reply_to=orig_msg_id,
                        reply_markup={"inline_keyboard": kb_fallback} if kb_fallback else None
                    )
                    return

                from app.wa_helper import kirim_wa
                wa_sent = kirim_wa(wa_clean, complaint_text)

                if wa_sent:
                    # Otomatis update status tiket menjadi PROCESS & beri tahu member bahwa komplain sudah diteruskan ke Biller/Seller
                    if ticket.status == 'OPEN':
                        ticket.status = 'PROCESS'
                    auto_member_note = (
                        f"Halo kak, laporan komplain untuk transaksi {trx.ref_id} telah kami teruskan langsung ke pihak "
                        f"Biller/Seller ({seller_name}). Mohon ditunggu update selanjutnya ya kak 🙏"
                    )
                    if not ticket.admin_reply:
                        ticket.admin_reply = auto_member_note
                        ticket.admin_replied_at = datetime.utcnow()
                        ticket.admin_name = admin_name
                        if ticket.user_id:
                            try:
                                notif = Notification(
                                    title=f"Update Tiket #{ticket.ticket_number}",
                                    message=auto_member_note,
                                    type='info',
                                    link='/bantuan',
                                    target_user_id=ticket.user_id,
                                    is_broadcast=False
                                )
                                db.session.add(notif)
                            except Exception:
                                pass
                    db.session.commit()

                    answer_cb(f"Komplain berhasil dikirim ke WA Seller {seller_name}!")
                    send_tg_msg(
                        f"✅ <b>KOMPLAIN OTOMATIS TERKIRIM KE WA SELLER (BAILEYS)!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🏪 <b>Seller Tujuan:</b> <b>{seller_name}</b>\n"
                        f"📱 <b>No. WA Seller:</b> <code>{wa_clean}</code>\n"
                        f"🎫 <b>Tiket Member:</b> <code>#{ticket.ticket_number}</code> (Status: <b>DIPROSES</b>)\n\n"
                        f"📨 <b>Pesan Standar Digiflazz yang Dikirim:</b>\n"
                        f"<code>{complaint_text}</code>\n\n"
                        f"📌 <i>Member juga telah mendapat pemberitahuan otomatis di web bahwa komplain sedang ditangani bersama pihak Seller.</i>",
                        reply_to=orig_msg_id
                    )
                else:
                    answer_cb("Mesin WA Baileys belum terhubung. Gunakan tombol WA/Tele manual di bawah!", show_alert=True)
                    kb_manual = []
                    row_m = []
                    if info.get("wa_url"):
                        row_m.append({"text": "💬 Buka WA Seller Manual", "url": info["wa_url"]})
                    if info.get("tele_url"):
                        row_m.append({"text": f"✈️ Buka Tele Seller ({info['seller_tele']})", "url": info["tele_url"]})
                    if row_m:
                        kb_manual.append(row_m)
                    send_tg_msg(
                        f"⚠️ <b>Gagal Kirim Otomatis (WA Baileys Sedang Offline)</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🏪 <b>Seller:</b> <b>{seller_name}</b> (WA: <code>{wa_clean}</code>)\n\n"
                        f"📋 <b>Format Komplain:</b>\n<code>{complaint_text}</code>\n\n"
                        f"👇 Klik tombol di bawah untuk mengirim langsung via aplikasi WhatsApp / Telegram:",
                        reply_to=orig_msg_id,
                        reply_markup={"inline_keyboard": kb_manual} if kb_manual else None
                    )
                return

            # B. Balas Template Cepat (Diproses / Selesai)
            elif cb_data.startswith('reply_tpl:'):
                parts = cb_data.split(':')
                if len(parts) >= 3:
                    ticket_num = parts[1].replace('#', '').strip()
                    tpl_type = parts[2]

                    ticket = SupportTicket.query.filter_by(ticket_number=ticket_num).first()
                    if not ticket:
                        ticket = SupportTicket.query.filter(SupportTicket.ticket_number.ilike(f"%{ticket_num}%")).first()

                    if not ticket:
                        answer_cb("Tiket tidak ditemukan!", show_alert=True)
                        return

                    if tpl_type == 'process':
                        reply_text = "Halo kak, laporan keluhan sedang kami lakukan investigasi mendalam ke pihak provider biller. Mohon ditunggu pembaruannya ya kak 🙏"
                        ticket.status = 'PROCESS'
                        action_label = "DIPROSES"
                    elif tpl_type == 'resolved':
                        reply_text = "Halo kak, kendala pada transaksi ini telah berhasil diselesaikan oleh tim CS kami. Silakan cek pembaruan saldo / status transaksi Anda. Terima kasih atas kesabarannya 🙏"
                        ticket.status = 'RESOLVED'
                        action_label = "SELESAI (RESOLVED)"
                    else:
                        reply_text = "Baik kak, laporan sudah dalam penanganan admin kami."
                        action_label = "DIPROSES"

                    # Simpan balasan manual admin
                    ticket.admin_reply = reply_text
                    ticket.admin_replied_at = datetime.utcnow()
                    ticket.admin_name = admin_name

                    # Tambahkan notifikasi in-app untuk user
                    if ticket.user_id:
                        try:
                            notif = Notification(
                                title=f"Balasan CS: Tiket #{ticket.ticket_number}",
                                message=reply_text,
                                type='info',
                                link='/bantuan',
                                target_user_id=ticket.user_id,
                                is_broadcast=False
                            )
                            db.session.add(notif)
                        except Exception:
                            pass

                    db.session.commit()
                    logger.info(f"[Bot 1 CS] Tiket #{ticket.ticket_number} berhasil diupdate via template '{tpl_type}' oleh {admin_name}")

                    answer_cb(f"Tiket #{ticket_num} diupdate ke {action_label}!")
                    send_tg_msg(
                        f"✅ <b>Balasan Terkirim ke Web Pengguna!</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎫 <b>Tiket:</b> <code>#{ticket.ticket_number}</code>\n"
                        f"👤 <b>Pelapor:</b> {ticket.user_name}\n"
                        f"📊 <b>Status Baru:</b> <b>{action_label}</b>\n"
                        f"💬 <b>Balasan yang Tampil di Web:</b>\n<i>\"{reply_text}\"</i>\n\n"
                        f"📌 <i>Pengguna dapat melihat balasan ini secara real-time di halaman Pusat Bantuan web mereka.</i>",
                        reply_to=orig_msg_id
                    )
                    return

        # 2. TANGANI PESAN TEKS (REPLY ATAU COMMAND /balas)
        elif 'message' in update:
            msg = update['message']
            chat_id = msg.get('chat', {}).get('id')
            msg_id = msg.get('message_id')
            text = (msg.get('text') or msg.get('caption') or '').strip()
            from_user = msg.get('from', {})
            first_n = from_user.get('first_name', '')
            last_n = from_user.get('last_name', '')
            admin_name = f"{first_n} {last_n}".strip() or from_user.get('username') or 'Admin CS'

            logger.info(f"[Bot 1 CS] Pesan teks dari @{from_user.get('username')} ({admin_name}): '{text}'")

            def send_tg_msg(resp_text, reply_to=None):
                try:
                    res = call_telegram_api(
                        'post',
                        f"bot{bot_token}/sendMessage",
                        json={
                            "chat_id": chat_id,
                            "text": resp_text,
                            "parse_mode": "HTML",
                            "reply_to_message_id": reply_to
                        },
                        timeout=10
                    )
                    if not res.json().get('ok'):
                        logger.error(f"[Bot 1 CS] Gagal sendMessage: {res.text}")
                except Exception as ex:
                    logger.error(f"[Bot 1 CS] sendMessage exception: {ex}")

            if not text:
                return

            # A. Cek apakah ini Reply ke Pesan Tiket Sebelumnya
            target_ticket_num = None
            reply_to_msg = msg.get('reply_to_message')
            if reply_to_msg:
                parent_text = reply_to_msg.get('text') or reply_to_msg.get('caption') or ''
                match = re.search(r'#?(CS-\d{4,8}-\d+)', parent_text, re.IGNORECASE)
                if match:
                    target_ticket_num = match.group(1).upper()

            # B. Cek apakah menggunakan format command /balas, /jawab, atau tanpa slash
            reply_content = text
            text_lower = text.lower()
            if text_lower.startswith(('/balas', '/jawab', '/reply', 'balas ', 'jawab ')):
                parts = text.split(maxsplit=2)
                if len(parts) >= 3:
                    target_ticket_num = parts[1].replace('#', '').strip().upper()
                    reply_content = parts[2].strip()
                elif target_ticket_num and len(parts) == 2:
                    reply_content = parts[1].strip()
                else:
                    send_tg_msg(
                        "⚠️ <b>Format Perintah Balas:</b>\n"
                        "<code>/balas [Nomor Tiket] [Pesan Balasan]</code>\n"
                        "Contoh: <code>/balas CS-20260928-9520 Pulsa sudah kami cek dan sukses ya kak</code>",
                        reply_to=msg_id
                    )
                    return

            elif text_lower.startswith(('/selesai', '/done', '/close', 'selesai ', 'done ', 'close ')):
                parts = text.split(maxsplit=2)
                if len(parts) >= 2:
                    target_ticket_num = parts[1].replace('#', '').strip().upper()
                    reply_content = parts[2].strip() if len(parts) >= 3 else "Keluhan transaksi ini telah selesai ditangani oleh tim CS. Terima kasih!"
                elif target_ticket_num:
                    reply_content = parts[1].strip() if len(parts) >= 2 else "Keluhan transaksi ini telah selesai ditangani oleh tim CS. Terima kasih!"
                else:
                    send_tg_msg("⚠️ <b>Format Selesai:</b>\n<code>/selesai [Nomor Tiket] [Pesan Penutup]</code>", reply_to=msg_id)
                    return

            elif text_lower in ['/start', '/help', '/menu']:
                send_tg_msg(
                    "🤖 <b>Bot 1 : CS & Balas Inbox GarudaTel</b>\n\n"
                    "Bot ini menerima seluruh tiket keluhan dari pelanggan web secara langsung.\n\n"
                    "<b>Cara Balas ke Web Pengguna:</b>\n"
                    "1. <b>Swipe / Reply</b> langsung pesan tiket di atas, lalu ketik balasan Anda.\n"
                    "2. Gunakan perintah: <code>/balas CS-XXXX pesan balasan</code>\n"
                    "3. Selesaikan tiket: <code>/selesai CS-XXXX pesan penutup</code>\n"
                    "4. Atau tekan tombol <b>[✍️ Balas Manual]</b> di bawah tiket.\n\n"
                    "<i>Balasan Anda langsung dikirim ke halaman Pusat Bantuan web pengguna!</i>",
                    reply_to=msg_id
                )
                return

            # C. Fallback: Jika pengguna menulis nomor tiket langsung (contoh: CS-20260928-9520 pesan)
            if not target_ticket_num:
                parts_check = text.split(maxsplit=1)
                first_word = parts_check[0].replace('#', '').strip().upper()
                if first_word.startswith('CS-') and len(parts_check) >= 2:
                    target_ticket_num = first_word
                    reply_content = parts_check[1].strip()
                else:
                    match_inline = re.search(r'#?(CS-\d{4,8}-\d+)', text, re.IGNORECASE)
                    if match_inline:
                        target_ticket_num = match_inline.group(1).upper()
                        cleaned_msg = re.sub(r'#?CS-\d{4,8}-\d+', '', text, flags=re.IGNORECASE).strip()
                        cleaned_msg = re.sub(r'^(/balas|balas|/jawab|jawab)\s*', '', cleaned_msg, flags=re.IGNORECASE).strip()
                        if cleaned_msg:
                            reply_content = cleaned_msg

            # D. Eksekusi penyimpanan balasan jika tiket ditemukan
            if target_ticket_num:
                ticket = SupportTicket.query.filter_by(ticket_number=target_ticket_num).first()
                if not ticket:
                    ticket = SupportTicket.query.filter(SupportTicket.ticket_number.ilike(f"%{target_ticket_num}%")).first()

                if not ticket:
                    send_tg_msg(f"❌ <b>Tiket #{target_ticket_num} tidak ditemukan di sistem!</b>", reply_to=msg_id)
                    return

                # Update status
                is_closing = text_lower.startswith(('/selesai', '/done', '/close', 'selesai ', 'done ', 'close '))
                if is_closing:
                    ticket.status = 'RESOLVED'
                elif ticket.status == 'OPEN':
                    ticket.status = 'PROCESS'

                # Simpan balasan admin (bisa bertahap jika admin membalas lebih dari 1 kali)
                if ticket.admin_reply:
                    ticket.admin_reply = f"{ticket.admin_reply}\n\n[Pesan Tambahan CS]: {reply_content}"
                else:
                    ticket.admin_reply = reply_content

                ticket.admin_replied_at = datetime.utcnow()
                ticket.admin_name = admin_name

                # Buat notifikasi in-app
                if ticket.user_id:
                    try:
                        notif = Notification(
                            title=f"Balasan CS: Tiket #{ticket.ticket_number}",
                            message=reply_content,
                            type='info',
                            link='/bantuan',
                            target_user_id=ticket.user_id,
                            is_broadcast=False
                        )
                        db.session.add(notif)
                    except Exception:
                        pass

                db.session.commit()
                logger.info(f"[Bot 1 CS] Balasan admin '{reply_content[:40]}...' tersimpan untuk tiket #{ticket.ticket_number} oleh {admin_name}")

                st_badge = "✅ SELESAI" if ticket.status == 'RESOLVED' else "⏳ SEDANG DIPROSES"
                send_tg_msg(
                    f"✅ <b>Balasan Berhasil Dikirim ke Web Pelapor!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🎫 <b>No. Tiket:</b> <code>#{ticket.ticket_number}</code>\n"
                    f"👤 <b>Pelapor:</b> {ticket.user_name} ({ticket.user_phone})\n"
                    f"📊 <b>Status Tiket:</b> <b>{st_badge}</b>\n"
                    f"💬 <b>Balasan yang Tampil di Web:</b>\n"
                    f"<i>\"{reply_content}\"</i>\n\n"
                    f"📌 <i>Pelapor sudah bisa melihat balasan resmi ini langsung di halaman Pusat Bantuan web mereka.</i>",
                    reply_to=msg_id
                )


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
        payload = {
            "chat_id": chat_id,
            "text": full_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        resp = call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=(15, 30))
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
    sku_code = getattr(trx, 'sku_code', '') or ''
    target_number = getattr(trx, 'target_number', '-') or '-'
    amount = float(getattr(trx, 'amount', 0) or 0)
    base_price = float(getattr(trx, 'base_price', 0) or 0)
    payment_method = getattr(trx, 'payment_method', '-') or '-'
    payment_status = getattr(trx, 'payment_status', 'UNPAID') or 'UNPAID'
    user_id = getattr(trx, 'user_id', '-')
    sn = getattr(trx, 'sn', None)
    seller_name = getattr(trx, 'seller_name', None) or getattr(trx, 'resolved_seller_name', None)
    seller_tele = getattr(trx, 'seller_tele', None)
    seller_wa = getattr(trx, 'seller_wa', None)
    complaint_fmt = getattr(trx, 'complaint_fmt', None)

    if not seller_name and sku_code and sku_code not in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT']:
        try:
            from app.models.product import Product
            p_db = Product.query.filter_by(sku_code=sku_code).first()
            if p_db and getattr(p_db, 'seller_name', None):
                seller_name = p_db.seller_name
            if base_price <= 0 and p_db and getattr(p_db, 'base_price', None):
                base_price = float(p_db.base_price or 0.0)
        except Exception:
            pass

    if not complaint_fmt and hasattr(trx, 'format_digiflazz_complaint') and sku_code not in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT']:
        try:
            complaint_fmt = trx.format_digiflazz_complaint()
        except Exception:
            pass

    # Resolusi Nama Pengguna / Toko
    user_name = getattr(trx, 'user_name', None)
    if not user_name and user_id and str(user_id) != '-' and str(user_id).isdigit():
        try:
            from app.models.user import User
            u_db = User.query.get(int(user_id))
            if u_db:
                user_name = u_db.name
        except Exception:
            pass

    user_info = f"#{user_id}"
    if user_name:
        user_info = f"#{user_id} ({user_name})"

    sku_str = f" (<code>{sku_code}</code>)" if sku_code and sku_code not in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL'] else ""
    lines = [
        f"{icon} <b>{title.upper()}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 <b>Ref ID:</b> <code>{ref_id}</code>",
        f"📦 <b>Produk:</b> <code>{product_name}</code>{sku_str}",
    ]
    if seller_name:
        lines.append(f"🏪 <b>Seller:</b> <b>{seller_name}</b>")
    if seller_tele or seller_wa:
        lines.append(f"☎️ <b>CS Seller:</b> ✈️ <code>{seller_tele or '-'}</code> | 📱 <code>{seller_wa or '-'}</code>")

    lines.extend([
        f"📱 <b>Tujuan:</b> <code>{target_number}</code>",
        f"💰 <b>Harga Jual:</b> Rp {amount:,.0f}" + (f" (Modal: Rp {base_price:,.0f})" if base_price > 0 else ""),
        f"💳 <b>Metode:</b> {payment_method} (<b>{payment_status}</b>)",
        f"📊 <b>Status:</b> <b>{status_upper}</b>",
        f"👤 <b>User ID:</b> {user_info}",
        f"⏰ <b>Waktu:</b> {wib_now}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ])

    if sn:
        lines.append(f"🔖 <b>SN/Keterangan:</b> <code>{sn}</code>")

    if complaint_fmt and status_upper in ['PENDING', 'PROCESSING', 'FAILED', 'GAGAL'] and sku_code not in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT']:
        lines.append(f"📣 <b>Format Komplain Seller:</b>\n<code>{complaint_fmt}</code>")

    if "SALDO PROVIDER HABIS" in title.upper():
        lines.append("")
        lines.append("🚨 <b>PERHATIAN SERVER ADMIN:</b>")
        lines.append("⚠️ Transaksi ini GAGAL karena <b>SALDO DEPOSIT PROVIDER HABIS / KURANG</b>!")
        lines.append("👉 Harap segera lakukan Top Up saldo deposit di portal provider terkait (VIP-Reseller / Digiflazz) agar transaksi pengguna tidak terus gagal.")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    full_text = "\n".join(lines)

    try:
        payload = {
            "chat_id": chat_id,
            "text": full_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        r = call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=(15, 30))
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
        user_name = getattr(trx, 'user_name', None)
        user_obj = getattr(trx, 'user', None)
        if not user_name and user_obj and hasattr(user_obj, 'name'):
            user_name = user_obj.name
        if not user_name:
            uid = getattr(trx, 'user_id', None)
            if uid and str(uid).isdigit():
                try:
                    from app.models.user import User
                    u_db = User.query.get(int(uid))
                    if u_db:
                        user_name = u_db.name
                except Exception:
                    pass

        sku_code = getattr(trx, 'sku_code', '') or ''
        seller_name = getattr(trx, 'seller_name', None) or getattr(trx, 'resolved_seller_name', None)
        base_price = float(getattr(trx, 'base_price', 0) or 0)
        if not seller_name and sku_code and sku_code not in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT']:
            try:
                from app.models.product import Product
                p_db = Product.query.filter_by(sku_code=sku_code).first()
                if p_db and getattr(p_db, 'seller_name', None):
                    seller_name = p_db.seller_name
                if base_price <= 0 and p_db and getattr(p_db, 'base_price', None):
                    base_price = float(p_db.base_price or 0.0)
            except Exception:
                pass

        complaint_fmt = None
        if hasattr(trx, 'format_digiflazz_complaint'):
            try:
                complaint_fmt = trx.format_digiflazz_complaint()
            except Exception:
                complaint_fmt = None

        trx_snapshot = {
            'ref_id': getattr(trx, 'ref_id', '-'),
            'product_name': getattr(trx, 'product_name', '-'),
            'sku_code': sku_code,
            'target_number': getattr(trx, 'target_number', '-'),
            'amount': float(getattr(trx, 'amount', 0) or 0),
            'base_price': base_price,
            'payment_method': getattr(trx, 'payment_method', '-'),
            'payment_status': getattr(trx, 'payment_status', 'UNPAID'),
            'status': getattr(trx, 'status', '-'),
            'user_id': getattr(trx, 'user_id', '-'),
            'user_name': user_name,
            'sn': getattr(trx, 'sn', None),
            'seller_name': seller_name,
            'seller_tele': getattr(trx, 'seller_tele', None),
            'seller_wa': getattr(trx, 'seller_wa', None),
            'complaint_fmt': complaint_fmt
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
            with open(backup_file_path, 'rb') as f:
                files = {'document': (filename_only, f, 'application/zip')}
                data = {
                    'chat_id': chat_id,
                    'caption': caption,
                    'parse_mode': 'HTML',
                    'reply_markup': json.dumps(reply_markup)
                }
                res = call_telegram_api('post', f"bot{token}/sendDocument", files=files, data=data, timeout=90)
                return res.status_code == 200, res.text
        else:
            payload = {
                'chat_id': chat_id,
                'text': caption,
                'parse_mode': 'HTML',
                'reply_markup': reply_markup
            }
            res = call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=(15, 30))
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
    # Validasi otorisasi admin secara ketat (Fail-Closed)
    valid_chats = {str(c) for c in [allowed_chat, admin_chat] if c}
    if not valid_chats or str(chat_id) not in valid_chats:
        _answer_callback(token, query_id, "Akses ditolak! Anda bukan Admin terdaftar.")
        logger.warning(f"[Bot 2 Security Alert] Akses callback ditolak dari unauthorized chat_id: {chat_id}")
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
    elif data.startswith('prov_acc_') or data.startswith('prov_rej_'):
        return handle_admin_callback(app, callback_query)


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
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        res = call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=(15, 30))
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
                {"text": "🏆 Top User Hari Ini", "callback_data": "cmd_top_users"},
                {"text": "⏳ Trx Pending", "callback_data": "cmd_pending"}
            ],
            [
                {"text": "🚨 Analisa Produk & Seller Gagal", "callback_data": "cmd_failed_products"}
            ],
            [
                {"text": "🔓 Kelola & Aktifkan Produk Nonaktif", "callback_data": "cmd_disabled_catalog"}
            ],
            [
                {"text": "💰 Saldo Digiflazz", "callback_data": "cmd_saldo"},
                {"text": "📥 Tarik Deposit", "callback_data": "cmd_tarik_deposit"}
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
                {"text": "🖥️ Panel Mitra POS (ipaypos)", "callback_data": "cmd_pos_panel"}
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


def format_rupiah(val):
    """Format angka ke format Rupiah standar Indonesia dengan pemisah titik (cth: Rp 250.000)."""
    try:
        return f"Rp {float(val or 0):,.0f}".replace(',', '.')
    except Exception:
        return f"Rp {val}"


def render_top_users_report(limit=8):
    """
    Menghasilkan teks laporan dan keyboard inline untuk Top Transaksi User Hari Ini.
    Menampilkan rincian:
    - Jumlah transaksi berhasil & gagal
    - Jumlah nominal transaksi (sukses, gagal, dan total volume)
    - Peringkat user/toko paling aktif hari ini.
    """
    from app.extensions import db
    from app.models.transaction import Transaction
    from app.models.user import User
    from sqlalchemy import case

    wib_now = get_wib_now()
    today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start = today_start_wib.astimezone(timezone.utc).replace(tzinfo=None)

    # 1. Ringkasan Keseluruhan Hari Ini
    total_trx = Transaction.query.filter(Transaction.created_at >= today_start).count()
    success_count = Transaction.query.filter(
        Transaction.created_at >= today_start,
        Transaction.status == 'SUCCESS'
    ).count()
    failed_count = Transaction.query.filter(
        Transaction.created_at >= today_start,
        Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL'])
    ).count()
    pending_count = Transaction.query.filter(
        Transaction.created_at >= today_start,
        Transaction.status == 'PENDING'
    ).count()

    success_amt = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.created_at >= today_start,
        Transaction.status == 'SUCCESS',
        ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT'])
    ).scalar() or 0.0

    failed_amt = db.session.query(db.func.sum(Transaction.amount)).filter(
        Transaction.created_at >= today_start,
        Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL'])
    ).scalar() or 0.0

    total_volume = float(success_amt) + float(failed_amt)
    global_rate = round((success_count / total_trx * 100), 1) if total_trx > 0 else 0

    # 2. Agregasi Transaksi Per User / Toko Hari Ini
    user_stats = db.session.query(
        Transaction.user_id,
        db.func.count(Transaction.id).label('total_u_count'),
        db.func.sum(case((Transaction.status == 'SUCCESS', 1), else_=0)).label('u_success_count'),
        db.func.sum(case((Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL']), 1), else_=0)).label('u_failed_count'),
        db.func.sum(case(((Transaction.status == 'SUCCESS') & (~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'COMMISSION_PAYOUT'])), Transaction.amount), else_=0)).label('u_success_amt'),
        db.func.sum(case((Transaction.status.in_(['FAILED', 'GAGAL', 'CANCELLED', 'BATAL']), Transaction.amount), else_=0)).label('u_failed_amt')
    ).filter(
        Transaction.created_at >= today_start,
        Transaction.user_id.isnot(None)
    ).group_by(
        Transaction.user_id
    ).order_by(
        db.desc('u_success_amt'),
        db.desc('total_u_count')
    ).limit(limit).all()

    lines = [
        "🏆 <b>TOP TRANSAKSI USER / TOKO HARI INI</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>Periode:</b> {format_wib(fmt='%A, %d %B %Y')}",
        f"⏰ <b>Update:</b> {format_wib(fmt='%H:%M:%S WIB')}",
        "",
        "📊 <b>RINGKASAN SISTEM HARI INI:</b>",
        f"• <b>Total Transaksi:</b> {total_trx:,} trx",
        f"• <b>Sukses:</b> ✅ {success_count:,} trx (<code>{format_rupiah(success_amt)}</code>)",
        f"• <b>Gagal:</b> ❌ {failed_count:,} trx (<code>{format_rupiah(failed_amt)}</code>)",
        f"• <b>Pending:</b> ⏳ {pending_count:,} trx",
        f"• <b>Total Perputaran:</b> <code>{format_rupiah(total_volume)}</code>",
        f"• <b>Success Rate:</b> {global_rate}%",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    inline_kb = []
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

    if not user_stats:
        lines.append("ℹ️ <i>Belum ada aktivitas transaksi dari pengguna hari ini.</i>")
    else:
        lines.append("🏅 <b>PERINGKAT PENGGUNA TERAKTIF:</b>\n")
        curr_row = []
        for idx, row in enumerate(user_stats):
            u = User.query.get(row.user_id)
            u_name = u.name if u and u.name else f"User #{row.user_id}"
            u_phone = f" (<code>{u.phone}</code>)" if u and u.phone else ""
            u_succ_cnt = int(row.u_success_count or 0)
            u_fail_cnt = int(row.u_failed_count or 0)
            u_succ_amt = float(row.u_success_amt or 0.0)
            u_fail_amt = float(row.u_failed_amt or 0.0)
            u_total_vol = u_succ_amt + u_fail_amt
            u_tot_cnt = int(row.total_u_count or 0)
            u_rate = round((u_succ_cnt / u_tot_cnt * 100), 1) if u_tot_cnt > 0 else 0
            badge = medals[idx] if idx < len(medals) else f"#{idx+1}"

            lines.append(
                f"{badge} <b>{u_name}</b> (<code>#{row.user_id}</code>){u_phone}\n"
                f"   • ✅ Sukses: <b>{u_succ_cnt}</b> trx | <code>{format_rupiah(u_succ_amt)}</code>\n"
                f"   • ❌ Gagal: <b>{u_fail_cnt}</b> trx | <code>{format_rupiah(u_fail_amt)}</code>\n"
                f"   • 🔄 Total: <b>{u_tot_cnt}</b> trx | Vol: <code>{format_rupiah(u_total_vol)}</code> (SR: {u_rate}%)\n"
            )

            # Tombol intip toko (2 toko per baris)
            short_label = (u_name[:14] + "..") if len(u_name) > 16 else u_name
            curr_row.append({"text": f"🏢 {short_label}", "callback_data": f"store_view_{row.user_id}"})
            if len(curr_row) == 2:
                inline_kb.append(curr_row)
                curr_row = []

        if curr_row:
            inline_kb.append(curr_row)

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Klik tombol toko di bawah untuk melihat rincian toko atau atur saldo.</i>")

    inline_kb.append([
        {"text": "🔄 Refresh Data", "callback_data": "cmd_top_users"},
        {"text": "📊 Omset Hari Ini", "callback_data": "cmd_stats"}
    ])
    inline_kb.append([
        {"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": inline_kb}


# ==============================================================================
# FITUR ANALISA PRODUK & SELLER SERING GAGAL (SMART CATALOG HEALTH & ACTION)
# ==============================================================================
EXCLUDED_INTERNAL_SKUS = [
    'DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'MANUAL_DEDUCTION',
    'COMMISSION_PAYOUT', 'ADMIN_BALANCE'
]
FAILED_STATUS_LIST = ['FAILED', 'GAGAL', 'CANCELLED', 'BATAL', 'ERROR']


def format_seller_handle_and_name(seller_name=None, seller_tele=None):
    """
    Merapikan nama Seller & membuat tag standar 'seller@username' seperti contoh:
    'seller@payfast_id' beserta nama resmi Seller Digiflazz.
    """
    import re
    from app.services.digiflazz import normalize_seller_tele_username

    clean_name = clean_str(seller_name)
    if clean_name in ['-', 'None', 'null']:
        clean_name = ''

    tele_user = normalize_seller_tele_username(seller_tele)
    if tele_user:
        seller_tag = f"seller@{tele_user}"
        tele_display = f"@{tele_user}"
    elif clean_name:
        # Jika username telegram belum ditarik dari API transaksi, bentuk slug bersih dari nama seller
        slug = re.sub(r'[^a-zA-Z0-9]+', '_', clean_name.lower()).strip('_')
        slug = re.sub(r'^(pt|cv|ud|toko)_+', '', slug) or 'digiflazz'
        seller_tag = f"seller@{slug[:24]}"
        tele_display = ""
    else:
        clean_name = "Seller Digiflazz"
        seller_tag = "seller@digiflazz"
        tele_display = ""

    display_name = clean_name or (f"@{tele_user}" if tele_user else "Seller Digiflazz")
    return {
        "seller_name": display_name,
        "seller_tag": seller_tag,
        "seller_tele_username": tele_user,
        "seller_tele_display": tele_display,
    }


def _get_period_start_utc(period_code='30d'):
    """Mengembalikan tuple (start_utc_naive, label_periode) berdasarkan kode periode."""
    wib_now = get_wib_now()
    p = str(period_code or '30d').lower().strip()
    if p in ['1d', 'today', 'hariini']:
        start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start_wib.astimezone(timezone.utc).replace(tzinfo=None), "Hari Ini", "1d"
    elif p in ['7d', '7hari', 'week']:
        start_wib = (wib_now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_wib.astimezone(timezone.utc).replace(tzinfo=None), "7 Hari Terakhir", "7d"
    elif p in ['all', 'semua']:
        return None, "Semua Waktu", "all"
    else:
        start_wib = (wib_now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start_wib.astimezone(timezone.utc).replace(tzinfo=None), "30 Hari Terakhir", "30d"


def get_failed_products_analytics(period='30d', filter_mode='all', auto_fallback=False):
    """
    Menganalisa seluruh transaksi produk untuk menemukan produk-produk yang sering gagal
    beserta performa suksesnya, identitas Seller Digiflazz, alasan gagal terakhir,
    dan rekomendasi tindakan otomatis (Pertahankan / Evaluasi / Ganti Seller / Nonaktifkan / Hapus).
    """
    from app.extensions import db
    from app.models.transaction import Transaction
    from app.models.product import Product

    start_utc, period_label, norm_period = _get_period_start_utc(period)

    def _fetch_trxs(since_dt):
        q = Transaction.query.filter(
            ~Transaction.sku_code.in_(EXCLUDED_INTERNAL_SKUS),
            Transaction.payment_method != 'admin_manual'
        )
        if since_dt is not None:
            q = q.filter(Transaction.created_at >= since_dt)
        return q.order_by(Transaction.id.desc()).all()

    trxs = _fetch_trxs(start_utc)

    # Jika auto_fallback aktif dan periode default belum memiliki transaksi gagal, cek Semua Waktu
    has_failed_in_period = any((t.status or '').upper() in FAILED_STATUS_LIST for t in trxs)
    if auto_fallback and not has_failed_in_period and norm_period != 'all':
        all_trxs = _fetch_trxs(None)
        if any((t.status or '').upper() in FAILED_STATUS_LIST for t in all_trxs):
            trxs = all_trxs
            start_utc = None
            period_label = "Semua Waktu (Auto)"
            norm_period = "all"

    # Peta katalog Product berdasarkan sku_code
    all_products = Product.query.all()
    prod_map = {p.sku_code: p for p in all_products if p.sku_code}

    sku_buckets = {}
    global_failed_trx = 0
    global_success_trx = 0
    global_pending_trx = 0

    for t in trxs:
        sku = (t.sku_code or 'UNKNOWN').strip()
        st = (t.status or 'PENDING').upper()

        if st == 'SUCCESS':
            global_success_trx += 1
        elif st in FAILED_STATUS_LIST:
            global_failed_trx += 1
        else:
            global_pending_trx += 1

        if sku not in sku_buckets:
            p_obj = prod_map.get(sku)
            sku_buckets[sku] = {
                'sku_code': sku,
                'product_obj': p_obj,
                'product_id': p_obj.id if p_obj else None,
                'product_name': (p_obj.name if p_obj and p_obj.name else None) or t.product_name or sku,
                'category': (p_obj.category if p_obj else None) or '-',
                'brand': (p_obj.brand if p_obj else None) or '-',
                'is_active': bool(p_obj.is_active) if p_obj is not None else None,
                'in_catalog': p_obj is not None,
                'base_price': float(p_obj.base_price or 0.0) if p_obj else float(t.base_price or 0.0),
                'sell_price': float(p_obj.sell_price or 0.0) if p_obj else float(t.amount or 0.0),
                'failed_count': 0,
                'success_count': 0,
                'pending_count': 0,
                'total_count': 0,
                'failed_amount': 0.0,
                'success_amount': 0.0,
                'raw_seller_name': (p_obj.seller_name if p_obj and p_obj.seller_name else None),
                'raw_seller_tele': None,
                'raw_seller_wa': None,
                'last_fail_reason': None,
                'last_fail_time': None,
                'last_fail_trx': None,
                'failed_trxs': [],
            }

        b = sku_buckets[sku]
        b['total_count'] += 1

        # Ambil metadata seller dari transaksi terbaru jika ada
        if t.seller_name and t.seller_name.strip() and t.seller_name.strip() != '-':
            if not b['raw_seller_name']:
                b['raw_seller_name'] = t.seller_name.strip()
        if t.seller_tele and t.seller_tele.strip() and t.seller_tele.strip() != '-':
            if not b['raw_seller_tele']:
                b['raw_seller_tele'] = t.seller_tele.strip()
        if t.seller_wa and t.seller_wa.strip() and t.seller_wa.strip() != '-':
            if not b['raw_seller_wa']:
                b['raw_seller_wa'] = t.seller_wa.strip()

        if st == 'SUCCESS':
            b['success_count'] += 1
            b['success_amount'] += float(t.amount or 0.0)
        elif st in FAILED_STATUS_LIST:
            b['failed_count'] += 1
            b['failed_amount'] += float(t.amount or 0.0)
            if len(b['failed_trxs']) < 5:
                b['failed_trxs'].append(t)
            if b['last_fail_trx'] is None:
                b['last_fail_trx'] = t
                b['last_fail_reason'] = (t.sn or 'Gagal dari provider / biller').strip()
                b['last_fail_time'] = format_wib(t.created_at, '%d/%m %H:%M') if t.created_at else '-'
        else:
            b['pending_count'] += 1

    # Filter hanya produk yang memiliki minimal 1 kejadian gagal & hitung metrik kelayakan
    all_failed_buckets = []
    seller_agg = {}
    critical_count = 0
    warning_count = 0
    active_failed_count = 0
    disabled_failed_count = 0
    deleted_failed_count = 0
    critical_active_count = 0

    for sku, b in sku_buckets.items():
        if b['failed_count'] <= 0:
            continue

        # Fallback nama seller jika masih kosong
        if not b['raw_seller_name'] and b['last_fail_trx']:
            b['raw_seller_name'] = getattr(b['last_fail_trx'], 'resolved_seller_name', None)

        s_meta = format_seller_handle_and_name(b['raw_seller_name'], b['raw_seller_tele'])
        b['seller_name'] = s_meta['seller_name']
        b['seller_tag'] = s_meta['seller_tag']
        b['seller_tele_username'] = s_meta['seller_tele_username']
        b['seller_tele_display'] = s_meta['seller_tele_display']

        decided_total = b['failed_count'] + b['success_count']
        denom = decided_total if decided_total > 0 else b['total_count']
        fail_rate = round((b['failed_count'] / denom * 100.0), 1) if denom > 0 else 100.0
        succ_rate = round((b['success_count'] / denom * 100.0), 1) if denom > 0 else 0.0
        b['fail_rate'] = fail_rate
        b['success_rate'] = succ_rate

        # Format kalimat ringkasan persis gaya user:
        # misal: "Telkomsel Data UMKM 4GB 30 Hari — 9 kali gagal, 1 kali sukses • seller@payfast_id"
        b['compact_line'] = (
            f"{b['product_name']} — {b['failed_count']} kali gagal, "
            f"{b['success_count']} kali sukses • {b['seller_tag']}"
        )

        # Evaluasi tingkat keparahan & rekomendasi tindakan katalog
        if (b['failed_count'] >= 3 and fail_rate >= 70.0) or (b['failed_count'] >= 5 and fail_rate >= 50.0) or (b['failed_count'] >= 2 and b['success_count'] == 0):
            b['severity'] = 'CRITICAL'
            b['severity_icon'] = '🚨'
            b['recommendation_short'] = 'GANTI SELLER / NONAKTIFKAN / HAPUS!'
            b['recommendation_detail'] = (
                'Produk ini memiliki rasio gagal sangat tinggi. Sangat disarankan segera '
                'DINONAKTIFKAN dari web, DIGANTI SELLER di portal Digiflazz, atau DIHAPUS dari katalog.'
            )
            critical_count += 1
            if b['is_active']:
                critical_active_count += 1
        elif (b['failed_count'] >= 2 and fail_rate >= 35.0) or (b['failed_count'] >= 3):
            b['severity'] = 'WARNING'
            b['severity_icon'] = '⚠️'
            b['recommendation_short'] = 'RAWAN GAGAL — EVALUASI SELLER'
            b['recommendation_detail'] = (
                'Produk ini cukup sering gagal. Periksa apakah jam cut-off seller atau stok seller '
                'tidak stabil, dan pertimbangkan pindah ke seller cadangan.'
            )
            warning_count += 1
        else:
            b['severity'] = 'INFO'
            b['severity_icon'] = '🟢'
            b['recommendation_short'] = 'MASIH LAYAK (PANTAU / CEK INPUT)'
            b['recommendation_detail'] = (
                'Tingkat keberhasilan produk masih bagus atau kegagalan baru terjadi 1 kali '
                '(bisa karena nomor tujuan salah/terblokir). Produk masih layak ditampilkan.'
            )

        # Hitung status katalog produk
        if not b['in_catalog']:
            deleted_failed_count += 1
        elif b['is_active']:
            active_failed_count += 1
        else:
            disabled_failed_count += 1

        # Agregasi per Seller
        s_key = b['seller_name'].upper()
        if s_key not in seller_agg:
            seller_agg[s_key] = {
                'seller_name': b['seller_name'],
                'seller_tag': b['seller_tag'],
                'seller_tele_display': b['seller_tele_display'],
                'failed_count': 0,
                'success_count': 0,
                'total_count': 0,
                'products': [],
                'active_sku_count': 0,
                'disabled_sku_count': 0,
                'sample_trx_id': b['last_fail_trx'].id if b['last_fail_trx'] else 0,
            }
        sa = seller_agg[s_key]
        sa['failed_count'] += b['failed_count']
        sa['success_count'] += b['success_count']
        sa['total_count'] += (b['failed_count'] + b['success_count'])
        sa['products'].append(b)
        if b['is_active']:
            sa['active_sku_count'] += 1
        else:
            sa['disabled_sku_count'] += 1
        if not sa['sample_trx_id'] and b['last_fail_trx']:
            sa['sample_trx_id'] = b['last_fail_trx'].id

        all_failed_buckets.append(b)

    # Filter items sesuai filter_mode agar data yang sudah dinonaktifkan TIDAK MENUMPUK
    # Mode 'active' (DEFAULT): Hanya produk yang MASIH AKTIF di Web yang perlu tindakan admin
    # Mode 'crit': Hanya produk KRITIS yang masih aktif
    # Mode 'all': Menampilkan semua produk termasuk yang sudah nonaktif / dihapus
    norm_filter_mode = str(filter_mode or 'active').lower().strip()
    if norm_filter_mode in ['active', 'act', 'active_only']:
        failed_items = [x for x in all_failed_buckets if x['is_active'] is True]
    elif norm_filter_mode in ['crit', 'critical']:
        failed_items = [x for x in all_failed_buckets if x['is_active'] is True and x['severity'] == 'CRITICAL']
    else:
        failed_items = list(all_failed_buckets)
        norm_filter_mode = 'all'

    # Urutkan produk dari gagal terbanyak -> rasio gagal tertinggi -> sukses paling sedikit
    failed_items.sort(
        key=lambda x: (x['failed_count'], x['fail_rate'], -x['success_count']),
        reverse=True
    )

    # Hitung rasio gagal per seller & urutkan
    seller_leaderboard = []
    for s_val in seller_agg.values():
        s_tot = s_val['failed_count'] + s_val['success_count']
        s_val['fail_rate'] = round((s_val['failed_count'] / s_tot * 100.0), 1) if s_tot > 0 else 100.0
        s_val['products'].sort(key=lambda x: (x['failed_count'], x['fail_rate']), reverse=True)
        seller_leaderboard.append(s_val)

    seller_leaderboard.sort(
        key=lambda s: (s['active_sku_count'] > 0, s['failed_count'], s['fail_rate'], len(s['products'])),
        reverse=True
    )

    return {
        'period': norm_period,
        'period_label': period_label,
        'filter_mode': norm_filter_mode,
        'items': failed_items,
        'all_failed_count': len(all_failed_buckets),
        'total_failed_products': len(all_failed_buckets),
        'active_failed_count': active_failed_count,
        'disabled_failed_count': disabled_failed_count,
        'deleted_failed_count': deleted_failed_count,
        'critical_count': critical_count,
        'critical_active_count': critical_active_count,
        'warning_count': warning_count,
        'global_failed_trx': global_failed_trx,
        'global_success_trx': global_success_trx,
        'global_pending_trx': global_pending_trx,
        'seller_leaderboard': seller_leaderboard,
    }


def render_failed_products_report(period='30d', page=1, per_page=5, filter_mode='active', auto_fallback=False):
    """
    Menghasilkan tampilan pesan HTML Telegram dan Inline Keyboard interaktif
    untuk Laporan Analisa Produk & Seller yang Sering Gagal.
    Secara default (filter_mode='active'), HANYA menampilkan produk yang MASIH AKTIF di Web,
    sehingga produk yang sudah dinonaktifkan atau dihapus langsung lenyap dari daftar agar tidak menumpuk.
    """
    import math
    analytics = get_failed_products_analytics(
        period=period,
        filter_mode=filter_mode,
        auto_fallback=auto_fallback
    )

    norm_period = analytics['period']
    period_label = analytics['period_label']
    norm_filter = analytics['filter_mode']
    items = analytics['items']
    total_items = len(items)
    total_pages = max(1, math.ceil(total_items / per_page))
    page = max(1, min(int(page or 1), total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_items = items[start_idx:end_idx]

    if norm_filter == 'crit':
        filter_title = "Hanya Produk Kritis Aktif 🚨"
    elif norm_filter == 'all':
        filter_title = "Semua Riwayat (Termasuk yg Sudah Nonaktif) 📂"
    else:
        filter_title = "Hanya yg Masih Aktif di Web 🟢 (Triage Cepat)"

    resolved_count = analytics['disabled_failed_count'] + analytics['deleted_failed_count']

    lines = [
        "🚨 <b>LAPORAN ANALISA PRODUK & SELLER SERING GAGAL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>Periode:</b> {period_label} (Hal {page}/{total_pages})",
        f"🔍 <b>Mode Tampilan:</b> {filter_title}",
        "",
        "📊 <b>STATUS KATALOG PERIODE INI:</b>",
        f"• 🚨 <b>Perlu Ditangani (Masih Aktif di Web):</b> <b>{analytics['active_failed_count']}</b> produk",
        f"• ✅ <b>Sudah Beres (Nonaktif / Dihapus):</b> <b>{resolved_count}</b> produk",
        f"• 📦 <b>Total Riwayat Produk Pernah Gagal:</b> <b>{analytics['total_failed_products']}</b> SKU",
        f"• 🔄 <b>Total Transaksi:</b> ❌ {analytics['global_failed_trx']} Gagal | ✅ {analytics['global_success_trx']} Sukses",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    inline_kb = []

    if not page_items:
        if norm_filter in ['active', 'crit'] and analytics['total_failed_products'] > 0:
            lines.append("🎉 <b>Luar biasa! Seluruh produk sering gagal pada periode ini sudah berhasil DINONAKTIFKAN / DIHAPUS dari katalog web!</b>\n")
            lines.append("✅ <i>Katalog Anda kini bersih dari produk bermasalah (data yang sudah Anda edit tidak menumpuk lagi).</i>")
            lines.append("💡 <i>Untuk memeriksa arsip produk yang sudah dinonaktifkan, klik tombol '📂 Tampilkan Riwayat Nonaktif' di bawah.</i>")
        else:
            lines.append("✅ <i>Tidak ditemukan produk yang mengalami kegagalan pada periode/filter ini.</i>")
            lines.append("💡 <i>Gunakan tombol periode di bawah untuk mengecek rentang waktu 7 Hari / 30 Hari / Semua Waktu.</i>")
    else:
        lines.append("📋 <b>DAFTAR PRODUK YANG PERLU DITANGANI:</b>\n")
        prod_btn_row = []

        for idx, item in enumerate(page_items, start=start_idx + 1):
            if not item['in_catalog']:
                cat_badge = "🗑️ <b>SUDAH DIHAPUS</b>"
            elif item['is_active']:
                cat_badge = "🟢 <b>AKTIF (Tampil di Web)</b>"
            else:
                cat_badge = "🔴 <b>NONAKTIF (Disembunyikan)</b>"

            seller_disp = f"<b>{item['seller_name']}</b>"
            if item['seller_tele_display']:
                seller_disp += f" (✈️ <code>{item['seller_tele_display']}</code>)"

            last_reason = (item['last_fail_reason'] or '-')[:75]

            lines.append(
                f"<b>{idx}. {item['product_name']}</b> (<code>{item['sku_code']}</code>)\n"
                f"   📌 <b>{item['failed_count']} kali gagal</b> | <b>{item['success_count']} kali sukses</b> • <code>{item['seller_tag']}</code>\n"
                f"   🏪 Seller: {seller_disp} | Rasio Gagal: <b>{item['fail_rate']}%</b> (SR: {item['success_rate']}%)\n"
                f"   🏷️ Katalog: {cat_badge} | Modal: {format_rupiah(item['base_price'])}\n"
                f"   ⚠️ Alasan Terakhir: <i>{last_reason}</i>\n"
                f"   💡 Analisa: {item['severity_icon']} <b>{item['recommendation_short']}</b>\n"
            )

            short_prod = (item['product_name'][:13] + "..") if len(item['product_name']) > 15 else item['product_name']
            cb_sku = item['sku_code'][:28]
            prod_btn_row.append({
                "text": f"🛠️ #{idx} {short_prod} ({item['failed_count']}G/{item['success_count']}S)",
                "callback_data": f"fp_view:{norm_period}:{cb_sku}"
            })
            if len(prod_btn_row) == 2:
                inline_kb.append(prod_btn_row)
                prod_btn_row = []

        if prod_btn_row:
            inline_kb.append(prod_btn_row)

        # Tampilkan Top 3 Seller Paling Sering Gagal
        top_sellers = analytics['seller_leaderboard'][:3]
        if top_sellers:
            lines.append("━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("🏪 <b>TOP SELLER PALING SERING GAGAL:</b>")
            for s_idx, s_row in enumerate(top_sellers, 1):
                act_label = f"({s_row['active_sku_count']} SKU Aktif)" if s_row['active_sku_count'] > 0 else "(Semua Sudah Nonaktif ✅)"
                lines.append(
                    f"{s_idx}. <b>{s_row['seller_name']}</b> (<code>{s_row['seller_tag']}</code>)\n"
                    f"   └ ❌ <b>{s_row['failed_count']}x Gagal</b> | ✅ <b>{s_row['success_count']}x Sukses</b> "
                    f"(Gagal: {s_row['fail_rate']}% • {act_label})"
                )

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("👇 <i>Klik tombol produk di bawah untuk Nonaktifkan, Hapus, Ganti/Sync Seller, atau Komplain:</i>")

    # Tombol Aksi Masal: Nonaktifkan Semua Produk Kritis yang masih Aktif
    active_crit_count = analytics['critical_active_count']
    if active_crit_count > 0:
        inline_kb.append([
            {
                "text": f"🛑 Matikan Semua Produk Kritis Aktif ({active_crit_count} SKU)",
                "callback_data": f"fp_offcrit:{norm_period}"
            }
        ])

    # Navigasi Halaman jika lebih dari 1 halaman
    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"fp_list:{norm_period}:{page - 1}:{norm_filter}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"fp_list:{norm_period}:{page + 1}:{norm_filter}"})
    if nav_row:
        inline_kb.append(nav_row)

    # Baris Filter Mode & Analisa Per Seller
    # Jika mode 'active' (default): sediakan opsi tampilkan riwayat nonaktif (arsip)
    # Jika mode 'all': sediakan opsi kembali saring hanya yang aktif (bersih)
    if norm_filter == 'active':
        filter_toggle_row = [
            {"text": f"📂 Tampilkan Riwayat Nonaktif ({analytics['total_failed_products']})", "callback_data": f"fp_list:{norm_period}:1:all"}
        ]
        if analytics['critical_active_count'] > 0:
            filter_toggle_row.append({"text": f"🚨 Hanya Kritis ({analytics['critical_active_count']})", "callback_data": f"fp_list:{norm_period}:1:crit"})
        inline_kb.append(filter_toggle_row)
    elif norm_filter == 'crit':
        inline_kb.append([
            {"text": f"🟢 Kembali ke Semua Produk Aktif ({analytics['active_failed_count']})", "callback_data": f"fp_list:{norm_period}:1:active"}
        ])
    else:  # mode 'all'
        inline_kb.append([
            {"text": f"🟢 Saring Hanya yg Masih Aktif ({analytics['active_failed_count']})", "callback_data": f"fp_list:{norm_period}:1:active"}
        ])

    # Tombol Analisa Per Seller (mengarah ke mode aktif)
    inline_kb.append([
        {"text": "🏪 Analisa Per Seller (Top Gagal)", "callback_data": f"fp_sellers:{norm_period}:1:active"}
    ])

    # Baris Filter Periode Waktu
    p_buttons = [
        ("1d", "Hari Ini"),
        ("7d", "7 Hari"),
        ("30d", "30 Hari"),
        ("all", "Semua")
    ]
    period_row = []
    for p_code, p_text in p_buttons:
        prefix = "✅ " if norm_period == p_code else "📅 "
        period_row.append({
            "text": f"{prefix}{p_text}",
            "callback_data": f"fp_list:{p_code}:1:{norm_filter}"
        })
    inline_kb.append(period_row)

    # Baris Refresh & Menu Utama
    inline_kb.append([
        {"text": "🔄 Refresh Analisa (Bersih)", "callback_data": f"fp_list:{norm_period}:{page}:{norm_filter}"},
        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": inline_kb}


def _resolve_fp_sku(sku_fragment):
    """Mencari kode SKU lengkap berdasarkan potongan SKU dari callback_data (maks 28 karakter)."""
    from app.models.product import Product
    from app.models.transaction import Transaction

    frag = str(sku_fragment or '').strip()
    if not frag:
        return ''
    p_exact = Product.query.filter_by(sku_code=frag).first()
    if p_exact:
        return p_exact.sku_code
    t_exact = Transaction.query.filter_by(sku_code=frag).first()
    if t_exact:
        return t_exact.sku_code
    p_pref = Product.query.filter(Product.sku_code.startswith(frag)).first()
    if p_pref:
        return p_pref.sku_code
    t_pref = Transaction.query.filter(Transaction.sku_code.startswith(frag)).first()
    if t_pref:
        return t_pref.sku_code
    return frag


def render_failed_product_detail(sku_code, period='30d'):
    """
    Menampilkan halaman detail analisa 1 produk yang sering gagal beserta tombol eksekusi:
    - Nonaktifkan / Aktifkan produk di katalog web & POS
    - Sync ulang harga & nama seller dari Digiflazz (setelah ganti seller di portal Digiflazz)
    - Tarik kontak Telegram/WA Seller & kirim komplain otomatis
    - Hapus produk dari katalog database
    """
    from app.models.product import Product
    from app.models.transaction import Transaction
    from app.services.digiflazz import build_seller_complaint_info

    sku_clean = _resolve_fp_sku(sku_code)
    start_utc, period_label, norm_period = _get_period_start_utc(period)

    prod = Product.query.filter_by(sku_code=sku_clean).first()
    q = Transaction.query.filter(Transaction.sku_code == sku_clean)
    if start_utc is not None:
        q = q.filter(Transaction.created_at >= start_utc)
    trxs = q.order_by(Transaction.id.desc()).all()

    # Jika di periode ini kosong, ambil dari semua waktu
    if not trxs and start_utc is not None:
        trxs = Transaction.query.filter(Transaction.sku_code == sku_clean).order_by(Transaction.id.desc()).all()
        period_label = "Semua Waktu"

    failed_trxs = [t for t in trxs if (t.status or '').upper() in FAILED_STATUS_LIST]
    success_trxs = [t for t in trxs if (t.status or '').upper() == 'SUCCESS']
    pending_trxs = [t for t in trxs if (t.status or '').upper() not in FAILED_STATUS_LIST + ['SUCCESS']]

    f_cnt = len(failed_trxs)
    s_cnt = len(success_trxs)
    p_cnt = len(pending_trxs)
    denom = (f_cnt + s_cnt) if (f_cnt + s_cnt) > 0 else len(trxs)
    fail_rate = round((f_cnt / denom * 100.0), 1) if denom > 0 else 0.0
    succ_rate = round((s_cnt / denom * 100.0), 1) if denom > 0 else 0.0

    prod_name = (prod.name if prod else None) or (trxs[0].product_name if trxs else sku_clean)
    raw_seller = (prod.seller_name if prod and prod.seller_name else None)
    raw_tele = None
    raw_wa = None
    for t in trxs:
        if not raw_seller and t.seller_name:
            raw_seller = t.seller_name
        if not raw_tele and t.seller_tele:
            raw_tele = t.seller_tele
        if not raw_wa and t.seller_wa:
            raw_wa = t.seller_wa

    s_meta = format_seller_handle_and_name(raw_seller, raw_tele)

    if not prod:
        status_web = "🗑️ <b>SUDAH DIHAPUS DARI KATALOG</b>"
        price_line = "-"
    else:
        status_web = "🟢 <b>AKTIF (Ditampilkan di Web & Kasir)</b>" if prod.is_active else "🔴 <b>NONAKTIF (Disembunyikan dari Web)</b>"
        margin_val = float(prod.sell_price or 0) - float(prod.base_price or 0)
        price_line = f"Modal {format_rupiah(prod.base_price)} ➜ Jual {format_rupiah(prod.sell_price)} (Margin: {format_rupiah(margin_val)})"

    if (f_cnt >= 3 and fail_rate >= 70.0) or (f_cnt >= 2 and s_cnt == 0):
        verdict = "🚨 <b>TIDak LAYAK TAMPIL SEKARANG — Segera Ganti Seller di Digiflazz atau Nonaktifkan/Hapus!</b>"
    elif f_cnt >= 2 and fail_rate >= 35.0:
        verdict = "⚠️ <b>RAWAN GAGAL — Evaluasi Seller / Pertimbangkan Seller Cadangan.</b>"
    else:
        verdict = "🟢 <b>MASIH LAYAK TAMPIL — Kegagalan kemungkinan karena input nomor / gangguan sesaat.</b>"

    lines = [
        "🛠️ <b>DETAIL ANALISA & KEPUTUSAN PRODUK</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📦 <b>Nama Produk:</b> <b>{prod_name}</b>",
        f"🔖 <b>Kode SKU:</b> <code>{sku_clean}</code>",
        f"📂 <b>Kategori / Brand:</b> {(prod.category if prod else '-')} / {(prod.brand if prod else '-')}",
        f"🌐 <b>Status Katalog:</b> {status_web}",
        f"💰 <b>Harga & Margin:</b> {price_line}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 <b>PERFORMA TRANSAKSI ({period_label}):</b>",
        f"👉 <b>{prod_name} — {f_cnt} kali gagal, {s_cnt} kali sukses • <code>{s_meta['seller_tag']}</code></b>",
        f"• ❌ <b>Total Gagal:</b> <b>{f_cnt} kali</b> ({fail_rate}%)",
        f"• ✅ <b>Total Sukses:</b> <b>{s_cnt} kali</b> ({succ_rate}%)",
        f"• ⏳ <b>Pending:</b> {p_cnt} kali",
        f"• 🏪 <b>Nama Seller:</b> <b>{s_meta['seller_name']}</b> (<code>{s_meta['seller_tag']}</code>)",
        f"• ☎️ <b>Kontak CS Seller:</b> ✈️ <code>{raw_tele or 'Belum ditarik'}</code> | 📱 <code>{raw_wa or 'Belum ditarik'}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💡 <b>KESIMPULAN ANALISA:</b>\n{verdict}",
    ]

    last_fail = failed_trxs[0] if failed_trxs else None
    comp_info = build_seller_complaint_info(last_fail, mode='gagal') if last_fail else {}

    if failed_trxs:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📋 <b>5 RIWAYAT GAGAL TERAKHIR PRODUK INI:</b>")
        for idx, ft in enumerate(failed_trxs[:5], 1):
            ft_time = format_wib(ft.created_at, '%d/%m %H:%M') if ft.created_at else '-'
            ft_seller = ft.seller_name or s_meta['seller_name']
            ft_reason = (ft.sn or 'Gagal dari provider')[:65]
            lines.append(
                f"{idx}. <code>{ft.ref_id}</code> ➜ <code>{ft.target_number}</code> ({ft_time})\n"
                f"   🏪 {ft_seller} | ⚠️ <i>{ft_reason}</i>"
            )
        if comp_info.get('complaint_gagal'):
            lines.append("")
            lines.append("📣 <b>Format Komplain Gagal ke Seller (Klik untuk Copy):</b>")
            lines.append(f"<code>{comp_info['complaint_gagal']}</code>")

    cb_sku = sku_clean[:28]
    kb = []

    # 1. Tombol Aktifkan / Nonaktifkan Produk
    if prod:
        if prod.is_active:
            kb.append([
                {"text": "🔴 Sembunyikan Produk Ini dari Web (Nonaktifkan)", "callback_data": f"fp_tog:{norm_period}:{cb_sku}"}
            ])
        else:
            kb.append([
                {"text": "🟢 Tampilkan Kembali Produk Ini (Aktifkan)", "callback_data": f"fp_tog:{norm_period}:{cb_sku}"}
            ])

    # 2. Tombol Sync Ulang Seller & Kontak dari Digiflazz (berguna setelah ganti seller di Digiflazz)
    kb.append([
        {"text": "🔄 Sync Ulang Seller, Harga & Kontak (Digiflazz)", "callback_data": f"fp_sync:{norm_period}:{cb_sku}"}
    ])

    # 3. Tombol Komplain Langsung ke Seller untuk Transaksi Gagal Terakhir
    if last_fail:
        contact_row = []
        if comp_info.get('tele_url'):
            contact_row.append({
                "text": f"✈️ Chat Tele Seller ({comp_info.get('seller_tele')})",
                "url": comp_info['tele_url']
            })
        if comp_info.get('wa_url'):
            contact_row.append({
                "text": "💬 WA Seller Manual",
                "url": comp_info['wa_url']
            })
        if contact_row:
            kb.append(contact_row)
        kb.append([
            {"text": "📲 Auto-Kirim WA Komplain Gagal ke Seller", "callback_data": f"fp_wa:{norm_period}:{last_fail.id}"}
        ])

    # 4. Tombol Hapus Produk dari Katalog (dengan Konfirmasi)
    if prod:
        kb.append([
            {"text": "🗑️ Hapus Produk Ini dari Katalog Database", "callback_data": f"fp_delask:{norm_period}:{cb_sku}"}
        ])

    # 5. Tombol Kembali ke Laporan Utama
    kb.append([
        {"text": "« Kembali ke Laporan Produk Gagal", "callback_data": f"fp_list:{norm_period}:1:active"},
        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": kb}


def render_failed_sellers_report(period='30d', page=1, per_page=5, filter_mode='active'):
    """
    Menampilkan Laporan Rekapitulasi Per Seller Digiflazz yang paling sering gagal.
    Secara default (filter_mode='active'), HANYA menampilkan seller yang masih memiliki produk aktif bermasalah,
    dan tombol matikan produk HANYA menonaktifkan produk gagal dari seller tersebut yang masih aktif (tidak mempengaruhi produk normal).
    """
    import math
    analytics = get_failed_products_analytics(period=period, filter_mode='all')
    norm_period = analytics['period']
    period_label = analytics['period_label']
    norm_filter = str(filter_mode or 'active').lower().strip()
    all_sellers = analytics['seller_leaderboard']

    if norm_filter in ['active', 'act', 'active_only']:
        sellers = [s for s in all_sellers if s['active_sku_count'] > 0]
        filter_title = "Hanya Seller Belum Beres 🟢 (Ada Produk Aktif Gagal)"
    else:
        sellers = all_sellers
        norm_filter = 'all'
        filter_title = "Semua Riwayat Seller Bermasalah 📂"

    total_sellers = len(sellers)
    total_pages = max(1, math.ceil(total_sellers / per_page))
    page = max(1, min(int(page or 1), total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_sellers = sellers[start_idx:end_idx]

    active_sellers_count = sum(1 for s in all_sellers if s['active_sku_count'] > 0)
    resolved_sellers_count = len(all_sellers) - active_sellers_count

    lines = [
        "🏪 <b>RAPOR ANALISA SELLER DIGIFLAZZ SERING GAGAL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 <b>Periode:</b> {period_label} (Hal {page}/{total_pages})",
        f"🔍 <b>Mode Tampilan:</b> {filter_title}",
        f"🏢 <b>Status:</b> 🚨 {active_sellers_count} Belum Beres | ✅ {resolved_sellers_count} Sudah Selesai",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    kb = []

    if not page_sellers:
        if norm_filter == 'active' and len(all_sellers) > 0:
            lines.append("🎉 <b>Luar biasa! Seluruh produk bermasalah dari semua Seller sudah berhasil DINONAKTIFKAN!</b>\n")
            lines.append("✅ <i>Tidak ada lagi produk gagal dari seller manapun yang sedang tayang di web. Data tidak menumpuk.</i>")
            lines.append("💡 <i>Untuk melihat semua riwayat seller terdahulu, klik tombol '📂 Tampilkan Semua Riwayat Seller' di bawah.</i>")
        else:
            lines.append("✅ <i>Tidak ada seller dengan transaksi gagal pada periode ini.</i>")
    else:
        for idx, s in enumerate(page_sellers, start=start_idx + 1):
            badges = []
            if s['active_sku_count'] > 0:
                badges.append(f"🚨 <b>{s['active_sku_count']} Aktif di Web</b>")
            if s.get('disabled_sku_count', 0) > 0:
                badges.append(f"🔴 <b>{s['disabled_sku_count']} Nonaktif (Terkunci)</b>")
            if not badges:
                badges.append("✅ <b>Semua Produk Selesai</b>")
            act_badge = " | ".join(badges)

            lines.append(
                f"<b>{idx}. 🏪 {s['seller_name']}</b> (<code>{s['seller_tag']}</code>)\n"
                f"   • 📊 Total: <b>{s['failed_count']} kali gagal</b> | <b>{s['success_count']} kali sukses</b> (Gagal: <b>{s['fail_rate']}%</b>)\n"
                f"   • 📦 Produk Terdampak: <b>{len(s['products'])} SKU</b> ({act_badge})"
            )
            for p_item in s['products'][:3]:
                st_dot = "🟢" if p_item['is_active'] else "🔴"
                lines.append(
                    f"     {st_dot} <i>{p_item['product_name']}</i> (<code>{p_item['sku_code']}</code>): "
                    f"<b>{p_item['failed_count']}x gagal, {p_item['success_count']}x sukses</b>"
                )
            if len(s['products']) > 3:
                lines.append(f"     <i>...dan {len(s['products']) - 3} produk lainnya.</i>")
            lines.append("")

            # Tombol matikan produk: HANYA jika seller ini masih punya produk gagal yang AKTIF
            if s['active_sku_count'] > 0 and s['sample_trx_id']:
                short_sname = (s['seller_name'][:14] + "..") if len(s['seller_name']) > 16 else s['seller_name']
                kb.append([
                    {
                        "text": f"🛑 Matikan {s['active_sku_count']} Produk Gagal Seller #{idx} ({short_sname})",
                        "callback_data": f"fp_slroff:{norm_period}:{s['sample_trx_id']}"
                    }
                ])

            # Tombol kelola produk nonaktif & aktivasi massal per seller
            if s.get('disabled_sku_count', 0) > 0 and s['sample_trx_id']:
                kb.append([
                    {
                        "text": f"📂 Lihat {s['disabled_sku_count']} Produk Nonaktif #{idx}",
                        "callback_data": f"fp_slrdis:{norm_period}:{s['sample_trx_id']}:1"
                    },
                    {
                        "text": f"🟢 Aktifkan Semua Produk #{idx}",
                        "callback_data": f"fp_slron:{norm_period}:{s['sample_trx_id']}"
                    }
                ])

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 <b>PENTING TENTANG AKSI SELLER:</b>")
        lines.append("• <b>[🛑 Matikan Produk]</b> hanya mematikan produk gagal aktif milik seller tersebut (produk normal tetap aman).")
        lines.append("• Produk yang dinonaktifkan otomatis digembok dari Auto-Sync Digiflazz.")
        lines.append("• Gunakan tombol <b>[📂 Lihat Produk Nonaktif]</b> atau <b>[🟢 Aktifkan Semua]</b> untuk mengembalikan produk seller yang sudah normal.")

    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"fp_sellers:{norm_period}:{page - 1}:{norm_filter}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"fp_sellers:{norm_period}:{page + 1}:{norm_filter}"})
    if nav_row:
        kb.append(nav_row)

    # Baris Filter Toggle Seller
    if norm_filter == 'active':
        kb.append([
            {"text": f"📂 Tampilkan Semua Riwayat Seller ({len(all_sellers)})", "callback_data": f"fp_sellers:{norm_period}:1:all"}
        ])
    else:
        kb.append([
            {"text": f"🟢 Saring Seller Belum Beres ({active_sellers_count})", "callback_data": f"fp_sellers:{norm_period}:1:active"}
        ])

    kb.append([
        {"text": "🔓 Katalog Produk Nonaktif Per Seller", "callback_data": "cmd_disabled_catalog"}
    ])
    kb.append([
        {"text": "📦 Kembali ke Daftar Produk Gagal", "callback_data": f"fp_list:{norm_period}:1:active"},
        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": kb}


def render_disabled_seller_products_report(sample_trx_id, period='30d', page=1, per_page=5):
    """
    Menampilkan daftar produk milik seller tertentu yang saat ini berstatus NONAKTIF (digembok dari Auto-Sync Digiflazz).
    Dilengkapi tombol untuk mengaktifkan kembali produk (per-item maupun sekaligus per-seller).
    """
    import math
    import hashlib
    from app.extensions import db
    from app.models.transaction import Transaction
    from app.models.product import Product
    sample_trx = Transaction.query.get(sample_trx_id)
    target_seller = None
    if sample_trx:
        target_seller = getattr(sample_trx, 'resolved_seller_name', None) or sample_trx.seller_name

    if not target_seller:
        return "❌ <i>Data seller tidak ditemukan!</i>", get_back_button()

    s_meta = format_seller_handle_and_name(target_seller, getattr(sample_trx, 'seller_tele', None))
    analytics = get_failed_products_analytics(period=period, filter_mode='all')
    period_label = analytics['period_label']
    norm_period = analytics['period']

    # Ambil produk nonaktif dari seller ini (dari analytics maupun langsung dari Product catalog)
    seller_disabled_items = [
        p for p in analytics['items']
        if p['seller_name'].upper() == target_seller.upper() and not p['is_active']
    ]

    # Cek juga jika ada produk lain di database Product yang dimiliki seller ini dan is_active=False tapi tidak ada di analytics transaksi
    existing_skus = {p['sku_code'] for p in seller_disabled_items}
    db_extra_prods = Product.query.filter(
        db.func.upper(Product.seller_name) == target_seller.upper(),
        Product.is_active == False
    ).all()
    for dp in db_extra_prods:
        if dp.sku_code not in existing_skus:
            seller_disabled_items.append({
                'sku_code': dp.sku_code,
                'product_name': dp.name,
                'seller_name': dp.seller_name,
                'seller_tag': s_meta['seller_tag'],
                'failed_count': 0,
                'success_count': 0,
                'fail_rate': 0.0,
                'is_active': False,
                'is_admin_disabled': getattr(dp, 'is_admin_disabled', False),
                'product_obj': dp
            })

    total_prods = len(seller_disabled_items)
    total_pages = max(1, math.ceil(total_prods / per_page))
    page = max(1, min(int(page or 1), total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_items = seller_disabled_items[start_idx:end_idx]

    lines = [
        "📂 <b>DAFTAR PRODUK NONAKTIF SELLER</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🏪 <b>Seller:</b> <b>{s_meta['seller_name']}</b> (<code>{s_meta['seller_tag']}</code>)",
        f"📅 <b>Periode:</b> {period_label} (Hal {page}/{total_pages})",
        f"🔒 <b>Total Nonaktif:</b> {total_prods} SKU (Aman dari Auto-Sync Digiflazz)",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    kb = []

    if not page_items:
        lines.append("✅ <i>Tidak ada produk nonaktif untuk seller ini. Seluruh produk saat ini berstatus aktif di web.</i>")
    else:
        lines.append("<i>Produk di bawah ini saat ini dinonaktifkan dari katalog web dan digembok dari Auto-Sync Digiflazz:</i>\n")
        s_hash = hashlib.md5(target_seller.strip().upper().encode('utf-8')).hexdigest()[:8]
        for idx, item in enumerate(page_items, start=start_idx + 1):
            is_locked = bool(item.get('is_admin_disabled', False)) or (item.get('product_obj') and getattr(item['product_obj'], 'is_admin_disabled', False))
            lock_str = "🔒 Gembok Admin: Aktif" if is_locked else "🔓 Standar"
            lines.append(
                f"<b>{idx}. 🔴 {item['product_name']}</b> (<code>{item['sku_code']}</code>)\n"
                f"   • Riwayat: <b>{item['failed_count']}x gagal</b> | <b>{item['success_count']}x sukses</b> (Gagal: <b>{item['fail_rate']}%</b>)\n"
                f"   • Status: {lock_str}"
            )
            cb_sku = item['sku_code'][:28]
            p_obj = item.get('product_obj')
            if p_obj:
                kb.append([
                    {"text": f"🟢 Aktifkan #{idx} ({item['sku_code'][:12]})", "callback_data": f"dis_act_one:{p_obj.id}:{s_hash}"},
                    {"text": f"🔍 Detail", "callback_data": f"fp_view:{norm_period}:{cb_sku}"}
                ])
            else:
                kb.append([
                    {"text": f"🔍 Kelola / Aktifkan #{idx} ({item['sku_code']})", "callback_data": f"fp_view:{norm_period}:{cb_sku}"}
                ])
            lines.append("")

        lines.append("━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("💡 <i>Anda dapat mengaktifkan kembali produk di atas satu per satu (tombol hijau) atau sekaligus seluruhnya untuk seller ini.</i>")

        # Tombol Aktifkan Semua Produk Nonaktif Seller Ini diletakkan paling atas
        kb.insert(0, [
            {
                "text": f"🟢 Aktifkan Semua ({total_prods} Produk) Seller Ini",
                "callback_data": f"fp_slron:{norm_period}:{sample_trx_id}"
            }
        ])

    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"fp_slrdis:{norm_period}:{sample_trx_id}:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"fp_slrdis:{norm_period}:{sample_trx_id}:{page + 1}"})
    if nav_row:
        kb.append(nav_row)

    kb.append([
        {"text": "🔓 Buka Katalog Nonaktif Lengkap", "callback_data": "cmd_disabled_catalog"},
        {"text": "« Kembali ke Rapor Seller", "callback_data": f"fp_sellers:{norm_period}:1:all"}
    ])
    kb.append([
        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": kb}


# State & Cache Pencarian Produk Nonaktif Admin (Bot 3)
_ADMIN_SEARCH_STATE = {}
_SEARCH_KEYWORDS_CACHE = {}


def get_disabled_sellers_list():
    """
    Mengambil daftar seluruh seller yang memiliki produk berstatus nonaktif
    atau terkunci gembok admin (is_active == False atau is_admin_disabled == True)
    langsung dari tabel Product.
    Mengembalikan list of dict terurut dari yang terbanyak produk nonaktifnya.
    """
    import hashlib
    from app.models.product import Product

    prods = Product.query.filter(
        (Product.is_active == False) | (Product.is_admin_disabled == True)
    ).all()

    seller_map = {}
    for p in prods:
        s_raw = (p.seller_name or '').strip()
        s_key = s_raw.upper() if s_raw else '__NONE__'
        if s_key not in seller_map:
            s_hash = hashlib.md5(s_key.encode('utf-8')).hexdigest()[:8]
            seller_map[s_key] = {
                'key': s_key,
                'hash': s_hash,
                'raw_name': s_raw,
                'display_name': s_raw if s_raw else 'Tanpa Seller / Default',
                'products': []
            }
        seller_map[s_key]['products'].append(p)

    sorted_sellers = sorted(
        seller_map.values(),
        key=lambda item: (-len(item['products']), item['display_name'].lower())
    )
    return sorted_sellers


def render_disabled_catalog_sellers_menu(page=1, per_page=6):
    """
    Menampilkan menu daftar seller yang memiliki produk nonaktif di katalog.
    Admin dapat memilih salah satu seller untuk melihat dan mengaktifkan produknya,
    atau menggunakan tombol pencarian untuk mencari nama produk secara langsung.
    """
    import math

    sellers = get_disabled_sellers_list()
    total_sellers = len(sellers)
    total_disabled_products = sum(len(s['products']) for s in sellers)

    total_pages = max(1, math.ceil(total_sellers / per_page))
    page = max(1, min(int(page or 1), total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_sellers = sellers[start_idx:end_idx]

    lines = [
        "🔓 <b>KATALOG PRODUK NONAKTIF PER SELLER</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "Kelola dan aktifkan kembali produk yang dinonaktifkan / digembok.",
        f"📊 <b>Total Nonaktif:</b> {total_disabled_products} Produk ({total_sellers} Seller)",
        f"📄 <b>Halaman:</b> {page} dari {total_pages}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    kb = []

    if not sellers:
        lines.append("🎉 <b>SEMUA PRODUK AKTIF!</b>")
        lines.append("<i>Saat ini tidak ada produk yang berstatus nonaktif di katalog database.</i>")
        lines.append("<i>Seluruh produk sedang tayang dan aktif di website & kasir POS.</i>")
        kb.append([
            {"text": "🔄 Refresh", "callback_data": "cmd_disabled_catalog"},
            {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
        ])
        return "\n".join(lines), {"inline_keyboard": kb}

    # Tombol Pencarian Cepat di bagian paling atas
    kb.append([
        {"text": "🔍 CARI PRODUK NONAKTIF (Ketik Nama / SKU)", "callback_data": "dis_search_prompt"}
    ])

    lines.append("Silakan <b>klik nama seller</b> di bawah untuk melihat rincian produk, atau klik <b>Cari Produk</b> di atas:\n")

    for i, s_item in enumerate(page_sellers, start=start_idx + 1):
        s_count = len(s_item['products'])
        lines.append(f"<b>{i}. 🏪 {s_item['display_name']}</b> — <b>{s_count}</b> Produk Nonaktif")
        btn_text = f"🏪 #{i}. {s_item['display_name'][:20]} ({s_count} Produk)"
        kb.append([
            {"text": btn_text, "callback_data": f"dis_slr:{s_item['hash']}:1"}
        ])

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Produk yang diaktifkan kembali otomatis membuka gembok admin dan langsung aktif di web.</i>")

    # Pagination row
    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"dis_menu:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"dis_menu:{page + 1}"})
    if nav_row:
        kb.append(nav_row)

    kb.append([
        {"text": "🚨 Laporan Produk Sering Gagal", "callback_data": "cmd_failed_products"},
        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": kb}


def render_disabled_catalog_seller_products(seller_hash, page=1, per_page=5):
    """
    Menampilkan daftar produk nonaktif milik seller yang dipilih (berdasarkan seller hash).
    Admin dapat:
    1. Memilih produk tertentu untuk diaktifkan (1-klik tombol per produk).
    2. Mengaktifkan seluruh produk nonaktif seller ini sekaligus (1-klik tombol).
    """
    import math

    sellers = get_disabled_sellers_list()
    target_seller = next((s for s in sellers if s['hash'] == str(seller_hash).strip()), None)

    if not target_seller:
        return (
            "🎉 <b>SEMUA PRODUK SELLER INI TELAH AKTIF!</b>\n"
            "Seluruh produk milik seller ini sudah berhasil diaktifkan kembali dan sedang tayang di website & kasir POS.",
            {
                "inline_keyboard": [
                    [{"text": "« Kembali ke Daftar Seller", "callback_data": "cmd_disabled_catalog"}],
                    [{"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}]
                ]
            }
        )

    prods = target_seller['products']
    total_prods = len(prods)

    total_pages = max(1, math.ceil(total_prods / per_page))
    page = max(1, min(int(page or 1), total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_prods = prods[start_idx:end_idx]

    lines = [
        "📂 <b>PRODUK NONAKTIF SELLER</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🏪 <b>Seller:</b> <b>{target_seller['display_name']}</b>",
        f"🔒 <b>Total Nonaktif:</b> {total_prods} Produk (Digembok dari Auto-Sync)",
        f"📄 <b>Halaman:</b> {page} dari {total_pages}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    kb = []

    if not page_prods:
        lines.append("🎉 <b>SEMUA PRODUK SELLER INI TELAH AKTIF!</b>")
        lines.append("<i>Tidak ada lagi produk nonaktif untuk seller ini.</i>")
        kb.append([
            {"text": "« Kembali ke Daftar Seller", "callback_data": "cmd_disabled_catalog"},
            {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
        ])
        return "\n".join(lines), {"inline_keyboard": kb}

    lines.append("<i>Pilih produk yang ingin Anda aktifkan kembali di bawah:</i>\n")

    # Tombol Aktifkan Semua Produk Seller Ini diletakkan paling atas
    kb.append([
        {
            "text": f"🟢 Aktifkan SEMUA ({total_prods} Produk) Seller Ini",
            "callback_data": f"dis_act_all:{seller_hash}"
        }
    ])

    for num, p in enumerate(page_prods, start=start_idx + 1):
        price_str = format_rupiah(p.base_price) if getattr(p, 'base_price', None) else '-'
        lock_status = "🔒 Digembok Admin" if getattr(p, 'is_admin_disabled', False) else "🔴 Nonaktif"
        lines.append(
            f"<b>{num}. 🔴 {p.name}</b>\n"
            f"   • SKU: <code>{p.sku_code}</code> | Modal: {price_str}\n"
            f"   • Kategori: {p.category or '-'} | Status: {lock_status}"
        )
        lines.append("")

        # Tombol 1-klik aktifkan produk ini
        btn_label = f"🟢 Aktifkan #{num}: {p.sku_code[:16]}"
        kb.append([
            {
                "text": btn_label,
                "callback_data": f"dis_act_one:{p.id}:{seller_hash}"
            }
        ])

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Klik tombol hijau [🟢 Aktifkan] pada produk yang ingin Anda nyalakan kembali.</i>")

    # Pagination baris
    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"dis_slr:{seller_hash}:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"dis_slr:{seller_hash}:{page + 1}"})
    if nav_row:
        kb.append(nav_row)

    kb.append([
        {"text": "🔍 Cari Produk Nonaktif", "callback_data": "dis_search_prompt"},
        {"text": "« Pilih Seller Lain", "callback_data": "cmd_disabled_catalog"}
    ])
    kb.append([
        {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
    ])

    return "\n".join(lines), {"inline_keyboard": kb}


def render_disabled_search_results(keyword, page=1, per_page=5):
    """
    Mencari produk nonaktif (is_active == False atau is_admin_disabled == True)
    berdasarkan nama produk, brand, kode SKU, kategori, atau nama seller.
    Mendukung aktivasi satuan (1-klik) dan aktivasi massal seluruh hasil pencarian.
    """
    import math
    import hashlib
    from app.models.product import Product
    from sqlalchemy import or_, and_

    kw = (keyword or '').strip()
    if not kw:
        return (
            "⚠️ <b>KATA KUNCI PENCARIAN KOSONG</b>\n\n"
            "Silakan ketik nama produk, brand, atau kode SKU yang ingin Anda cari.\n"
            "Contoh: <code>/cari telkomsel 10</code>",
            {
                "inline_keyboard": [
                    [{"text": "🔍 Coba Cari Lagi", "callback_data": "dis_search_prompt"}],
                    [{"text": "« Kembali ke Katalog Seller", "callback_data": "cmd_disabled_catalog"}]
                ]
            }
        )

    kw_hash = hashlib.md5(kw.lower().encode('utf-8')).hexdigest()[:8]
    _SEARCH_KEYWORDS_CACHE[kw_hash] = kw

    # Parsing multi-kata (semua kata harus cocok pada produk)
    terms = kw.split()
    conds = []
    for term in terms:
        t_pat = f"%{term}%"
        conds.append(or_(
            Product.name.ilike(t_pat),
            Product.sku_code.ilike(t_pat),
            Product.brand.ilike(t_pat),
            Product.category.ilike(t_pat),
            Product.seller_name.ilike(t_pat)
        ))

    status_filter = or_(Product.is_active == False, Product.is_admin_disabled == True)
    query = Product.query.filter(and_(status_filter, *conds)).order_by(Product.name.asc())
    prods = query.all()
    total_found = len(prods)

    total_pages = max(1, math.ceil(total_found / per_page))
    page = max(1, min(int(page or 1), total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_prods = prods[start_idx:end_idx]

    lines = [
        "🔍 <b>HASIL PENCARIAN PRODUK NONAKTIF</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🔎 <b>Kata Kunci:</b> <code>{kw}</code>",
        f"📊 <b>Ditemukan:</b> <b>{total_found}</b> Produk Nonaktif",
        f"📄 <b>Halaman:</b> {page} dari {total_pages}",
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    kb = []

    if not prods:
        lines.append("❌ <b>TIDAK ADA PRODUK NONAKTIF YANG COCOK!</b>\n")
        lines.append(f"Tidak ditemukan produk nonaktif dengan kata kunci: <i>'{kw}'</i>.")
        lines.append("<i>Kemungkinan produk sudah berstatus aktif, atau silakan coba kata kunci lain.</i>")
        kb.append([
            {"text": "🔍 Cari Kata Kunci Lain", "callback_data": "dis_search_prompt"},
            {"text": "« Kembali ke Daftar Seller", "callback_data": "cmd_disabled_catalog"}
        ])
        kb.append([{"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}])
        return "\n".join(lines), {"inline_keyboard": kb}

    lines.append("<i>Pilih produk yang ingin Anda aktifkan kembali di bawah:</i>\n")

    # Tombol Aktifkan Semua Hasil Pencarian jika ada lebih dari 1 produk
    if total_found > 1:
        kb.append([
            {
                "text": f"⚡ Aktifkan SEMUA ({total_found} Produk) Hasil Pencarian Ini",
                "callback_data": f"dis_act_srch_all:{kw_hash}"
            }
        ])

    for num, p in enumerate(page_prods, start=start_idx + 1):
        seller_disp = (p.seller_name or '').strip() or 'Tanpa Seller / Default'
        price_str = format_rupiah(p.base_price) if getattr(p, 'base_price', None) else '-'
        lock_status = "🔒 Digembok Admin" if getattr(p, 'is_admin_disabled', False) else "🔴 Nonaktif"

        lines.append(
            f"<b>{num}. 🔴 {p.name}</b>\n"
            f"   • SKU: <code>{p.sku_code}</code> | Modal: {price_str}\n"
            f"   • 🏪 Seller: <b>{seller_disp}</b>\n"
            f"   • Kategori: {p.category or '-'} | Status: {lock_status}"
        )
        lines.append("")

        btn_label = f"🟢 Aktifkan #{num}: {p.sku_code[:16]}"
        kb.append([
            {
                "text": btn_label,
                "callback_data": f"dis_act_srch_one:{p.id}:{kw_hash}:{page}"
            }
        ])

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 <i>Klik tombol hijau [🟢 Aktifkan] pada produk yang ingin Anda nyalakan kembali.</i>")

    # Pagination baris
    nav_row = []
    if page > 1:
        nav_row.append({"text": "« Hal Sebelumnya", "callback_data": f"dis_srch_pg:{kw_hash}:{page - 1}"})
    if page < total_pages:
        nav_row.append({"text": "Hal Berikutnya »", "callback_data": f"dis_srch_pg:{kw_hash}:{page + 1}"})
    if nav_row:
        kb.append(nav_row)

    kb.append([
        {"text": "🔍 Cari Kata Kunci Lain", "callback_data": "dis_search_prompt"},
        {"text": "« Kembali ke Daftar Seller", "callback_data": "cmd_disabled_catalog"}
    ])
    kb.append([{"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}])

    return "\n".join(lines), {"inline_keyboard": kb}




def render_tarik_deposit_menu():
    """
    Menghasilkan tampilan menu awal Tarik Deposit:
    Memeriksa tiket pending aktif terlebih dahulu. Jika ada, tampilkan rincian tiket & opsi batalkan.
    Jika tidak ada tiket pending, tampilkan pilihan metode pembayaran.
    """
    from app.models.deposit_ticket import DigiDepositTicket

    # Cek apakah ada tiket deposit yang masih PENDING
    active_ticket = DigiDepositTicket.query.filter_by(status='PENDING').order_by(DigiDepositTicket.id.desc()).first()
    if active_ticket:
        created_wib = active_ticket.created_at_wib
        text = (
            "⚠️ <b>TIKET DEPOSIT AKTIF TERDETEKSI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Anda masih memiliki tiket deposit yang berstatus <b>PENDING</b>:\n\n"
            f"🎟️ <b>ID Tiket:</b> <code>#{active_ticket.id}</code>\n"
            f"💳 <b>Metode / Bank:</b> <code>{active_ticket.bank}</code>\n"
            f"💵 <b>Nominal Diminta:</b> {format_rupiah(active_ticket.amount_requested)}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔢 <b>JUMLAH HARUS DITRANSFER:</b>\n"
            f"👉 <code>{format_rupiah(active_ticket.amount_transfer)}</code>\n"
            "⚠️ <i>(Wajib transfer tepat termasuk 3 digit kode unik!)</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 <b>Rekening Tujuan:</b> <code>{active_ticket.account_number or '-'}</code>\n"
            f"🏢 <b>Atas Nama:</b> {active_ticket.account_name or 'Digiflazz'}\n"
            f"👤 <b>Pengirim:</b> {active_ticket.owner_name}\n"
            f"📝 <b>Catatan:</b> {active_ticket.notes or '-'}\n"
            f"⏰ <b>Dibuat:</b> {created_wib}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan selesaikan transfer atau batalkan tiket di bawah ini sebelum membuat tiket baru:"
        )
        markup = {
            "inline_keyboard": [
                [{"text": f"❌ Batalkan Tiket #{active_ticket.id}", "callback_data": f"depo_cancel_{active_ticket.id}"}],
                [{"text": "➕ Tetap Buat Tiket Baru", "callback_data": "depo_new_menu"}],
                [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
            ]
        }
        return text, markup

    return render_tarik_deposit_methods_menu()


def render_tarik_deposit_methods_menu():
    """Tampilan pilihan metode tarik deposit (GoPay, ShopeePay, Bank)."""
    text = (
        "📥 <b>TARIK TIKET DEPOSIT DIGIFLAZZ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Pilih metode pembayaran deposit:\n"
        "• <i>Minimal deposit: <b>Rp 200.000 (200K)</b></i>\n"
        "• <i>Saldo otomatis masuk setelah transfer diverifikasi.</i>\n\n"
        "Silakan pilih metode pembayaran di bawah:"
    )
    markup = {
        "inline_keyboard": [
            [
                {"text": "🟢 GoPay", "callback_data": "depo_method_GoPay"},
                {"text": "🟠 ShopeePay", "callback_data": "depo_method_ShopeePay"}
            ],
            [
                {"text": "🏦 BCA", "callback_data": "depo_method_BCA"},
                {"text": "🏦 Bank Mandiri", "callback_data": "depo_method_MANDIRI"}
            ],
            [
                {"text": "🏦 BRI", "callback_data": "depo_method_BRI"},
                {"text": "🏦 BNI", "callback_data": "depo_method_BNI"}
            ],
            [
                {"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}
            ]
        ]
    }
    return text, markup


def render_tarik_deposit_amounts(method):
    """
    Tampilan pemilihan nominal cepat minimal 200K untuk metode tertentu.
    """
    m_lower = str(method).lower()
    if m_lower in ['shopeepay', 'shoopepay']:
        method_title = 'ShopeePay'
    elif m_lower in ['gopay', 'go-pay']:
        method_title = 'GoPay'
    else:
        method_title = str(method).upper()

    text = (
        f"📥 <b>TARIK DEPOSIT - METODE {method_title}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Pilih nominal cepat di bawah (Min. Rp 200.000):\n\n"
        "Atau ketik langsung di chat:\n"
        f"👉 <code>/tarikdeposit {method} &lt;nominal&gt; [nama_pengirim]</code>\n"
        f"Contoh: <code>/tarikdeposit {method} 250000 ANGGA DIAN</code>"
    )
    markup = {
        "inline_keyboard": [
            [
                {"text": "Rp 200.000", "callback_data": f"depo_exec_{method}_200000"},
                {"text": "Rp 300.000", "callback_data": f"depo_exec_{method}_300000"}
            ],
            [
                {"text": "Rp 500.000", "callback_data": f"depo_exec_{method}_500000"},
                {"text": "Rp 1.000.000", "callback_data": f"depo_exec_{method}_1000000"}
            ],
            [
                {"text": "Rp 2.000.000", "callback_data": f"depo_exec_{method}_2000000"},
                {"text": "Rp 5.000.000", "callback_data": f"depo_exec_{method}_5000000"}
            ],
            [
                {"text": "« Ganti Metode", "callback_data": "depo_new_menu"},
                {"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}
            ]
        ]
    }
    return text, markup


def execute_tarik_deposit(token, chat_id, message_id, method, amount, owner_name=None, is_edit=True):
    """
    Mengeksekusi penarikan tiket deposit ke Digiflazz dan menyimpan riwayat ke DigiDepositTicket.
    Memvalidasi batas minimal Rp 200.000 (200K).
    """
    from app.extensions import db
    from app.models.deposit_ticket import DigiDepositTicket
    from app.services.digiflazz import request_deposit

    try:
        amount_int = int(float(amount))
    except (ValueError, TypeError):
        err_text = "⚠️ <b>Nominal Tidak Valid!</b>\nMasukkan nominal berupa angka bulat tanpa titik/koma."
        if is_edit and message_id:
            _edit_message(token, chat_id, message_id, err_text, get_back_button())
        else:
            _send_message(token, chat_id, err_text, reply_markup=get_back_button())
        return

    # Validasi minimal 200K sesuai permintaan
    if amount_int < 200000:
        err_text = (
            "⚠️ <b>NOMINAL DI BAWAH BATAS MINIMAL!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Minimal penarikan tiket deposit adalah <b>Rp 200.000 (200K)</b>.\n"
            f"Nominal yang diminta: <code>Rp {amount_int:,.0f}</code>\n\n"
            "Silakan pilih atau masukkan nominal minimal 200K ke atas."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "📥 Pilih Nominal Minimal 200K", "callback_data": f"depo_method_{method}"}],
                [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
            ]
        }
        if is_edit and message_id:
            _edit_message(token, chat_id, message_id, err_text, markup)
        else:
            _send_message(token, chat_id, err_text, reply_markup=markup)
        return

    # Jika nama pengirim tidak ditentukan, gunakan riwayat tiket terakhir atau .env
    if not owner_name:
        last_ticket = DigiDepositTicket.query.order_by(DigiDepositTicket.id.desc()).first()
        if last_ticket and last_ticket.owner_name:
            owner_name = last_ticket.owner_name
        else:
            owner_name = os.getenv('DIGI_OWNER_NAME', 'ANGGA DIAN')

    if is_edit and message_id:
        _edit_message(token, chat_id, message_id, f"⏳ <i>Sedang meminta tiket deposit Rp {amount_int:,.0f} via {method} ke Digiflazz...</i>", None)

    success, data, message = request_deposit(amount_int, method, owner_name)

    if success:
        amount_transfer = float(data.get('amount', amount_int))
        acc_no = data.get('account_no', '') or data.get('account_number', '') or data.get('notes', '')
        acc_name = data.get('account_name', 'PT DIGIFLAZZ INTERKONEKSI INDONESIA')
        notes = data.get('notes', '')
        bank_res = data.get('bank', method)

        ticket = DigiDepositTicket(
            amount_requested=float(amount_int),
            amount_transfer=amount_transfer,
            bank=bank_res,
            owner_name=owner_name,
            account_number=acc_no,
            account_name=acc_name,
            notes=notes,
            rc=data.get('rc', '00'),
            status='PENDING'
        )
        db.session.add(ticket)
        db.session.commit()

        text_reply = (
            "✅ <b>TIKET DEPOSIT BERHASIL DIBUAT!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎟️ <b>ID Tiket:</b> <code>#{ticket.id}</code>\n"
            f"💳 <b>Metode / Bank:</b> <code>{bank_res}</code>\n"
            f"💵 <b>Nominal Diminta:</b> {format_rupiah(amount_int)}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🔢 <b>JUMLAH HARUS DITRANSFER:</b>\n"
            f"👉 <code>{format_rupiah(amount_transfer)}</code>\n"
            "⚠️ <i>(WAJIB TEPAT! Termasuk 3 digit kode unik agar saldo otomatis masuk)</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏦 <b>Rekening / Tujuan:</b> <code>{acc_no}</code>\n"
            f"🏢 <b>Atas Nama Tujuan:</b> {acc_name}\n"
            f"👤 <b>Nama Pengirim:</b> {owner_name}\n"
            f"📝 <b>Catatan:</b> {notes or '-'}\n"
            f"⏰ <b>Waktu:</b> {ticket.created_at_wib}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>Saldo akan otomatis bertambah ke akun Digiflazz setelah transfer berhasil diverifikasi.</i>"
        )
        markup = {
            "inline_keyboard": [
                [{"text": f"❌ Batalkan Tiket #{ticket.id}", "callback_data": f"depo_cancel_{ticket.id}"}],
                [{"text": "💰 Cek Saldo Sekarang", "callback_data": "cmd_saldo"}],
                [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
            ]
        }
    else:
        text_reply = (
            "🚨 <b>GAGAL MEMBUAT TIKET DEPOSIT!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Metode:</b> {method}\n"
            f"• <b>Nominal:</b> {format_rupiah(amount_int)}\n"
            f"• <b>Alasan / Respon:</b> <i>{message}</i>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Silakan periksa kredensial atau coba metode deposit lainnya."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "🔄 Coba Lagi", "callback_data": f"depo_method_{method}"}],
                [{"text": "📥 Pilih Metode Lain", "callback_data": "depo_new_menu"}],
                [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
            ]
        }

    if is_edit and message_id:
        _edit_message(token, chat_id, message_id, text_reply, markup)
    else:
        _send_message(token, chat_id, text_reply, reply_markup=markup)


def cancel_tarik_deposit(token, chat_id, message_id, ticket_id, is_edit=True):
    """Membatalkan tiket deposit aktif."""
    from app.extensions import db
    from app.models.deposit_ticket import DigiDepositTicket

    ticket = DigiDepositTicket.query.get(ticket_id)
    if not ticket:
        text = f"❌ Tiket deposit #{ticket_id} tidak ditemukan!"
        markup = get_back_button()
    else:
        ticket.status = 'CANCELLED'
        db.session.commit()
        text = (
            f"✅ <b>TIKET DEPOSIT #{ticket.id} TELAH DIBATALKAN!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"• <b>Bank / Metode:</b> {ticket.bank}\n"
            f"• <b>Nominal Transfer:</b> {format_rupiah(ticket.amount_transfer)}\n"
            f"• <b>Status Sekarang:</b> ❌ DIBATALKAN (CANCELLED)\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "Anda sekarang dapat membuat tiket deposit baru dengan aman."
        )
        markup = {
            "inline_keyboard": [
                [{"text": "📥 Tarik Tiket Baru", "callback_data": "cmd_tarik_deposit"}],
                [{"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}]
            ]
        }

    if is_edit and message_id:
        _edit_message(token, chat_id, message_id, text, markup)
    else:
        _send_message(token, chat_id, text, reply_markup=markup)


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
        token, allowed_chat = get_bot_notif_credentials()
    if not token:
        return

    query_id = callback_query.get('id')
    message = callback_query.get('message', {})
    chat_id = str(message.get('chat', {}).get('id', ''))
    message_id = message.get('message_id')
    data = callback_query.get('data', '')

    # Validasi otorisasi chat_id admin
    if allowed_chat and not is_admin_chat_authorized(chat_id, allowed_chat):
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
                "🦅 <b>BOT 3 : PANEL & FITUR ADMIN GARUDATEL v2</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Selamat datang di Panel Cepat Telegram Admin (Bot 3).\n"
                "Pilih salah satu tombol di bawah atau gunakan pintasan:\n"
                "• <code>/produkgagal</code> — Analisa Produk & Seller Sering Gagal\n"
                "• <code>/analisaseller</code> — Rapor Seller Paling Sering Gagal\n"
                "• <code>/toko</code> | <code>/saldo</code> | <code>/topusers</code> | <code>/otp</code>"
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
                    t_seller = getattr(t, 'resolved_seller_name', None) or t.seller_name or '-'
                    t_comp = t.format_digiflazz_complaint('gagal') if hasattr(t, 'format_digiflazz_complaint') else ''
                    comp_row = f"• 📣 Komplain: <code>{t_comp}</code>\n" if t_comp and t.sku_code not in ['DEPOSIT_SALDO', 'DEPOSIT_MANUAL', 'MANUAL_DEDUCTION'] else ""
                    lines.append(
                        f"<b>{idx}. {t.product_name or 'Produk'}</b>\n"
                        f"• Ref: <code>{t.ref_id}</code> | Rp {t.amount:,.0f}\n"
                        f"• Tujuan: <code>{t.target_number or '-'}</code> | {t_time} WIB\n"
                        f"• 🏪 Seller: <b>{t_seller}</b>\n"
                        f"• ⚠️ Alasan: <i>{reason}</i>\n"
                        f"{comp_row}"
                    )
                lines.append("━━━━━━━━━━━━━━━━━━━━━━")
                text = "\n".join(lines)

            markup = {
                "inline_keyboard": [
                    [{"text": "🚨 Analisa Produk & Seller Sering Gagal", "callback_data": "cmd_failed_products"}],
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
                    r_seller = getattr(r, 'resolved_seller_name', None) or r.seller_name or '-'
                    seller_part = f" | 🏪 {r_seller}" if r_seller and r_seller != '-' else ""
                    lines.append(
                        f"{icon} <b>{r.product_name or 'Produk'}</b> ({r.status})\n"
                        f"• Ref: <code>{r.ref_id}</code> | Rp {r.amount:,.0f}{seller_part}\n"
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
                from app.extensions import db
                from app.models.user import User
                total_user_balance = db.session.query(db.func.sum(User.balance)).scalar() or 0.0
                total_users = User.query.count()

                diff = float(bal) - float(total_user_balance)
                if diff > 0:
                    diff_str = f"+Rp {diff:,.0f} (Surplus / Aman ✅)"
                elif diff < 0:
                    diff_str = f"-Rp {abs(diff):,.0f} (Defisit / Kurang ⚠️)"
                else:
                    diff_str = f"Rp 0 (Seimbang / Pas)"

                text = (
                    "💰 <b>INFORMASI SALDO DIGIFLAZZ</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Saldo Digiflazz:</b> <code>Rp {bal:,.0f}</code>\n"
                    f"• <b>Total Saldo User:</b> <code>Rp {total_user_balance:,.0f}</code> ({total_users} user)\n"
                    f"• <b>Selisih (Digiflazz - User):</b> <code>{diff_str}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Status API:</b> Terhubung Normal (200 OK)\n"
                    f"• <b>Update:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}"
                )
            else:
                text = f"🚨 <b>GAGAL CEK SALDO:</b>\n{msg}"
            _edit_message(token, chat_id, message_id, text, get_back_button())

        elif data == 'cmd_top_users':
            rep_text, rep_kb = render_top_users_report()
            _edit_message(token, chat_id, message_id, rep_text, rep_kb)

        # ==========================================================
        # FITUR LAPORAN ANALISA PRODUK & SELLER SERING GAGAL
        # ==========================================================
        elif data == 'cmd_failed_products':
            rep_text, rep_kb = render_failed_products_report(
                period='30d', page=1, per_page=5, filter_mode='active', auto_fallback=True
            )
            _edit_message(token, chat_id, message_id, rep_text, rep_kb)

        elif data.startswith('fp_list:'):
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            filter_mode = parts[3] if len(parts) > 3 else 'active'
            rep_text, rep_kb = render_failed_products_report(
                period=period, page=page, per_page=5, filter_mode=filter_mode, auto_fallback=False
            )
            _edit_message(token, chat_id, message_id, rep_text, rep_kb)

        elif data.startswith('fp_view:'):
            parts = data.split(':', 2)
            period = parts[1] if len(parts) > 1 else '30d'
            raw_sku = parts[2] if len(parts) > 2 else ''
            det_text, det_kb = render_failed_product_detail(raw_sku, period=period)
            _edit_message(token, chat_id, message_id, det_text, det_kb)

        elif data.startswith('fp_tog:'):
            from app.extensions import db, cache
            parts = data.split(':', 2)
            period = parts[1] if len(parts) > 1 else '30d'
            raw_sku = parts[2] if len(parts) > 2 else ''
            sku_clean = _resolve_fp_sku(raw_sku)
            prod = Product.query.filter_by(sku_code=sku_clean).first()
            if not prod:
                _edit_message(token, chat_id, message_id, f"❌ Produk dengan SKU <code>{sku_clean}</code> tidak ditemukan di katalog database!", get_back_button())
                return
            prod.is_active = not bool(prod.is_active)
            # Jika dinonaktifkan: aktifkan gembok admin (is_admin_disabled=True) agar tidak tertimpa Auto-Sync
            # Jika diaktifkan kembali: buka gembok admin (is_admin_disabled=False)
            prod.is_admin_disabled = not bool(prod.is_active)
            db.session.commit()
            try:
                cache.clear()
            except Exception:
                pass
            banner = (
                f"✅ <b>STATUS PRODUK BERHASIL DIPERBARUI!</b>\n"
                f"Produk <b>{prod.name}</b> (<code>{prod.sku_code}</code>) kini berstatus: "
                f"{'🟢 <b>AKTIF (Ditampilkan di Web)</b> — <i>Gembok Admin Dibuka</i>' if prod.is_active else '🔴 <b>NONAKTIF (Disembunyikan dari Web)</b> — <i>Digembok dari Auto-Sync Digiflazz</i>'}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            det_text, det_kb = render_failed_product_detail(sku_clean, period=period)
            _edit_message(token, chat_id, message_id, banner + det_text, det_kb)

        elif data.startswith('fp_sync:'):
            from app.extensions import db, cache
            from app.services.digiflazz import get_price_list, check_transaction_status, apply_digiflazz_seller_metadata
            parts = data.split(':', 2)
            period = parts[1] if len(parts) > 1 else '30d'
            raw_sku = parts[2] if len(parts) > 2 else ''
            sku_clean = _resolve_fp_sku(raw_sku)

            _edit_message(token, chat_id, message_id, f"⏳ <i>Sedang menarik data terbaru Seller, Harga Modal, dan Kontak CS untuk SKU <code>{sku_clean}</code> dari Digiflazz...</i>", None)

            prod = Product.query.filter_by(sku_code=sku_clean).first()
            sync_notes = []

            ok_pl, pl_items, pl_msg = get_price_list('prepaid', code=sku_clean)
            matched_pl = None
            if ok_pl and isinstance(pl_items, list):
                for item in pl_items:
                    if str(item.get('buyer_sku_code', '')).strip().upper() == sku_clean.upper():
                        matched_pl = item
                        break

            if matched_pl:
                new_seller = clean_str(matched_pl.get('seller_name'))
                new_price = float(matched_pl.get('price') or 0.0)
                b_stat = bool(matched_pl.get('buyer_product_status', True))
                s_stat = bool(matched_pl.get('seller_product_status', True))
                if prod:
                    if new_seller:
                        prod.seller_name = new_seller
                    if new_price > 0:
                        prod.base_price = new_price
                    # Saat admin sengaja klik sync untuk mengaktifkan seller baru, lepas gembok admin
                    prod.is_admin_disabled = False
                    prod.is_active = (b_stat and s_stat)
                    db.session.commit()
                    try:
                        cache.clear()
                    except Exception:
                        pass
                sync_notes.append(f"• Seller Digiflazz Terbaru: <b>{new_seller or '-'}</b> (Modal: {format_rupiah(new_price)})")

            # Tarik juga metadata kontak tele/wa dari transaksi gagal terakhir jika ada
            last_fail = Transaction.query.filter(
                Transaction.sku_code == sku_clean,
                Transaction.status.in_(FAILED_STATUS_LIST)
            ).order_by(Transaction.id.desc()).first()

            if last_fail:
                try:
                    ok_st, st_data, _ = check_transaction_status(last_fail.sku_code, last_fail.target_number, last_fail.ref_id)
                    if isinstance(st_data, dict) and st_data:
                        apply_digiflazz_seller_metadata(last_fail, st_data, product=prod)
                        db.session.commit()
                        if last_fail.seller_tele or last_fail.seller_wa:
                            sync_notes.append(f"• Kontak CS Seller: ✈️ <code>{last_fail.seller_tele or '-'}</code> | 📱 <code>{last_fail.seller_wa or '-'}</code>")
                except Exception:
                    pass

            if not sync_notes:
                sync_notes.append("• Data lokal telah disinkronkan (API Digiflazz sedang cooldown / tidak ada perubahan baru).")

            banner = (
                "✅ <b>SINKRONISASI SKU & SELLER SELESAI!</b>\n"
                + "\n".join(sync_notes)
                + "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            det_text, det_kb = render_failed_product_detail(sku_clean, period=period)
            _edit_message(token, chat_id, message_id, banner + det_text, det_kb)

        elif data.startswith('fp_wa:'):
            from app.services.digiflazz import build_seller_complaint_info
            from app.wa_helper import kirim_wa
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            trx_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            trx = Transaction.query.get(trx_id)
            if not trx:
                _edit_message(token, chat_id, message_id, "❌ Data transaksi gagal tidak ditemukan!", get_back_button())
                return

            c_info = build_seller_complaint_info(trx, mode='gagal')
            wa_num = c_info.get('seller_wa_clean')
            comp_txt = c_info.get('complaint_gagal') or trx.format_digiflazz_complaint('gagal')

            if not wa_num:
                banner = (
                    "⚠️ <b>NOMOR WHATSAPP SELLER BELUM TERSEDIA!</b>\n"
                    f"Seller <b>{c_info.get('seller_name')}</b> belum mencantumkan nomor WA di respon API Digiflazz.\n"
                    f"Silakan gunakan tombol <b>Chat Tele Seller</b> atau salin format komplain berikut:\n"
                    f"<code>{comp_txt}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            else:
                sent = kirim_wa(wa_num, comp_txt)
                if sent:
                    banner = (
                        f"✅ <b>KOMPLAIN GAGAL TERKIRIM KE WA SELLER!</b>\n"
                        f"• 🏪 Seller: <b>{c_info.get('seller_name')}</b> (<code>{wa_num}</code>)\n"
                        f"• 💬 Pesan: <code>{comp_txt}</code>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    )
                else:
                    banner = (
                        f"⚠️ <b>Bot WA lokal belum terhubung, silakan klik tombol WA Seller Manual di bawah.</b>\n"
                        f"• Nomor WA Seller: <code>{wa_num}</code>\n"
                        f"• Format Komplain: <code>{comp_txt}</code>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    )
            det_text, det_kb = render_failed_product_detail(trx.sku_code, period=period)
            _edit_message(token, chat_id, message_id, banner + det_text, det_kb)

        elif data.startswith('fp_delask:'):
            parts = data.split(':', 2)
            period = parts[1] if len(parts) > 1 else '30d'
            raw_sku = parts[2] if len(parts) > 2 else ''
            sku_clean = _resolve_fp_sku(raw_sku)
            prod = Product.query.filter_by(sku_code=sku_clean).first()
            if not prod:
                _edit_message(token, chat_id, message_id, f"❌ Produk <code>{sku_clean}</code> sudah tidak ada di katalog.", get_back_button())
                return

            cb_sku = sku_clean[:28]
            text = (
                "⚠️ <b>KONFIRMASI HAPUS PRODUK DARI KATALOG</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 <b>Nama Produk:</b> <b>{prod.name}</b>\n"
                f"🔖 <b>Kode SKU:</b> <code>{prod.sku_code}</code>\n"
                f"🏪 <b>Seller:</b> {prod.seller_name or '-'}\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Apakah Anda yakin ingin <b>MENGHAPUS</b> produk ini dari katalog database?\n"
                "<i>(Riwayat transaksi lama tetap aman tersimpan di laporan analisa, namun produk tidak akan tampil lagi di katalog belanja).</i>"
            )
            kb = {
                "inline_keyboard": [
                    [
                        {"text": "🗑️ YA, HAPUS SEKARANG", "callback_data": f"fp_delok:{period}:{cb_sku}"},
                        {"text": "❌ BATAL", "callback_data": f"fp_view:{period}:{cb_sku}"}
                    ]
                ]
            }
            _edit_message(token, chat_id, message_id, text, kb)

        elif data.startswith('fp_delok:'):
            from app.extensions import db, cache
            parts = data.split(':', 2)
            period = parts[1] if len(parts) > 1 else '30d'
            raw_sku = parts[2] if len(parts) > 2 else ''
            sku_clean = _resolve_fp_sku(raw_sku)
            prod = Product.query.filter_by(sku_code=sku_clean).first()
            if prod:
                del_name = prod.name
                db.session.delete(prod)
                db.session.commit()
                try:
                    cache.clear()
                except Exception:
                    pass
                banner = (
                    f"🗑️ <b>PRODUK BERHASIL DIHAPUS DARI KATALOG!</b>\n"
                    f"Produk <b>{del_name}</b> (<code>{sku_clean}</code>) telah dihapus dari katalog website & kasir POS.\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            else:
                banner = f"ℹ️ Produk <code>{sku_clean}</code> sudah dihapus sebelumnya.\n\n"

            rep_text, rep_kb = render_failed_products_report(period=period, page=1, per_page=5, filter_mode='active')
            _edit_message(token, chat_id, message_id, banner + rep_text, rep_kb)

        elif data.startswith('fp_offcrit:'):
            from app.extensions import db, cache
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            analytics = get_failed_products_analytics(period=period, filter_mode='all')
            disabled_names = []
            for item in analytics['items']:
                if item['severity'] == 'CRITICAL' and item['product_obj'] and item['product_obj'].is_active:
                    item['product_obj'].is_active = False
                    item['product_obj'].is_admin_disabled = True
                    disabled_names.append(f"{item['product_name']} ({item['sku_code']})")
            if disabled_names:
                db.session.commit()
                try:
                    cache.clear()
                except Exception:
                    pass
                banner = (
                    f"🛑 <b>{len(disabled_names)} PRODUK KRITIS BERHASIL DINONAKTIFKAN!</b>\n"
                    + "\n".join(f"• 🔴 {n}" for n in disabled_names[:6])
                    + "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            else:
                banner = "ℹ️ <b>Seluruh produk berstatus Kritis sudah dalam keadaan Nonaktif.</b>\n\n"

            rep_text, rep_kb = render_failed_products_report(period=period, page=1, per_page=5, filter_mode='active')
            _edit_message(token, chat_id, message_id, banner + rep_text, rep_kb)

        elif data.startswith('fp_sellers:'):
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            filter_mode = parts[3] if len(parts) > 3 else 'active'
            s_text, s_kb = render_failed_sellers_report(period=period, page=page, per_page=5, filter_mode=filter_mode)
            _edit_message(token, chat_id, message_id, s_text, s_kb)

        elif data.startswith('fp_slroff:'):
            from app.extensions import db, cache
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            sample_trx_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            sample_trx = Transaction.query.get(sample_trx_id)
            target_seller = None
            if sample_trx:
                target_seller = getattr(sample_trx, 'resolved_seller_name', None) or sample_trx.seller_name

            disabled_count = 0
            disabled_names = []
            if target_seller:
                # PENTING: Hanya menonaktifkan produk-produk dari seller ini yang TERCATAT GAGAL dan masih AKTIF!
                # Produk normal seller lainnya TIDAK AKAN disentuh!
                analytics = get_failed_products_analytics(period=period, filter_mode='all')
                for item in analytics['items']:
                    if item['seller_name'].upper() == target_seller.strip().upper():
                        if item['product_obj'] and item['product_obj'].is_active:
                            item['product_obj'].is_active = False
                            item['product_obj'].is_admin_disabled = True
                            disabled_count += 1
                            disabled_names.append(f"{item['product_name']} ({item['sku_code']})")

                if disabled_count > 0:
                    db.session.commit()
                    try:
                        cache.clear()
                    except Exception:
                        pass
                    banner = (
                        f"🛑 <b>{disabled_count} PRODUK GAGAL SELLER {target_seller.upper()} DINONAKTIFKAN!</b>\n"
                        f"• Produk bermasalah berhasil dinonaktifkan dari katalog web & digembok dari Auto-Sync.\n"
                        f"• <i>Produk normal milik seller ini tetap aman & aktif.</i>\n"
                        + "\n".join(f"• 🔴 {n}" for n in disabled_names[:5])
                        + "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    )
                else:
                    banner = f"ℹ️ <b>Semua produk gagal dari seller {target_seller.upper()} sudah dalam keadaan nonaktif.</b>\n\n"
            else:
                banner = "⚠️ <b>Identitas Seller tidak ditemukan.</b>\n\n"

            # Render ulang seller report dengan filter_mode='active' sehingga seller yang sudah beres langsung hilang dari antrean (Clean View)!
            s_text, s_kb = render_failed_sellers_report(period=period, page=1, per_page=5, filter_mode='active')
            _edit_message(token, chat_id, message_id, banner + s_text, s_kb)

        elif data.startswith('fp_slrdis:'):
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            sample_trx_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
            dis_text, dis_kb = render_disabled_seller_products_report(sample_trx_id, period=period, page=page, per_page=5)
            _edit_message(token, chat_id, message_id, dis_text, dis_kb)

        elif data.startswith('fp_slron:'):
            from app.extensions import db, cache
            parts = data.split(':')
            period = parts[1] if len(parts) > 1 else '30d'
            sample_trx_id = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
            sample_trx = Transaction.query.get(sample_trx_id)
            target_seller = None
            if sample_trx:
                target_seller = getattr(sample_trx, 'resolved_seller_name', None) or sample_trx.seller_name

            enabled_count = 0
            enabled_names = []
            if target_seller:
                # Cari semua produk yang berstatus nonaktif dari seller ini di katalog
                seller_prods = Product.query.filter(
                    db.func.upper(Product.seller_name) == target_seller.strip().upper(),
                    Product.is_active == False
                ).all()
                analytics = get_failed_products_analytics(period=period, filter_mode='all')
                prods_to_enable = set(seller_prods)
                for item in analytics['items']:
                    if item['seller_name'].upper() == target_seller.strip().upper() and item['product_obj'] and not item['product_obj'].is_active:
                        prods_to_enable.add(item['product_obj'])

                for p in prods_to_enable:
                    p.is_active = True
                    p.is_admin_disabled = False
                    enabled_count += 1
                    enabled_names.append(f"{p.name} ({p.sku_code})")

                if enabled_count > 0:
                    db.session.commit()
                    try:
                        cache.clear()
                    except Exception:
                        pass
                    banner = (
                        f"🟢 <b>{enabled_count} PRODUK SELLER {target_seller.upper()} BERHASIL DIAKTIFKAN!</b>\n"
                        f"• Produk kini kembali tayang di web & kasir POS.\n"
                        f"• Gembok Admin telah dibuka sehingga dapat mengikuti status seller.\n"
                        + "\n".join(f"• 🟢 {n}" for n in enabled_names[:5])
                        + "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    )
                else:
                    banner = f"ℹ️ <b>Seluruh produk seller {target_seller.upper()} sudah dalam keadaan aktif.</b>\n\n"
            else:
                banner = "⚠️ <b>Identitas Seller tidak ditemukan.</b>\n\n"

            # Tampilkan kembali laporan seller
            s_text, s_kb = render_failed_sellers_report(period=period, page=1, per_page=5, filter_mode='all')
            _edit_message(token, chat_id, message_id, banner + s_text, s_kb)

        # ==========================================================
        # FITUR KATALOG PRODUK NONAKTIF PER SELLER & SELEKSI AKTIVASI
        # ==========================================================
        elif data == 'cmd_disabled_catalog':
            c_text, c_kb = render_disabled_catalog_sellers_menu(page=1, per_page=6)
            _edit_message(token, chat_id, message_id, c_text, c_kb)

        elif data.startswith('dis_menu:'):
            parts = data.split(':')
            page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
            c_text, c_kb = render_disabled_catalog_sellers_menu(page=page, per_page=6)
            _edit_message(token, chat_id, message_id, c_text, c_kb)

        elif data.startswith('dis_slr:'):
            parts = data.split(':')
            s_hash = parts[1] if len(parts) > 1 else ''
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            p_text, p_kb = render_disabled_catalog_seller_products(seller_hash=s_hash, page=page, per_page=5)
            _edit_message(token, chat_id, message_id, p_text, p_kb)

        elif data.startswith('dis_act_one:'):
            from app.extensions import db, cache
            parts = data.split(':')
            prod_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            s_hash = parts[2] if len(parts) > 2 else ''
            prod = Product.query.get(prod_id)
            if not prod:
                _edit_message(token, chat_id, message_id, "❌ Produk tidak ditemukan di database!", get_back_button())
                return
            prod.is_active = True
            prod.is_admin_disabled = False  # Buka gembok admin
            db.session.commit()
            try:
                cache.clear()
            except Exception:
                pass
            banner = (
                f"✅ <b>PRODUK BERHASIL DIAKTIFKAN KEMBALI!</b>\n"
                f"Produk <b>{prod.name}</b> (<code>{prod.sku_code}</code>) kini berstatus:\n"
                f"🟢 <b>AKTIF</b> — <i>Gembok Admin telah dibuka & tayang di web!</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            # Re-render halaman produk seller ini (Clean View / Inbox Zero: produk yang baru diaktifkan langsung lenyap dari daftar nonaktif)
            p_text, p_kb = render_disabled_catalog_seller_products(seller_hash=s_hash, page=1, per_page=5)
            _edit_message(token, chat_id, message_id, banner + p_text, p_kb)

        elif data.startswith('dis_act_all:'):
            from app.extensions import db, cache
            parts = data.split(':')
            s_hash = parts[1] if len(parts) > 1 else ''
            sellers = get_disabled_sellers_list()
            target_seller = next((s for s in sellers if s['hash'] == s_hash), None)
            if not target_seller:
                _edit_message(token, chat_id, message_id, "ℹ️ Seluruh produk milik seller ini sudah aktif.", get_back_button())
                return
            enabled_count = 0
            enabled_names = []
            for p in target_seller['products']:
                p.is_active = True
                p.is_admin_disabled = False
                enabled_count += 1
                enabled_names.append(f"{p.name} ({p.sku_code})")
            if enabled_count > 0:
                db.session.commit()
                try:
                    cache.clear()
                except Exception:
                    pass
                banner = (
                    f"✅ <b>{enabled_count} PRODUK SELLER {target_seller['display_name'].upper()} BERHASIL DIAKTIFKAN!</b>\n"
                    f"Semua produk milik seller ini telah dibuka gemboknya dan kembali aktif di katalog website.\n"
                    + "\n".join(f"• 🟢 {n}" for n in enabled_names[:5])
                    + "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            else:
                banner = f"ℹ️ Semua produk milik seller {target_seller['display_name']} sudah aktif.\n\n"
            # Kembali ke menu daftar seller (Clean View: seller ini langsung hilang dari daftar seller nonaktif jika 0 produk)
            c_text, c_kb = render_disabled_catalog_sellers_menu(page=1, per_page=6)
            _edit_message(token, chat_id, message_id, banner + c_text, c_kb)

        # ==========================================================
        # FITUR PENCARIAN & AKTIVASI PRODUK NONAKTIF
        # ==========================================================
        elif data == 'dis_search_prompt':
            _ADMIN_SEARCH_STATE[str(chat_id)] = True
            prompt_text = (
                "🔍 <b>PENCARIAN PRODUK NONAKTIF</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "Ketik nama produk, brand, kategori, atau kode SKU yang ingin Anda cari:\n"
                "(Contoh: <code>telkomsel 10</code>, <code>mobile legends</code>, <code>dana</code>, <code>bca</code>, atau <code>pln</code>)\n\n"
                "💡 <i>Langsung ketik dan kirim pesan di chat ini untuk mencari, atau ketik <code>/batal</code> untuk kembali.</i>"
            )
            prompt_kb = {
                "inline_keyboard": [
                    [{"text": "« Kembali ke Katalog Seller", "callback_data": "cmd_disabled_catalog"}],
                    [{"text": "🏠 Menu Utama", "callback_data": "cmd_menu"}]
                ]
            }
            _edit_message(token, chat_id, message_id, prompt_text, prompt_kb)

        elif data.startswith('dis_srch_pg:'):
            parts = data.split(':')
            kw_hash = parts[1] if len(parts) > 1 else ''
            page = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
            kw = _SEARCH_KEYWORDS_CACHE.get(kw_hash, '')
            if not kw:
                _edit_message(token, chat_id, message_id, "⚠️ Sesi pencarian kedaluwarsa. Silakan cari ulang:", {
                    "inline_keyboard": [
                        [{"text": "🔍 Cari Produk Nonaktif", "callback_data": "dis_search_prompt"}],
                        [{"text": "« Kembali ke Katalog Seller", "callback_data": "cmd_disabled_catalog"}]
                    ]
                })
                return
            s_text, s_kb = render_disabled_search_results(keyword=kw, page=page, per_page=5)
            _edit_message(token, chat_id, message_id, s_text, s_kb)

        elif data.startswith('dis_act_srch_one:'):
            from app.extensions import db, cache
            parts = data.split(':')
            prod_id = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
            kw_hash = parts[2] if len(parts) > 2 else ''
            page = int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 1
            kw = _SEARCH_KEYWORDS_CACHE.get(kw_hash, '')
            prod = Product.query.get(prod_id)
            if not prod:
                _edit_message(token, chat_id, message_id, "❌ Produk tidak ditemukan di database!", get_back_button())
                return
            prod.is_active = True
            prod.is_admin_disabled = False
            db.session.commit()
            try:
                cache.clear()
            except Exception:
                pass
            banner = (
                f"✅ <b>PRODUK BERHASIL DIAKTIFKAN KEMBALI!</b>\n"
                f"Produk <b>{prod.name}</b> (<code>{prod.sku_code}</code>) kini berstatus:\n"
                f"🟢 <b>AKTIF</b> — <i>Gembok Admin telah dibuka & tayang di web!</i>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            s_text, s_kb = render_disabled_search_results(keyword=kw, page=page, per_page=5)
            _edit_message(token, chat_id, message_id, banner + s_text, s_kb)

        elif data.startswith('dis_act_srch_all:'):
            from app.extensions import db, cache
            from sqlalchemy import or_, and_
            parts = data.split(':')
            kw_hash = parts[1] if len(parts) > 1 else ''
            kw = _SEARCH_KEYWORDS_CACHE.get(kw_hash, '')
            if not kw:
                _edit_message(token, chat_id, message_id, "⚠️ Sesi pencarian kedaluwarsa. Silakan cari ulang:", {
                    "inline_keyboard": [
                        [{"text": "🔍 Cari Produk Nonaktif", "callback_data": "dis_search_prompt"}],
                        [{"text": "« Kembali ke Katalog Seller", "callback_data": "cmd_disabled_catalog"}]
                    ]
                })
                return
            terms = kw.split()
            conds = []
            for term in terms:
                t_pat = f"%{term}%"
                conds.append(or_(
                    Product.name.ilike(t_pat),
                    Product.sku_code.ilike(t_pat),
                    Product.brand.ilike(t_pat),
                    Product.category.ilike(t_pat),
                    Product.seller_name.ilike(t_pat)
                ))
            status_filter = or_(Product.is_active == False, Product.is_admin_disabled == True)
            matching_prods = Product.query.filter(and_(status_filter, *conds)).all()
            enabled_count = 0
            enabled_names = []
            for p in matching_prods:
                p.is_active = True
                p.is_admin_disabled = False
                enabled_count += 1
                enabled_names.append(f"{p.name} ({p.sku_code})")
            if enabled_count > 0:
                db.session.commit()
                try:
                    cache.clear()
                except Exception:
                    pass
                banner = (
                    f"✅ <b>{enabled_count} PRODUK HASIL PENCARIAN '{kw.upper()}' BERHASIL DIAKTIFKAN!</b>\n"
                    f"Semua produk yang cocok telah dibuka gemboknya dan kembali aktif di katalog website.\n"
                    + "\n".join(f"• 🟢 {n}" for n in enabled_names[:5])
                    + "\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                )
            else:
                banner = f"ℹ️ Semua produk hasil pencarian '{kw}' sudah aktif.\n\n"
            s_text, s_kb = render_disabled_search_results(keyword=kw, page=1, per_page=5)
            _edit_message(token, chat_id, message_id, banner + s_text, s_kb)

        elif data == 'cmd_tarik_deposit':
            dep_text, dep_kb = render_tarik_deposit_menu()
            _edit_message(token, chat_id, message_id, dep_text, dep_kb)

        elif data == 'depo_new_menu':
            dep_text, dep_kb = render_tarik_deposit_methods_menu()
            _edit_message(token, chat_id, message_id, dep_text, dep_kb)

        elif data.startswith('depo_method_'):
            method = data.replace('depo_method_', '')
            amt_text, amt_kb = render_tarik_deposit_amounts(method)
            _edit_message(token, chat_id, message_id, amt_text, amt_kb)

        elif data.startswith('depo_exec_'):
            parts = data.split('_')
            try:
                method = parts[2]
                amt = float(parts[3])
            except Exception:
                _edit_message(token, chat_id, message_id, "❌ Parameter tiket deposit tidak valid!", get_back_button())
                return
            execute_tarik_deposit(token, chat_id, message_id, method, amt, is_edit=True)

        elif data.startswith('depo_cancel_'):
            try:
                ticket_id = int(data.replace('depo_cancel_', ''))
            except Exception:
                _edit_message(token, chat_id, message_id, "❌ ID Tiket tidak valid!", get_back_button())
                return
            cancel_tarik_deposit(token, chat_id, message_id, ticket_id, is_edit=True)

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
                    p_seller = getattr(p, 'resolved_seller_name', None) or p.seller_name or '-'
                    p_comp = p.format_digiflazz_complaint('pending') if hasattr(p, 'format_digiflazz_complaint') else ''
                    lines.append(
                        f"• <code>{p.ref_id}</code> | Rp {p.amount:,.0f}\n"
                        f"  Produk: {p.product_name or '-'} (🏪 <b>{p_seller}</b>)\n"
                        f"  Tujuan: <code>{p.target_number or '-'}</code> | {t_time} WIB\n"
                        f"  📣 Komplain: <code>{p_comp}</code>"
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
            _edit_message(token, chat_id, message_id, "⏳ <i>Sedang menarik data produk dari Digiflazz di background... Anda akan menerima pesan notifikasi saat selesai.</i>", get_back_button())
            from app.extensions import db
            try:
                # Pastikan semua produk yang saat ini berstatus nonaktif terkunci agar tidak tertimpa sync Digiflazz
                Product.query.filter(Product.is_active == False, Product.is_admin_disabled != True).update({'is_admin_disabled': True})
                db.session.commit()
            except Exception:
                pass

            def async_sync_runner():
                with app.app_context():
                    ok, msg = sync_products(notify_admin_bot=False)
                    res_icon = "✅" if ok else "🚨"
                    text = f"{res_icon} <b>HASIL SINKRONISASI DIGIFLAZZ:</b>\n\n{msg}"
                    _send_message(token, chat_id, text, reply_markup=get_back_button())

            threading.Thread(target=async_sync_runner, daemon=True).start()

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
                with open(backup_path, 'rb') as f:
                    call_telegram_api(
                        'post',
                        f"bot{token}/sendDocument",
                        files={'document': (display_name, f, 'application/zip')},
                        data={'chat_id': chat_id, 'caption': caption, 'parse_mode': 'HTML'},
                        timeout=90
                    )
                
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

        # ==========================================================
        # 1-CLICK AUTO-PROVISIONING MITRA WEB POS (TERIMA / TOLAK)
        # ==========================================================
        elif data.startswith('prov_acc_'):
            try:
                prov_id = int(data.replace('prov_acc_', ''))
                from app.services.merchant_service import approve_provision_request
                prov, err = approve_provision_request(prov_id)
                if err or not prov:
                    _edit_message(token, chat_id, message_id, f"❌ <b>Gagal menyetujui permohonan:</b> {err}", None)
                else:
                    text = (
                        "✅ <b>MITRA PPOB DISETUJUI & TERHUBUNG OTOMATIS!</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🏪 <b>Nama Toko   :</b> {prov.store_name}\n"
                        f"👤 <b>Pemilik     :</b> {prov.owner_name}\n"
                        f"📱 <b>No. WA      :</b> <code>{prov.phone}</code>\n"
                        f"🆔 <b>ID Tenant   :</b> <code>{prov.tenant_id or '-'}</code>\n"
                        f"🔑 <b>Merchant ID :</b> <code>{prov.merchant_id}</code>\n"
                        f"⏰ <b>Disetujui   :</b> {format_wib(fmt='%d %b %Y, %H:%M WIB')}\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🟢 <i>API Key & Secret Key telah di-inject otomatis ke Web POS user (Mode LIVE).</i>"
                    )
                    _edit_message(token, chat_id, message_id, text, None)
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"❌ Error: {e}", None)

        elif data.startswith('prov_rej_'):
            try:
                prov_id = int(data.replace('prov_rej_', ''))
                from app.services.merchant_service import reject_provision_request
                prov, err = reject_provision_request(prov_id)
                if err or not prov:
                    _edit_message(token, chat_id, message_id, f"❌ <b>Gagal menolak permohonan:</b> {err}", None)
                else:
                    text = (
                        "❌ <b>PERMOHONAN MITRA PPOB DITOLAK</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🏪 <b>Nama Toko   :</b> {prov.store_name}\n"
                        f"👤 <b>Pemilik     :</b> {prov.owner_name}\n"
                        f"📱 <b>No. WA      :</b> <code>{prov.phone}</code>\n"
                        f"🆔 <b>ID Tenant   :</b> <code>{prov.tenant_id or '-'}</code>\n"
                        f"⏰ <b>Ditolak     :</b> {format_wib(fmt='%d %b %Y, %H:%M WIB')}\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n"
                        "🔴 <i>Status penolakan telah dikirimkan ke layar Web POS user.</i>"
                    )
                    _edit_message(token, chat_id, message_id, text, None)
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"❌ Error: {e}", None)

        elif data == 'cmd_pos_panel':
            try:
                from app.models.merchant import MerchantApiKey, MerchantProvisionRequest, ensure_merchant_provision_table
                from app.extensions import db
                ensure_merchant_provision_table()

                merchants = MerchantApiKey.query.order_by(MerchantApiKey.id.desc()).all()
                active_mch = [m for m in merchants if m.is_active]
                pending_prov = MerchantProvisionRequest.query.filter_by(status='PENDING').count()
                low_bal_mch = [m for m in active_mch if m.user and float(m.user.balance or 0) < 50000]

                wib_now = get_wib_now()
                today_start_wib = wib_now.replace(hour=0, minute=0, second=0, microsecond=0)
                today_start = today_start_wib.astimezone(timezone.utc).replace(tzinfo=None)

                pos_today_cnt = Transaction.query.filter(
                    Transaction.payment_method == 'API_GATEWAY',
                    Transaction.created_at >= today_start,
                    Transaction.status == 'SUCCESS'
                ).count()
                pos_today_rev = db.session.query(db.func.sum(Transaction.amount)).filter(
                    Transaction.payment_method == 'API_GATEWAY',
                    Transaction.created_at >= today_start,
                    Transaction.status == 'SUCCESS'
                ).scalar() or 0.0

                store_lines = []
                for m in active_mch[:8]:
                    bal = float(m.user.balance or 0) if m.user else 0
                    warn = " ⚠️" if bal < 50000 else ""
                    store_lines.append(f"• <b>{m.name}</b> (<code>{m.merchant_id}</code>): Rp {bal:,.0f}{warn}")
                stores_summary = "\n".join(store_lines) if store_lines else "<i>Belum ada kasir POS aktif.</i>"

                text = (
                    "🖥️ <b>POS COMMAND CENTER (ipaypos.my.id)</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🏪 <b>Kasir POS Aktif :</b> {len(active_mch)} / {len(merchants)} Toko\n"
                    f"🔔 <b>Pengajuan Baru  :</b> {pending_prov} Menunggu Persetujuan\n"
                    f"⚠️ <b>Saldo &lt; Rp 50rb :</b> {len(low_bal_mch)} Toko\n"
                    f"📊 <b>Trx POS Hari Ini:</b> {pos_today_cnt} Sukses (Rp {pos_today_rev:,.0f})\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"<b>Daftar Kasir POS Aktif:</b>\n{stores_summary}\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    "💡 <b>Broadcast ke Layar Kasir via Telegram:</b>\n"
                    "Ketik: <code>/bcpos Judul | Isi Pesan</code>"
                )
                pos_kb = {
                    "inline_keyboard": [
                        [
                            {"text": f"🔔 Antrean Aktivasi ({pending_prov})", "callback_data": "pos_prov_pending"},
                            {"text": "🔄 Trx POS & Push SN", "callback_data": "pos_trx_list"}
                        ],
                        [
                            {"text": "« Kembali ke Menu Utama", "callback_data": "cmd_menu"}
                        ]
                    ]
                }
                _edit_message(token, chat_id, message_id, text, pos_kb)
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"❌ Error memuat Panel POS: {e}", get_back_button())

        elif data == 'pos_prov_pending':
            try:
                from app.models.merchant import MerchantProvisionRequest, ensure_merchant_provision_table
                ensure_merchant_provision_table()
                pendings = MerchantProvisionRequest.query.filter_by(status='PENDING').order_by(MerchantProvisionRequest.id.desc()).limit(5).all()
                if not pendings:
                    text = "✅ <b>Tidak ada antrean pengajuan aktivasi POS yang menunggu persetujuan.</b>"
                    kb = {"inline_keyboard": [[{"text": "« Kembali ke Panel POS", "callback_data": "cmd_pos_panel"}]]}
                    _edit_message(token, chat_id, message_id, text, kb)
                else:
                    lines = ["🔔 <b>ANTREAN PENGAJUAN AKTIVASI POS BARU</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
                    kb_rows = []
                    for p in pendings:
                        lines.append(
                            f"🏪 <b>{p.store_name}</b> ({p.owner_name})\n"
                            f"📱 WA: <code>{p.phone}</code> | Tenant: <code>{p.tenant_id or '-'}</code>"
                        )
                        kb_rows.append([
                            {"text": f"✅ Terima {p.store_name[:14]}", "callback_data": f"prov_acc_{p.id}"},
                            {"text": f"❌ Tolak", "callback_data": f"prov_rej_{p.id}"}
                        ])
                    kb_rows.append([{"text": "« Kembali ke Panel POS", "callback_data": "cmd_pos_panel"}])
                    _edit_message(token, chat_id, message_id, "\n\n".join(lines), {"inline_keyboard": kb_rows})
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"❌ Error: {e}", get_back_button())

        elif data == 'pos_trx_list':
            try:
                trxs = Transaction.query.filter(
                    Transaction.payment_method == 'API_GATEWAY',
                    ~Transaction.sku_code.in_(['DEPOSIT_SALDO', 'DEPOSIT_MANUAL'])
                ).order_by(Transaction.id.desc()).limit(6).all()
                if not trxs:
                    text = "📭 <b>Belum ada transaksi dari jalur Kasir POS.</b>"
                    kb = {"inline_keyboard": [[{"text": "« Kembali ke Panel POS", "callback_data": "cmd_pos_panel"}]]}
                    _edit_message(token, chat_id, message_id, text, kb)
                else:
                    lines = ["🔄 <b>6 TRANSAKSI POS TERAKHIR (KLIK UNTUK PUSH ULANG SN)</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
                    kb_rows = []
                    for t in trxs:
                        lines.append(
                            f"• <code>{t.ref_id}</code> [{t.status}]\n"
                            f"  {t.product_name} ➜ <code>{t.target_number}</code>\n"
                            f"  SN: <code>{(t.sn or '-')[:40]}</code>"
                        )
                        kb_rows.append([
                            {"text": f"🔄 Push SN {t.ref_id[-10:]} ({t.status})", "callback_data": f"pos_push_wh_{t.id}"}
                        ])
                    kb_rows.append([{"text": "« Kembali ke Panel POS", "callback_data": "cmd_pos_panel"}])
                    _edit_message(token, chat_id, message_id, "\n\n".join(lines), {"inline_keyboard": kb_rows})
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"❌ Error: {e}", get_back_button())

        elif data.startswith('pos_push_wh_'):
            try:
                trx_id = int(data.replace('pos_push_wh_', ''))
                from app.models.merchant import MerchantApiKey
                from app.services.merchant_service import dispatch_merchant_webhook
                from app.routes.transaction import sync_single_transaction

                trx = Transaction.query.get(trx_id)
                if not trx:
                    _edit_message(token, chat_id, message_id, "❌ Transaksi tidak ditemukan.", get_back_button())
                    return
                if trx.status in ['PENDING', 'PROCESSING', 'PROSES']:
                    try:
                        sync_single_transaction(trx)
                    except Exception:
                        pass

                mch = None
                if trx.provider_ref:
                    mch = MerchantApiKey.query.filter_by(merchant_id=trx.provider_ref).first()
                if not mch and trx.user_id:
                    mch = MerchantApiKey.query.filter_by(user_id=trx.user_id).first()

                if not mch or not mch.webhook_url:
                    msg_res = f"⚠️ Transaksi <code>{trx.ref_id}</code> berstatus <b>{trx.status}</b>, namun toko belum mengatur URL Webhook."
                else:
                    ok, code, resp_txt = dispatch_merchant_webhook(mch, {
                        "ref_id": trx.ref_id,
                        "status": (trx.status or 'PENDING').lower(),
                        "sn": trx.sn or "",
                        "sku_code": trx.sku_code or "",
                        "price": float(trx.amount or 0.0)
                    }, sync=True)
                    if ok:
                        msg_res = f"✅ <b>Push Ulang Webhook Berhasil!</b>\nRef: <code>{trx.ref_id}</code>\nStatus: <b>{trx.status}</b>\nSN: <code>{trx.sn or '-'}</code>\nRespon POS: HTTP {code}"
                    else:
                        msg_res = f"❌ <b>Gagal Push Webhook ke POS:</b>\n{resp_txt or f'HTTP {code}'}"

                kb = {"inline_keyboard": [[{"text": "« Kembali ke Trx POS", "callback_data": "pos_trx_list"}]]}
                _edit_message(token, chat_id, message_id, msg_res, kb)
            except Exception as e:
                _edit_message(token, chat_id, message_id, f"❌ Error: {e}", get_back_button())


def handle_admin_message(app, message):
    """
    Memproses perintah teks dari Admin di Bot 3 (seperti /start, /menu, /otp <nomor>, /bcpos, nomor WA pairing).
    """
    token, allowed_chat = get_bot_admin_credentials()
    if not token:
        token, allowed_chat = get_bot_notif_credentials()
    if not token:
        return

    chat_id = str(message.get('chat', {}).get('id', ''))
    text = message.get('text', '').strip()

    # Validasi otorisasi chat_id admin
    if allowed_chat and not is_admin_chat_authorized(chat_id, allowed_chat):
        _send_message(token, chat_id, "⛔ <b>Akses Ditolak!</b>\nAkun Telegram Anda tidak terdaftar sebagai Admin GarudaTel.")
        return

    if text.startswith('/bcpos'):
        raw_body = text[len('/bcpos'):].strip()
        if '|' not in raw_body:
            _send_message(
                token,
                chat_id,
                "⚠️ <b>Format Broadcast Kasir POS:</b>\n"
                "<code>/bcpos Judul Pengumuman | Isi Pesan Lengkap</code>\n\n"
                "Contoh:\n"
                "<code>/bcpos Info PLN | Cut-off PLN pukul 23:30 - 00:30 WIB</code>"
            )
            return
        title_part, msg_part = [p.strip() for p in raw_body.split('|', 1)]
        with app.app_context():
            from app.models.merchant import PosBroadcast, ensure_merchant_provision_table, get_wib_datetime
            from app.services.merchant_service import dispatch_pos_broadcast
            from app.extensions import db
            ensure_merchant_provision_table()
            b = PosBroadcast(
                title=title_part[:150],
                message=msg_part,
                level='info',
                target_merchant_id='ALL',
                is_active=True,
                created_at=get_wib_datetime()
            )
            db.session.add(b)
            db.session.commit()
            dispatch_pos_broadcast(b)
            _send_message(
                token,
                chat_id,
                f"📢 <b>Broadcast Kasir POS Dipublikasikan!</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 <b>Judul:</b> {b.title}\n"
                f"💬 <b>Pesan:</b> {b.message}\n"
                f"🎯 <b>Target:</b> Seluruh Kasir POS Aktif"
            )
        return

    # Tangkap balasan nomor telepon untuk pairing WhatsApp (awalan 62 dan panjang 10-16 digit)
    clean_digits = ''.join(c for c in text if c.isdigit())
    if clean_digits.startswith('62') and 10 <= len(clean_digits) <= 16 and not text.startswith('/'):
        _send_message(token, chat_id, f"⏳ <i>Sedang memproses Pairing Code untuk nomor <code>{clean_digits}</code>... Harap tunggu 3 detik untuk menstabilkan soket WhatsApp...</i>")
        try:
            from app.wa_helper import _get_wa_headers
            res = requests.post('http://127.0.0.1:3000/api/pair', json={'number': clean_digits}, headers=_get_wa_headers(), timeout=35)
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

    # Perintah /topuser, /topusers, /toptrx, /toptransaksi
    if any(text.lower().startswith(cmd) for cmd in ['/topuser', '/topusers', '/toptrx', '/toptransaksi']):
        with app.app_context():
            rep_text, rep_kb = render_top_users_report()
            _send_message(token, chat_id, rep_text, reply_markup=rep_kb)
        return

    # Perintah /produkgagal, /analisaproduk, /laporangagal, /failedproducts, /analisaseller
    if any(text.lower().startswith(cmd) for cmd in ['/produkgagal', '/analisaproduk', '/laporangagal', '/failedproducts', '/analisaseller']):
        parts = text.split()
        cmd_lower = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ''
        with app.app_context():
            if cmd_lower.startswith('/analisaseller'):
                p_arg = arg if arg.lower() in ['1d', '7d', '30d', 'all', 'hariini', 'semua'] else '30d'
                rep_text, rep_kb = render_failed_sellers_report(period=p_arg, page=1, per_page=5, filter_mode='active')
                _send_message(token, chat_id, rep_text, reply_markup=rep_kb)
                return

            if arg and arg.lower() not in ['1d', '7d', '30d', 'all', 'hariini', 'semua', 'crit', 'kritis', 'arsip', 'nonaktif']:
                # Anggap argumen sebagai kode SKU spesifik yang ingin diinspeksi
                det_text, det_kb = render_failed_product_detail(arg, period='30d')
                _send_message(token, chat_id, det_text, reply_markup=det_kb)
                return

            p_arg = arg.lower() if arg.lower() in ['1d', '7d', '30d', 'all', 'hariini', 'semua'] else '30d'
            if arg.lower() in ['crit', 'kritis']:
                f_mode = 'crit'
            elif arg.lower() in ['all', 'semua', 'arsip', 'nonaktif']:
                f_mode = 'all'
            else:
                f_mode = 'active'

            rep_text, rep_kb = render_failed_products_report(
                period=p_arg, page=1, per_page=5, filter_mode=f_mode, auto_fallback=(not bool(arg))
            )
            _send_message(token, chat_id, rep_text, reply_markup=rep_kb)
        return

    # Perintah /deposit, /tarikdeposit, /tarik_deposit
    if any(text.lower().startswith(cmd) for cmd in ['/tarikdeposit', '/tarik_deposit', '/deposit']):
        parts = text.split()
        with app.app_context():
            if len(parts) == 1:
                dep_text, dep_kb = render_tarik_deposit_menu()
                _send_message(token, chat_id, dep_text, reply_markup=dep_kb)
                return

            if len(parts) < 3:
                _send_message(token, chat_id, (
                    "⚠️ <b>Format Tarik Deposit Salah!</b>\n"
                    "Gunakan: <code>/tarikdeposit &lt;metode&gt; &lt;nominal&gt; [nama_pengirim]</code>\n\n"
                    "Metode yang didukung: <code>gopay</code>, <code>shopeepay</code>, <code>bca</code>, <code>mandiri</code>, <code>bri</code>, <code>bni</code>\n"
                    "Contoh:\n"
                    "👉 <code>/tarikdeposit gopay 250000</code>\n"
                    "👉 <code>/tarikdeposit shopeepay 500000 ANGGA DIAN</code>\n\n"
                    "<i>*Catatan: Minimal nominal deposit adalah Rp 200.000 (200K).</i>"
                ), reply_markup=get_back_button())
                return

            method_input = parts[1]
            try:
                amt_input = float(parts[2])
            except ValueError:
                _send_message(token, chat_id, "⚠️ Nominal deposit harus berupa angka (min 200K)!", reply_markup=get_back_button())
                return

            owner_input = " ".join(parts[3:]).strip() if len(parts) >= 4 else None
            execute_tarik_deposit(token, chat_id, None, method_input, amt_input, owner_name=owner_input, is_edit=False)
        return

    # Perintah /bataldeposit <id>
    if text.lower().startswith('/bataldeposit') or text.lower().startswith('/batal_deposit'):
        parts = text.split()
        if len(parts) < 2:
            _send_message(token, chat_id, "⚠️ Gunakan format: <code>/bataldeposit &lt;id_tiket&gt;</code>\nContoh: <code>/bataldeposit 12</code>")
            return
        try:
            t_id = int(parts[1])
        except ValueError:
            _send_message(token, chat_id, "⚠️ ID Tiket deposit harus berupa angka!")
            return
        with app.app_context():
            cancel_tarik_deposit(token, chat_id, None, t_id, is_edit=False)
        return

    # Perintah /saldo atau /saldodigi
    if text.strip().lower() in ['/saldo', '/saldodigi', 'saldo', 'saldo digiflazz', 'cek saldo digiflazz']:
        with app.app_context():
            from app.services.digiflazz import check_balance
            from app.extensions import db
            from app.models.user import User
            is_ok, bal, msg = check_balance()
            if is_ok:
                total_user_balance = db.session.query(db.func.sum(User.balance)).scalar() or 0.0
                total_users = User.query.count()

                diff = float(bal) - float(total_user_balance)
                if diff > 0:
                    diff_str = f"+Rp {diff:,.0f} (Surplus / Aman ✅)"
                elif diff < 0:
                    diff_str = f"-Rp {abs(diff):,.0f} (Defisit / Kurang ⚠️)"
                else:
                    diff_str = f"Rp 0 (Seimbang / Pas)"

                text_reply = (
                    "💰 <b>INFORMASI SALDO DIGIFLAZZ</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Saldo Digiflazz:</b> <code>Rp {bal:,.0f}</code>\n"
                    f"• <b>Total Saldo User:</b> <code>Rp {total_user_balance:,.0f}</code> ({total_users} user)\n"
                    f"• <b>Selisih (Digiflazz - User):</b> <code>{diff_str}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"• <b>Status API:</b> Terhubung Normal (200 OK)\n"
                    f"• <b>Update:</b> {format_wib(fmt='%d/%m/%Y %H:%M:%S WIB')}"
                )
            else:
                text_reply = f"🚨 <b>GAGAL CEK SALDO:</b>\n{msg}"
            _send_message(token, chat_id, text_reply, reply_markup=get_admin_inline_keyboard())
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
            from app.extensions import db
            from app.services.digiflazz import sync_products
            try:
                Product.query.filter(Product.is_active == False, Product.is_admin_disabled != True).update({'is_admin_disabled': True})
                db.session.commit()
            except Exception:
                pass
            ok, msg = sync_products(force=force_flag, notify_admin_bot=False)
            icon = "✅" if ok else "🚨"
            _send_message(token, chat_id, f"{icon} <b>HASIL SINKRONISASI DIGIFLAZZ:</b>\n\n{msg}")
        return

    # Perintah /batal jika dalam mode pencarian produk nonaktif
    if text.strip() == '/batal':
        _ADMIN_SEARCH_STATE.pop(str(chat_id), None)
        _ADMIN_SEARCH_STATE.pop(int(chat_id) if str(chat_id).isdigit() else chat_id, None)
        with app.app_context():
            c_text, c_kb = render_disabled_catalog_sellers_menu(page=1, per_page=6)
            _send_message(token, chat_id, "ℹ️ <i>Pencarian dibatalkan.</i>\n\n" + c_text, reply_markup=c_kb)
        return

    # Perintah /cari, /cariproduk, /carinonaktif ATAU sedang dalam mode search text prompt
    is_in_search_state = _ADMIN_SEARCH_STATE.get(str(chat_id)) or _ADMIN_SEARCH_STATE.get(int(chat_id) if str(chat_id).isdigit() else chat_id)
    if text.startswith('/cari') or text.startswith('/cariproduk') or text.startswith('/carinonaktif') or (is_in_search_state and not text.startswith('/')):
        if text.startswith('/'):
            parts = text.split(maxsplit=1)
            search_query = parts[1].strip() if len(parts) > 1 else ''
        else:
            search_query = text.strip()
            _ADMIN_SEARCH_STATE.pop(str(chat_id), None)
            _ADMIN_SEARCH_STATE.pop(int(chat_id) if str(chat_id).isdigit() else chat_id, None)

        if not search_query:
            _send_message(
                token, chat_id,
                "🔍 <b>FORMAT PENCARIAN PRODUK NONAKTIF</b>\n"
                "Ketik kata kunci nama produk setelah perintah /cari.\n"
                "Contoh: <code>/cari telkomsel 10</code> atau <code>/cari dana</code>",
                reply_markup={"inline_keyboard": [[{"text": "🔍 Buka Form Cari", "callback_data": "dis_search_prompt"}]]}
            )
            return

        with app.app_context():
            s_text, s_kb = render_disabled_search_results(keyword=search_query, page=1, per_page=5)
            _send_message(token, chat_id, s_text, reply_markup=s_kb)
        return

    # Perintah /produknonaktif atau /nonaktif atau /aktifkanproduk
    if text.startswith('/produknonaktif') or text.startswith('/nonaktif') or text.startswith('/aktifkanproduk'):
        with app.app_context():
            c_text, c_kb = render_disabled_catalog_sellers_menu(page=1, per_page=6)
            _send_message(token, chat_id, c_text, reply_markup=c_kb)
        return

    # Perintah Menu Utama (/start, /menu, /help)
    welcome_text = (
        "🦅 <b>BOT 3 : PANEL & FITUR ADMIN GARUDATEL v2</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Selamat datang di Bot 3 (Panel & Fitur Admin Telegram).\n"
        "Gunakan tombol interaktif di bawah ini atau ketik pintasan cepat:\n"
        "• <code>/cari nama_produk</code> — Cari & Aktifkan Produk Nonaktif Cepat\n"
        "• <code>/produknonaktif</code> — Kelola & Aktifkan Produk Nonaktif Per Seller\n"
        "• <code>/produkgagal</code> — Analisa Produk & Seller Sering Gagal\n"
        "• <code>/analisaseller</code> — Rapor Seller Paling Sering Gagal\n"
        "• <code>/toko</code> | <code>/saldo</code> | <code>/topusers</code> | <code>/otp</code>"
    )
    _send_message(token, chat_id, welcome_text, reply_markup=get_admin_inline_keyboard())


def _answer_callback(token, callback_query_id, text=""):
    try:
        call_telegram_api('post', f"bot{token}/answerCallbackQuery", json={
            "callback_query_id": callback_query_id,
            "text": text
        }, timeout=8)
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
        call_telegram_api('post', f"bot{token}/editMessageText", json=payload, timeout=15)
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
        call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=15)
    except Exception as e:
        logger.error(f"[Bot 3] Gagal kirim pesan: {e}")
