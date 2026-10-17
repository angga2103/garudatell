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


def record_device_heartbeat(battery=None, is_charging=None, client_ip=None):
    """Mencatat sinyal ping aktif (heartbeat) dari HP Samsung J1 Ace."""
    now_iso = datetime.utcnow().isoformat()
    set_setting_value('dana_device_last_ping', now_iso)
    if battery is not None:
        set_setting_value('dana_device_battery', str(battery))
    if is_charging is not None:
        set_setting_value('dana_device_charging', '1' if is_charging else '0')
    if client_ip:
        set_setting_value('dana_device_ip', str(client_ip))


def get_device_status():
    """Mengembalikan status live HP Samsung J1 Ace pembaca mutasi DANA."""
    last_ping_raw = get_setting_value('dana_device_last_ping', '')
    battery = get_setting_value('dana_device_battery', '-')
    is_charging = get_setting_value('dana_device_charging', '0') == '1'
    client_ip = get_setting_value('dana_device_ip', '-')

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
        'client_ip': client_ip
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
    Menghasilkan kode unik acak 3 digit (1 s/d 999) yang dijamin
    TIDAK BENTROK dengan tiket deposit aktif lainnya dalam 45 menit terakhir.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=45)
    existing_pending = Transaction.query.filter(
        Transaction.sku_code == 'DEPOSIT_MANUAL',
        Transaction.status == 'PENDING',
        Transaction.created_at >= cutoff
    ).all()

    existing_amounts = {int(t.amount or 0) for t in existing_pending}

    # Coba acak hingga 100 kali untuk menghindari tabrakan kode unik
    for _ in range(100):
        code = random.randint(1, 999)
        total = int(nominal) + code
        if total not in existing_amounts:
            return code, total

    # Fallback darurat jika sangat ramai (4 digit acak)
    code = random.randint(1000, 9999)
    return code, int(nominal) + code


def create_dana_deposit_ticket(user_id, nominal):
    """
    Membuat tiket deposit DANA Otomatis baru dengan kode unik.
    """
    user = User.query.get(user_id)
    if not user:
        return False, "Pengguna tidak ditemukan", None

    nominal = int(float(nominal))
    if nominal < 5000:
        return False, "Minimal deposit adalah Rp 5.000", None

    depo_settings = get_manual_deposit_settings()
    dest_number = depo_settings.get('dana_number') or "081775700114"
    dest_name = depo_settings.get('dana_name') or "GarudaTel / Kasir"

    unique_code, total_transfer = generate_unique_code(nominal)
    ref_id = f"DEP-DANA-{int(time.time())}{random.randint(100, 999)}"

    # Durasi kadaluarsa 30 menit
    expires_at = datetime.utcnow() + timedelta(minutes=30)
    expires_epoch = int(expires_at.replace(tzinfo=timezone.utc).timestamp())

    trx = Transaction(
        ref_id=ref_id,
        user_id=user.id,
        sku_code='DEPOSIT_MANUAL',
        product_name='Deposit DANA Otomatis',
        target_number=dest_number,
        amount=float(total_transfer),
        base_price=0.0,
        payment_method='dana_auto',
        payment_status='UNPAID',
        status='PENDING',
        is_prepaid=True,
        sn=f"Nominal Pokok: Rp {nominal:,} | Kode Unik: {unique_code:03d} | Total: Rp {total_transfer:,} | Rek: {dest_number} a.n {dest_name}"
    )

    db.session.add(trx)
    db.session.commit()

    # Kirim notifikasi transaksi tiket ke Telegram Admin
    try:
        from app.services.telegram_service import async_send_trx_notification
        async_send_trx_notification(trx, title="TIKET DEPOSIT DANA DIBUAT (AUTO)")
    except Exception as e:
        logger.error(f"[DANA DEPO] Error notif telegram: {e}")

    ticket_data = {
        'ref_id': ref_id,
        'nominal': nominal,
        'unique_code': f"{unique_code:03d}",
        'total_transfer': total_transfer,
        'dest_number': dest_number,
        'dest_name': dest_name,
        'status': 'PENDING',
        'expires_epoch': expires_epoch,
        'expires_at_str': format_wib(expires_at),
        'created_at_str': format_wib(trx.created_at)
    }

    return True, "Tiket deposit DANA berhasil dibuat.", ticket_data


def process_incoming_dana_mutation(raw_amount, sender_name="Member DANA", raw_text=""):
    """
    Mencocokkan transfer masuk dari HP Samsung J1 Ace ke tiket deposit pending.
    Eksekusi atomic dengan locking baris database untuk mencegah double-credit.
    """
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

    # Cari transaksi pending dengan nominal yang sama persis
    trx = Transaction.query.filter(
        Transaction.sku_code == 'DEPOSIT_MANUAL',
        Transaction.amount == amount_int,
        Transaction.status == 'PENDING',
        Transaction.payment_status == 'UNPAID',
        Transaction.created_at >= cutoff
    ).order_by(Transaction.id.desc()).first()

    if not trx:
        logger.warning(f"[DANA MUTASI] Tidak ditemukan tiket deposit pending untuk nominal Rp {amount_int:,}. Pengirim: {sender_name}")
        return False, f"Tidak ada tiket deposit pending dengan nominal Rp {amount_int:,}", None

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
        
        now_wib = format_wib()
        clean_sender = str(sender_name or 'Member DANA').strip()[:50]
        trx.sn = f"{trx.sn or ''} | SUKSES DANA AUTO via J1 Ace (Pengirim: {clean_sender} - {now_wib})"

        db.session.commit()
        logger.info(f"[DANA MUTASI ACC] User #{user.id} ({user.name}) Saldo +Rp {credit_amount:,} -> Rp {new_balance:,} | Trx: {trx.ref_id}")

        # Kirim notifikasi keberhasilan ke Bot Notifikasi Telegram Admin
        try:
            _send_dana_success_telegram_alert(trx, user, credit_amount, new_balance, clean_sender)
        except Exception as e_alert:
            logger.error(f"[DANA TELEGRAM ERR] {e_alert}")

        return True, f"Deposit Rp {credit_amount:,} untuk {user.name} berhasil disetujui otomatis!", trx

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


def _send_dana_success_telegram_alert(trx, user, amount, new_balance, sender_name):
    """Mengirim pesan notifikasi instan ke Bot Telegram Admin."""
    from app.services.telegram_service import get_bot_notif_credentials, get_bot_admin_credentials, call_telegram_api
    token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        token, chat_id = get_bot_admin_credentials()
    if not token or not chat_id:
        return

    wib_now = format_wib()
    lines = [
        "⚡ <b>DEPOSIT DANA OTOMATIS BERHASIL</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📋 <b>Ref ID:</b> <code>{trx.ref_id}</code>",
        f"👤 <b>Member:</b> <b>{user.name}</b> (<code>#{user.id}</code>)",
        f"📱 <b>WhatsApp:</b> <code>{user.phone}</code>",
        f"💰 <b>Nominal Masuk:</b> <b>Rp {amount:,.0f}</b>",
        f"👤 <b>Pengirim DANA:</b> <b>{sender_name}</b>",
        f"💳 <b>Saldo Utama Sekarang:</b> Rp {new_balance:,.0f}",
        f"📊 <b>Status:</b> <b>SUKSES (TERVERIFIKASI HP)</b>",
        f"📱 <b>Alat Verifikasi:</b> Samsung J1 Ace",
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
    call_telegram_api('post', f"bot{token}/sendMessage", json=payload, timeout=(10, 20))
