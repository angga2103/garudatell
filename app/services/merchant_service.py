import secrets
import hashlib
import logging
import requests
from threading import Thread
from app.extensions import db
from app.models.merchant import MerchantApiKey, get_wib_datetime
from app.models.user import User

logger = logging.getLogger(__name__)

def generate_merchant_credentials(user_id, name="Kasir Utama", webhook_url=None, ip_whitelist=None):
    """
    Membuat kredensial Merchant API baru untuk seorang user.
    """
    user = User.query.get(user_id)
    if not user:
        return None, "Pengguna tidak ditemukan"

    for _ in range(10):
        mch_id = f"IPAY_MCH_{secrets.token_hex(4).upper()}"
        if not MerchantApiKey.query.filter_by(merchant_id=mch_id).first():
            break

    for _ in range(10):
        api_key = f"IPAY_LIVE_{secrets.token_hex(16)}"
        if not MerchantApiKey.query.filter_by(api_key=api_key).first():
            break

    sec_key = f"SEC_{secrets.token_hex(16)}"

    mch = MerchantApiKey(
        user_id=user.id,
        merchant_id=mch_id,
        api_key=api_key,
        secret_key=sec_key,
        name=name or f"Kasir {user.name or user.phone}",
        webhook_url=webhook_url.strip() if webhook_url else None,
        ip_whitelist=ip_whitelist.strip() if ip_whitelist else None,
        is_active=True,
        created_at=get_wib_datetime()
    )

    db.session.add(mch)
    db.session.commit()
    logger.info(f"[MERCHANT_SERVICE] Kredensial API dibuat untuk User #{user.id} ({mch.merchant_id})")
    return mch, None

def get_client_ip(req):
    """Mendapatkan alamat IP klien nyata dari header proxy atau remote_addr."""
    x_forwarded_for = req.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return req.remote_addr or ''

def authenticate_merchant(req):
    """
    Memvalidasi otentikasi Merchant via header X-API-KEY.
    Memeriksa status aktif merchant, status aktif user, serta IP Whitelist (jika diatur).
    """
    api_key = req.headers.get("X-API-KEY") or req.headers.get("x-api-key")
    if not api_key:
        return None, ("Header X-API-KEY wajib disertakan", 401)

    merchant = MerchantApiKey.query.filter_by(api_key=api_key).first()
    if not merchant or not merchant.is_active:
        return None, ("API Key tidak valid atau dinonaktifkan", 401)

    user = merchant.user
    if not user or not user.is_active:
        return None, ("Akun pengguna pemilik API Key dinonaktifkan atau dibekukan", 403)

    # Validasi IP Whitelist (jika dikonfigurasi)
    if merchant.ip_whitelist:
        allowed_ips = [ip.strip() for ip in merchant.ip_whitelist.split(',') if ip.strip()]
        client_ip = get_client_ip(req)
        if allowed_ips and client_ip not in allowed_ips and client_ip not in ['127.0.0.1', 'localhost', '::1']:
            logger.warning(f"[MERCHANT_API] Akses ditolak untuk Merchant {merchant.merchant_id} dari IP {client_ip}")
            return None, (f"Alamat IP {client_ip} tidak terdaftar pada IP Whitelist merchant ini", 403)

    # Perbarui jejak aktivitas
    try:
        merchant.last_used_at = get_wib_datetime()
        db.session.commit()
    except Exception:
        db.session.rollback()

    return merchant, None

def verify_signature(merchant, received_sign, expected_string):
    """
    Memvalidasi integritas pesan melalui checksum MD5.
    """
    if not received_sign:
        return False
    expected_hash = hashlib.md5(expected_string.encode('utf-8')).hexdigest().lower()
    return str(received_sign).strip().lower() == expected_hash

def _send_webhook_worker(webhook_url, payload):
    try:
        requests.post(webhook_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=5)
    except Exception as e:
        logger.warning(f"[MERCHANT_WEBHOOK] Gagal mengirim webhook ke {webhook_url}: {e}")

def dispatch_merchant_webhook(merchant, payload):
    """
    Mengirimkan notifikasi callback asynchronous ke URL Webhook Merchant (POS IPAY).
    """
    if not merchant or not merchant.webhook_url:
        return

    sign = hashlib.md5(f"{merchant.merchant_id}{merchant.secret_key}{payload.get('ref_id', '')}".encode()).hexdigest()
    webhook_body = {
        "ref_id": payload.get("ref_id"),
        "status": payload.get("status"), # 'success', 'failed', 'pending'
        "sn": payload.get("sn", ""),
        "buyer_sku_code": payload.get("sku_code", ""),
        "price": payload.get("price", 0),
        "sign": sign
    }

    Thread(target=_send_webhook_worker, args=(merchant.webhook_url, webhook_body), daemon=True).start()


# =====================================================================
# ONE-TIME SSO TICKET STORE & EXCHANGE (ANTI-EXPOSURE SECRET KEY)
# =====================================================================
import time

_SSO_TICKETS = {}

def create_sso_ticket(merchant, name=None, phone=None, ttl_seconds=60):
    """
    Membuat One-Time SSO Ticket berdurasi 60 detik untuk pertukaran kredensial aman
    tanpa mengekspos secret key di parameter query URL browser.
    """
    now = time.time()
    # Bersihkan tiket yang sudah kedaluwarsa
    for k in list(_SSO_TICKETS.keys()):
        if _SSO_TICKETS[k].get('exp', 0) < now:
            _SSO_TICKETS.pop(k, None)

    code = secrets.token_urlsafe(32)
    _SSO_TICKETS[code] = {
        'merchant_id': merchant.merchant_id,
        'api_key': merchant.api_key,
        'secret_key': merchant.secret_key,
        'name': name or merchant.name or 'Mitra iPay',
        'phone': phone or getattr(merchant.user, 'phone', '') or '',
        'exp': now + ttl_seconds
    }
    return code

def exchange_sso_ticket(code):
    """
    Menukar One-Time SSO Ticket dengan kredensial API merchant.
    Tiket langsung hangus (sekali pakai).
    """
    if not code or code not in _SSO_TICKETS:
        return None
    data = _SSO_TICKETS.pop(code)
    if data.get('exp', 0) < time.time():
        return None
    return data


# =====================================================================
# 1-CLICK TELEGRAM AUTO-PROVISIONING ENGINE (POS -> IPAY -> TELEGRAM)
# =====================================================================

def normalize_phone_08(phone_raw):
    digits = ''.join(filter(str.isdigit, str(phone_raw or '')))
    if digits.startswith('62'):
        digits = '0' + digits[2:]
    elif digits.startswith('8'):
        digits = '0' + digits
    return digits


def send_provision_telegram_alert(prov_req):
    """
    Mengirimkan notifikasi permohonan aktivasi mitra PPOB baru dari Web POS
    ke Bot Telegram Admin lengkap dengan tombol [✅ TERIMA] dan [❌ TOLAK].
    """
    from app.services.telegram_service import (
        get_bot_admin_credentials,
        get_bot_notif_credentials,
        format_wib
    )
    token, chat_id = get_bot_admin_credentials()
    if not token or not chat_id:
        token, chat_id = get_bot_notif_credentials()
    if not token or not chat_id:
        return False, "Token/Chat ID Bot Admin belum dikonfigurasi"

    wib_str = format_wib(prov_req.created_at, fmt='%d %b %Y, %H:%M WIB')
    text = (
        "🔔 <b>PENDAFTARAN MITRA PPOB BARU (DARI WEB POS)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏪 <b>Nama Toko   :</b> {prov_req.store_name}\n"
        f"👤 <b>Pemilik     :</b> {prov_req.owner_name}\n"
        f"📱 <b>No. WA      :</b> <code>{prov_req.phone}</code>\n"
        f"🆔 <b>ID Tenant   :</b> <code>{prov_req.tenant_id or '-'}</code>\n"
        f"🔑 <b>ID Request  :</b> <code>{prov_req.request_id}</code>\n"
        "🌐 <b>Sumber      :</b> ipaypos.my.id\n"
        f"⏰ <b>Waktu       :</b> {wib_str}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Klik <b>Terima</b> untuk otomatis membuatkan akun di ipay.my.id,\n"
        "men-generate API Key, dan menyambungkannya langsung ke POS user:"
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ TERIMA & SAMBUNGKAN OTOMATIS", "callback_data": f"prov_acc_{prov_req.id}"},
                {"text": "❌ TOLAK", "callback_data": f"prov_rej_{prov_req.id}"}
            ]
        ]
    }

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": reply_markup
        }, timeout=10)
        return resp.ok, "Terkirim"
    except Exception as e:
        logger.warning(f"[PROVISION_TG] Gagal kirim alert Telegram: {e}")
        return False, str(e)


def approve_provision_request(prov_id):
    """
    Menyetujui permohonan 1-Click Auto-Provisioning:
    1. Cari atau buat User di ipay.my.id berdasarkan nomor WA
    2. Buat atau ambil kredensial MerchantApiKey (Merchant ID, API Key, Secret Key)
    3. Update status request menjadi APPROVED
    4. Kirim callback otomatis ke server POS (jika callback_url tersedia)
    """
    from app.models.merchant import MerchantProvisionRequest, ensure_merchant_provision_table
    ensure_merchant_provision_table()

    prov = MerchantProvisionRequest.query.get(prov_id)
    if not prov:
        return None, "Data permohonan tidak ditemukan"

    if prov.status == 'APPROVED' and prov.merchant_id and prov.api_key:
        return prov, None

    norm_phone = normalize_phone_08(prov.phone)
    user = User.query.filter(
        (User.phone == norm_phone) | (User.phone == prov.phone)
    ).first()

    if not user:
        display_name = f"{prov.store_name} ({prov.owner_name})" if prov.owner_name else prov.store_name
        user = User(
            name=display_name[:100],
            phone=norm_phone,
            balance=0.0,
            role='reseller',
            is_active=True
        )
        user.set_password(secrets.token_hex(8))
        db.session.add(user)
        db.session.commit()

    # Buat kredensial baru atau gunakan yang sudah aktif
    mch_name = f"POS - {prov.store_name}"[:100]
    mch, err = generate_merchant_credentials(
        user_id=user.id,
        name=mch_name,
        webhook_url=prov.webhook_url
    )
    if err or not mch:
        return None, err or "Gagal men-generate kredensial API"

    prov.status = 'APPROVED'
    prov.user_id = user.id
    prov.merchant_id = mch.merchant_id
    prov.api_key = mch.api_key
    prov.secret_key = mch.secret_key
    prov.updated_at = get_wib_datetime()
    db.session.commit()

    # Jika POS mengirimkan callback_url, tembak kredensial secara otomatis
    if prov.callback_url:
        cb_payload = {
            "status": "APPROVED",
            "request_id": prov.request_id,
            "tenant_id": prov.tenant_id,
            "store_name": prov.store_name,
            "owner_name": prov.owner_name,
            "phone": prov.phone,
            "merchant_id": prov.merchant_id,
            "api_key": prov.api_key,
            "secret_key": prov.secret_key,
            "mode": "LIVE"
        }
        Thread(target=_send_webhook_worker, args=(prov.callback_url, cb_payload), daemon=True).start()

    return prov, None


def reject_provision_request(prov_id, reason="Permohonan ditolak oleh Admin iPay."):
    from app.models.merchant import MerchantProvisionRequest, ensure_merchant_provision_table
    ensure_merchant_provision_table()

    prov = MerchantProvisionRequest.query.get(prov_id)
    if not prov:
        return None, "Data permohonan tidak ditemukan"

    prov.status = 'REJECTED'
    prov.rejection_reason = reason
    prov.updated_at = get_wib_datetime()
    db.session.commit()

    if prov.callback_url:
        cb_payload = {
            "status": "REJECTED",
            "request_id": prov.request_id,
            "tenant_id": prov.tenant_id,
            "reason": reason
        }
        Thread(target=_send_webhook_worker, args=(prov.callback_url, cb_payload), daemon=True).start()

    return prov, None

