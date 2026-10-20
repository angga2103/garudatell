import os
import re
import time
import random
import secrets
import logging
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.user import User
from app.models.transaction import Transaction
from app.models.setting import Setting
from app.services.setting_service import get_setting_value, set_setting_value, get_manual_deposit_settings

logger = logging.getLogger(__name__)

WIB_TZ = timezone(timedelta(hours=7))

def get_wib_now():
    return datetime.now(WIB_TZ)

def format_wib(dt=None, fmt='%d/%m/%Y %H:%M WIB'):
    if dt is None:
        dt = get_wib_now()
    elif isinstance(dt, datetime) and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc).astimezone(WIB_TZ)
    return dt.strftime(fmt)


def get_dana_device_token():
    """
    Mengambil secret token autentikasi untuk HP Samsung J1 Ace.
    Jika belum ada, otomatis generate 32-karakter token aman.
    """
    token = get_setting_value('dana_device_token', '')
    if not token or len(token) < 16:
        token = secrets.token_hex(16)
        set_setting_value('dana_device_token', token)
    return token


def regenerate_dana_device_token():
    """Memperbarui secret token device dengan token baru."""
    new_token = secrets.token_hex(16)
    set_setting_value('dana_device_token', new_token)
    return new_token


def record_device_heartbeat(battery=None, is_charging=None, client_ip=None, listener_connected=None, app_version=None, device_id=None):
    """Mencatat sinyal ping aktif (heartbeat) dari HP Samsung J1 Ace / PayHook."""
    now_iso = datetime.utcnow().isoformat()
    set_setting_value('dana_device_last_ping', now_iso)
    if battery is not None:
        set_setting_value('dana_device_battery', str(battery))
    if is_charging is not None:
        set_setting_value('dana_device_charging', '1' if is_charging else '0')
    if client_ip:
        set_setting_value('dana_device_ip', str(client_ip))
    if listener_connected is not None:
        set_setting_value('dana_device_listener', '1' if listener_connected else '0')
    if app_version:
        set_setting_value('dana_device_app_ver', str(app_version))
    if device_id:
        set_setting_value('dana_device_id', str(device_id))


def get_device_status():
    """Mengembalikan status live HP Samsung J1 Ace pembaca mutasi DANA."""
    last_ping_raw = get_setting_value('dana_device_last_ping', '')
    battery = get_setting_value('dana_device_battery', '-')
    is_charging = get_setting_value('dana_device_charging', '0') == '1'
    client_ip = get_setting_value('dana_device_ip', '-')
    listener_connected = get_setting_value('dana_device_listener', '1') == '1'
    app_version = get_setting_value('dana_device_app_ver', 'PayHook')
    device_id = get_setting_value('dana_device_id', '-')

    is_online = False
    minutes_ago = None
    last_ping_str = 'Belum Pernah Terhubung'

    if last_ping_raw:
        try:
            last_dt = datetime.fromisoformat(last_ping_raw)
            diff = (datetime.utcnow() - last_dt).total_seconds()
            minutes_ago = int(diff / 60)
            is_online = (diff <= 900)  # Online jika lapor dalam 15 menit terakhir
            last_ping_str = format_wib(last_dt)
        except Exception:
            pass

    return {
        'is_online': is_online,
        'minutes_ago': minutes_ago,
        'last_ping_str': last_ping_str,
        'battery': battery,
        'is_charging': is_charging,
        'client_ip': client_ip,
        'listener_connected': listener_connected,
        'app_version': app_version,
        'device_id': device_id
    }


def extract_amount_from_text(text):
    """
    Mengekstrak nominal Rupiah dari teks notifikasi DANA.
    Mendukung format: 'Rp 50.047', 'Rp50.047', 'Rp 50,047', atau 'sebesar 50047'.
    """
    if not text:
        return None
    # 1. Cari pola Rp dengan pemisah ribuan titik atau koma
    m = re.search(r'Rp\s?([0-9\.\,]+)', str(text), re.IGNORECASE)
    if m:
        raw_clean = m.group(1).replace('.', '').replace(',', '')
        try:
            val = int(raw_clean)
            if val > 0:
                return val
        except Exception:
            pass

    # 2. Cari pola kata kunci 'sebesar' atau 'uang' diikuti angka
    m2 = re.search(r'(?:sebesar|uang|saldo)\s+([0-9\.\,]+)', str(text), re.IGNORECASE)
    if m2:
        raw_clean = m2.group(1).replace('.', '').replace(',', '')
        try:
            val = int(raw_clean)
            if val > 0:
                return val
        except Exception:
            pass

    # 3. Fallback: Cari deretan angka nominal wajar (4 s/d 9 digit)
    m3 = re.findall(r'\b\d{4,9}\b', str(text))
    if m3:
        try:
            return int(m3[0])
        except Exception:
            pass

    return None


def extract_sender_from_text(text):
    """Mengekstrak nama pengirim dari teks notifikasi DANA."""
    if not text:
        return "Member DANA"
    # Contoh notif DANA: 'Kamu menerima uang Rp 50.047 dari BUDI SANTOSO'
    m = re.search(r'dari\s+([^,\.\n\r]+)', str(text), re.IGNORECASE)
    if m:
        name = m.group(1).strip()
        # Bersihkan kata-kata residu jika ada
        name = re.sub(r'\s+(melalui|lewat|pada).*$', '', name, flags=re.IGNORECASE).strip()
        return name[:50]
    return "Member DANA"


def generate_unique_code(nominal):
    """
    Menghasilkan kode unik acak range 10 s/d 150 sesuai permintaan admin
    agar tidak memberatkan pelanggan, dan dijamin TIDAK BENTROK dengan
    tiket deposit aktif lainnya dalam 45 menit terakhir.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=45)
    from sqlalchemy import or_
    existing_pending = Transaction.query.filter(
        or_(
            (Transaction.sku_code == 'DEPOSIT_MANUAL') & (Transaction.status == 'PENDING'),
            (Transaction.payment_method == 'QRIS') & (Transaction.payment_status == 'UNPAID') & (Transaction.status.in_(['UNPAID', 'PENDING']))
        ),
        Transaction.created_at >= cutoff
    ).all()

    existing_amounts = {int(t.amount or 0) for t in existing_pending}

    # Coba acak dalam range 10 s/d 150 terlebih dahulu (141 kombinasi angka)
    for _ in range(100):
        code = random.randint(10, 150)
        total = int(nominal) + code
        if total not in existing_amounts:
            return code, total

    # Fallback jika antrean tiket aktif sedang sangat padat
    for _ in range(100):
        code = random.randint(151, 300)
        total = int(nominal) + code
        if total not in existing_amounts:
            return code, total

    code = random.randint(301, 999)
    return code, int(nominal) + code


def create_ewallet_deposit_ticket(user_id, nominal, ewallet_type='DANA'):
    """
    Membuat tiket deposit E-Wallet Otomatis (DANA, GOPAY, SHOPEEPAY) baru dengan kode unik.
    """
    user = User.query.get(user_id)
    if not user:
        return False, "Pengguna tidak ditemukan", None

    nominal = int(float(nominal))
    if nominal < 5000:
        return False, "Minimal deposit adalah Rp 5.000", None

    ewallet_type = str(ewallet_type or 'DANA').upper().strip()
    depo_settings = get_manual_deposit_settings()

    if ewallet_type == 'GOPAY':
        dest_number = depo_settings.get('gopay_number') or "081775700114"
        dest_name = depo_settings.get('gopay_name') or "GarudaTel / Kasir"
        product_name = 'Deposit GoPay Otomatis'
        payment_method = 'gopay_auto'
        ref_prefix = 'DEP-GOPAY'
    elif ewallet_type == 'SHOPEEPAY':
        dest_number = depo_settings.get('shopee_number') or "081775700114"
        dest_name = depo_settings.get('shopee_name') or "GarudaTel / Kasir"
        product_name = 'Deposit ShopeePay Otomatis'
        payment_method = 'shopeepay_auto'
        ref_prefix = 'DEP-SHOPEE'
    else:
        ewallet_type = 'DANA'
        dest_number = depo_settings.get('dana_number') or "081775700114"
        dest_name = depo_settings.get('dana_name') or "GarudaTel / Kasir"
        product_name = 'Deposit DANA Otomatis'
        payment_method = 'dana_auto'
        ref_prefix = 'DEP-DANA'

    unique_code, total_transfer = generate_unique_code(nominal)
    ref_id = f"{ref_prefix}-{int(time.time())}{random.randint(100, 999)}"

    # Durasi kadaluarsa 30 menit
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    expires_epoch = int(expires_at.replace(tzinfo=timezone.utc).timestamp())

    trx = Transaction(
        ref_id=ref_id,
        user_id=user.id,
        sku_code='DEPOSIT_MANUAL',
        product_name=product_name,
        target_number=dest_number,
        amount=float(total_transfer),
        base_price=0.0,
        payment_method=payment_method,
        payment_status='UNPAID',
        status='PENDING',
        is_prepaid=True,
        sn=f"Nominal Pokok: Rp {nominal:,} | Kode Unik: {unique_code:03d} | Total: Rp {total_transfer:,} | Rek: {dest_number} a.n {dest_name} ({ewallet_type})"
    )

    db.session.add(trx)
    db.session.commit()

    # Kirim notifikasi transaksi tiket ke Telegram Admin
    try:
        from app.services.telegram_service import async_send_trx_notification
        async_send_trx_notification(trx, title=f"TIKET DEPOSIT {ewallet_type} DIBUAT (AUTO)")
    except Exception as e:
        logger.error(f"[{ewallet_type} DEPO] Error notif telegram: {e}")

    ticket_data = {
        'ref_id': ref_id,
        'nominal': nominal,
        'unique_code': f"{unique_code:03d}",
        'total_transfer': total_transfer,
        'ewallet_type': ewallet_type,
        'dest_number': dest_number,
        'dest_name': dest_name,
        'status': 'PENDING',
        'expires_epoch': expires_epoch,
        'expires_at_str': format_wib(expires_at),
        'created_at_str': format_wib(trx.created_at)
    }

    return True, f"Tiket deposit {ewallet_type} berhasil dibuat.", ticket_data


def create_dana_deposit_ticket(user_id, nominal):
    """Wrapper kompatibilitas untuk membuat tiket deposit DANA Otomatis."""
    return create_ewallet_deposit_ticket(user_id, nominal, ewallet_type='DANA')


def process_incoming_dana_mutation(raw_amount, sender_name="Member DANA", raw_text="", event_id=None):
    """
    Mencocokkan transfer masuk dari HP Samsung J1 Ace / PayHook ke tiket deposit pending.
    Eksekusi atomic dengan locking baris database untuk mencegah double-credit.
    Mendukung idempotency via event_id PayHook.
    """
    # 1. Cek Idempotency Key (PayHook event_id) agar tidak double-credit pada retry
    if event_id:
        clean_evt = str(event_id).strip()
        existing_trx = Transaction.query.filter(
            db.or_(
                Transaction.sn.like(f"%evt:{clean_evt}%"),
                Transaction.provider_ref == f"DANA:{clean_evt}",
                Transaction.provider_ref == clean_evt,
            )
        ).first()
        if existing_trx:
            logger.info(f"[DANA MUTASI IDEMPOTENT] Event {clean_evt} sudah diproses sebelumnya pada {existing_trx.ref_id}")
            return True, "Transaksi sudah diverifikasi sebelumnya (idempoten)", existing_trx

    try:
        if isinstance(raw_amount, (int, float)):
            amount_int = int(raw_amount)
        elif isinstance(raw_amount, dict):
            val = raw_amount.get('value') or raw_amount.get('amount') or 0
            clean_str = re.sub(r'[^0-9]', '', str(val))
            amount_int = int(clean_str)
        else:
            clean_str = re.sub(r'[^0-9]', '', str(raw_amount))
            amount_int = int(clean_str)
    except (ValueError, TypeError, Exception):
        return False, f"Nominal mutasi tidak valid: {raw_amount}", None

    cutoff = datetime.utcnow() - timedelta(minutes=45)

    # 1. Prioritas Utama: Cari tiket deposit manual pending
    trx = Transaction.query.filter(
        Transaction.sku_code == 'DEPOSIT_MANUAL',
        Transaction.amount == amount_int,
        Transaction.status == 'PENDING',
        Transaction.payment_status == 'UNPAID',
        Transaction.created_at >= cutoff
    ).order_by(Transaction.id.desc()).first()

    # 2. Prioritas Kedua: Cari pesanan produk langsung via QRIS pending
    is_direct_qris = False
    if not trx:
        trx = Transaction.query.filter(
            Transaction.sku_code != 'DEPOSIT_MANUAL',
            Transaction.payment_method == 'QRIS',
            Transaction.amount == amount_int,
            Transaction.payment_status == 'UNPAID',
            Transaction.status.in_(['UNPAID', 'PENDING']),
            Transaction.created_at >= cutoff
        ).order_by(Transaction.id.desc()).first()
        if trx:
            is_direct_qris = True

    if not trx:
        # 3. Prioritas Ketiga: CEK PESANAN QRIS YANG SUDAH TERLANJUR DIBATALKAN OLEH USER
        # (Pelanggan terlanjur klik "Batalkan" tapi ternyata tetap transfer/scan QRIS via M-Banking)
        # Amankan dana pelanggan: Otomatis masukkan uang masuk ke Saldo Akun User!
        trx_cancelled = Transaction.query.filter(
            Transaction.sku_code != 'DEPOSIT_MANUAL',
            Transaction.payment_method == 'QRIS',
            Transaction.amount == amount_int,
            Transaction.status == 'CANCELLED',
            Transaction.created_at >= cutoff
        ).order_by(Transaction.id.desc()).first()

        if trx_cancelled and trx_cancelled.user_id:
            user = db.session.query(User).filter_by(id=trx_cancelled.user_id).with_for_update().first()
            if user:
                old_bal = float(user.balance or 0.0)
                user.balance = round(old_bal + float(amount_int), 2)
                trx_cancelled.payment_status = 'PAID'
                if event_id:
                    clean_evt = str(event_id).strip()
                    trx_cancelled.provider_ref = f"DANA:{clean_evt}"[:100]
                now_wib = format_wib()
                clean_sender = str(sender_name or 'Member DANA').strip()[:50]
                evt_tag = f"evt:{event_id} " if event_id else ""
                trx_cancelled.sn = f"{trx_cancelled.sn or ''} | DANA QRIS DITERIMA (Pesanan dibatalkan -> Dana Rp {amount_int:,} masuk Saldo Akun [{evt_tag}Pengirim: {clean_sender} - {now_wib}])"[:255]
                db.session.commit()

                logger.info(f"[QRIS CANCELLED RECOVERY] User #{user.id} ({user.name}) saldo +Rp {amount_int:,} karena scan QR pesanan dibatalkan ({trx_cancelled.ref_id})")
                try:
                    _send_dana_success_telegram_alert(trx_cancelled, user, amount_int, user.balance, clean_sender, ew_label="QRIS (RECOVERY BATAL)")
                except Exception:
                    pass
                return True, f"Pembayaran QRIS Rp {amount_int:,} untuk pesanan yang dibatalkan ({trx_cancelled.ref_id}) berhasil diamankan dan dimasukkan ke Saldo Akun {user.name}!", trx_cancelled

        logger.warning(f"[DANA MUTASI] Tidak ditemukan tiket deposit atau pesanan QRIS pending untuk nominal Rp {amount_int:,}. Pengirim: {sender_name}")
        return False, f"Tidak ada tiket deposit atau pesanan QRIS pending dengan nominal Rp {amount_int:,}", None

    now_wib = format_wib()
    clean_sender = str(sender_name or 'Member DANA').strip()[:50]
    evt_tag = f"evt:{event_id} " if event_id else ""

    # KASUS A: TRANSAKSI PRODUK LANGSUNG VIA QRIS
    if is_direct_qris:
        try:
            user = User.query.get(trx.user_id) if trx.user_id else None
            trx.payment_status = 'PAID'
            prev_sn = (trx.sn or '').strip()
            trx.sn = f"{prev_sn} | DANA QRIS AUTO ({evt_tag}Pengirim: {clean_sender} - {now_wib})"[:255]
            if event_id:
                trx.provider_ref = f"DANA:{clean_evt}"[:100]
            db.session.commit()

            # Proses eksekusi ke provider (Digiflazz)
            from app.services.order_service import process_paid_order
            process_paid_order(trx)

            logger.info(f"[QRIS DANA AUTO SUCCESS] Trx {trx.ref_id} ({trx.product_name}) diproses otomatis untuk User #{trx.user_id}. Pengirim: {clean_sender}")

            # Kirim Telegram Alert khusus Pembayaran Produk QRIS
            try:
                _send_dana_qris_product_telegram_alert(trx, user, amount_int, clean_sender)
            except Exception as e_tg:
                logger.error(f"[DANA QRIS TELEGRAM ERR] {e_tg}")

            return True, f"Pembayaran QRIS Rp {amount_int:,} untuk {trx.product_name} ({trx.ref_id}) berhasil disetujui otomatis!", trx

        except Exception as e:
            db.session.rollback()
            logger.error(f"[DANA QRIS ERROR] Gagal proses pesanan {amount_int}: {e}")
            return False, f"Terjadi kesalahan saat memproses pesanan QRIS: {str(e)}", None

    # KASUS B: TIKET DEPOSIT MANUAL (TAMBAH SALDO AKUN)
    try:
        # Lock user row untuk update saldo aman
        user = db.session.query(User).filter_by(id=trx.user_id).with_for_update().first()
        if not user:
            return False, f"User ID {trx.user_id} tidak ditemukan", None

        old_balance = float(user.balance or 0.0)
        credit_amount = float(trx.amount)
        new_balance = round(old_balance + credit_amount, 2)

        # Update saldo & status transaksi
        user.balance = new_balance
        trx.status = 'SUCCESS'
        trx.payment_status = 'PAID'
        
        ew_label = "DANA"
        if trx.product_name:
            if "GOPAY" in trx.product_name.upper():
                ew_label = "GOPAY"
            elif "SHOPEE" in trx.product_name.upper():
                ew_label = "SHOPEEPAY"
        elif trx.payment_method:
            if "gopay" in trx.payment_method.lower():
                ew_label = "GOPAY"
            elif "shopee" in trx.payment_method.lower():
                ew_label = "SHOPEEPAY"

        trx.sn = f"{trx.sn or ''} | SUKSES {ew_label} AUTO via PayHook ({evt_tag}Pengirim: {clean_sender} - {now_wib})"
        if event_id:
            trx.provider_ref = f"DANA:{clean_evt}"[:100]

        db.session.commit()
        logger.info(f"[{ew_label} MUTASI ACC] User #{user.id} ({user.name}) Saldo +Rp {credit_amount:,} -> Rp {new_balance:,} | Trx: {trx.ref_id}")

        # Kirim notifikasi keberhasilan ke Bot Notifikasi Telegram Admin
        try:
            _send_dana_success_telegram_alert(trx, user, credit_amount, new_balance, clean_sender, ew_label)
        except Exception as e_alert:
            logger.error(f"[{ew_label} TELEGRAM ERR] {e_alert}")

        return True, f"Deposit {ew_label} Rp {credit_amount:,} untuk {user.name} berhasil disetujui otomatis!", trx

    except Exception as e:
        db.session.rollback()
        logger.error(f"[DANA MUTASI ERROR] Gagal proses mutasi {amount_int}: {e}")
        return False, f"Terjadi kesalahan database: {str(e)}", None


def cancel_deposit_ticket(ref_id, user_id=None):
    """Membatalkan tiket deposit pending (Tombol 'Batalkan Trx')."""
    query = Transaction.query.filter_by(ref_id=ref_id, status='PENDING')
    if user_id:
        query = query.filter_by(user_id=user_id)

    trx = query.first()
    if not trx:
        return False, "Tiket deposit tidak ditemukan atau sudah selesai."

    trx.status = 'CANCELLED'
    trx.payment_status = 'CANCELLED'
    db.session.commit()

    return True, "Tiket deposit berhasil dibatalkan."


def check_deposit_ticket_status(ref_id, user_id=None):
    """Mengecek status tiket deposit untuk polling otomatis di browser member."""
    query = Transaction.query.filter_by(ref_id=ref_id)
    if user_id:
        query = query.filter_by(user_id=user_id)

    trx = query.first()
    if not trx:
        return {'status': 'NOT_FOUND'}

    # Cek kadaluarsa otomatis jika masih pending setelah 30 menit
    if trx.status == 'PENDING' and trx.created_at:
        diff_minutes = (datetime.utcnow() - trx.created_at).total_seconds() / 60
        if diff_minutes > 30:
            trx.status = 'EXPIRED'
            trx.payment_status = 'EXPIRED'
            db.session.commit()

    user = User.query.get(trx.user_id) if trx.user_id else None

    return {
        'status': trx.status,
        'is_success': (trx.status == 'SUCCESS'),
        'ref_id': trx.ref_id,
        'amount': float(trx.amount or 0.0),
        'user_balance': float(user.balance or 0.0) if user else 0.0,
        'sn': trx.sn or '',
        'updated_at_str': format_wib(trx.updated_at or trx.created_at)
    }


def _send_dana_success_telegram_alert(trx, user, amount, new_balance, sender_name, ew_label="DANA"):
    """Mengirim pesan notifikasi instan ke Bot Telegram Admin (Asynchronous)."""
    import threading
    from app.services.telegram_service import get_bot_notif_credentials, get_bot_admin_credentials, call_telegram_api
    token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        token, chat_id = get_bot_admin_credentials()
    if not token or not chat_id:
        return

    wib_now = format_wib()
    lines = [
        f"⚡ <b>DEPOSIT {ew_label} OTOMATIS BERHASIL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 <b>Ref ID:</b> <code>{trx.ref_id}</code>",
        f"👤 <b>Member:</b> <b>{user.name}</b> (<code>#{user.id}</code>)",
        f"📱 <b>WhatsApp:</b> <code>{user.phone}</code>",
        f"💰 <b>Nominal Masuk:</b> <b>Rp {amount:,.0f}</b>",
        f"👤 <b>Pengirim {ew_label}:</b> <b>{sender_name}</b>",
        f"💳 <b>Saldo Utama Sekarang:</b> Rp {new_balance:,.0f}",
        f"📊 <b>Status:</b> <b>SUKSES (TERVERIFIKASI HP)</b>",
        f"📱 <b>Alat Verifikasi:</b> Samsung J1 Ace / PayHook",
        f"⏰ <b>Waktu:</b> {wib_now}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "✅ <i>Saldo otomatis masuk ke akun member tanpa potongan fee (0% MDR).</i>"
    ]
    payload = {
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    threading.Thread(
        target=call_telegram_api,
        args=('post', f"bot{token}/sendMessage"),
        kwargs={"json": payload, "timeout": (5, 10)},
        daemon=True
    ).start()


def _send_dana_qris_product_telegram_alert(trx, user, amount, sender_name):
    """Mengirim pesan notifikasi instan pembayaran produk via QRIS ke Bot Telegram Admin (Asynchronous)."""
    import threading
    from app.services.telegram_service import get_bot_notif_credentials, get_bot_admin_credentials, call_telegram_api
    token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        token, chat_id = get_bot_admin_credentials()
    if not token or not chat_id:
        return

    wib_now = format_wib()
    user_name = user.name if user else "Pembeli"
    user_phone = user.phone if user else "-"
    user_id_str = f"#{user.id}" if user else "-"

    lines = [
        "⚡ <b>PEMBAYARAN QRIS PRODUK DITERIMA (AUTO DANA)</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 <b>Ref ID:</b> <code>{trx.ref_id}</code>",
        f"📦 <b>Produk:</b> <b>{trx.product_name}</b>",
        f"🎯 <b>Tujuan:</b> <code>{trx.target_number}</code>",
        f"👤 <b>Member:</b> <b>{user_name}</b> (<code>{user_id_str}</code>)",
        f"📱 <b>WhatsApp:</b> <code>{user_phone}</code>",
        f"💰 <b>Nominal Masuk:</b> <b>Rp {amount:,.0f}</b>",
        f"👤 <b>Pengirim DANA:</b> <b>{sender_name}</b>",
        f"📊 <b>Status Provider:</b> <b>{trx.status}</b>",
        f"📱 <b>Alat Verifikasi:</b> Samsung J1 Ace / PayHook",
        f"⏰ <b>Waktu:</b> {wib_now}",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "✅ <i>Transaksi produk langsung diproses tanpa potongan fee gateway (0% MDR).</i>"
    ]
    payload = {
        "chat_id": chat_id,
        "text": "\n".join(lines),
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    threading.Thread(
        target=call_telegram_api,
        args=('post', f"bot{token}/sendMessage"),
        kwargs={"json": payload, "timeout": (5, 10)},
        daemon=True
    ).start()
