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

def dispatch_merchant_webhook(merchant, payload, sync=False):
    """
    Mengirimkan notifikasi callback ke URL Webhook Merchant (POS IPAY).
    Jika sync=True, mengembalikan tuple (ok: bool, status_code: int, message: str).
    """
    if not merchant or not merchant.webhook_url:
        return (False, 0, "URL Webhook belum dikonfigurasi pada merchant ini") if sync else None

    ref_val = payload.get('ref_id', '')
    sign = hashlib.md5(f"{merchant.merchant_id}{merchant.secret_key}{ref_val}".encode()).hexdigest()
    webhook_body = {
        "event": payload.get("event", "transaction.updated"),
        "merchant_id": merchant.merchant_id,
        "ref_id": ref_val,
        "status": payload.get("status"), # 'success', 'failed', 'pending'
        "sn": payload.get("sn", ""),
        "buyer_sku_code": payload.get("sku_code", ""),
        "price": payload.get("price", 0),
        "balance": payload.get("balance"),
        "reason": payload.get("reason"),
        "sign": sign
    }

    if sync:
        try:
            resp = requests.post(
                merchant.webhook_url,
                json=webhook_body,
                headers={'Content-Type': 'application/json'},
                timeout=8
            )
            return (200 <= resp.status_code < 300), resp.status_code, (resp.text or "")[:180]
        except Exception as e:
            return False, 0, str(e)

    Thread(target=_send_webhook_worker, args=(merchant.webhook_url, webhook_body), daemon=True).start()
    return None


def ping_merchant_webhook(merchant):
    """
    Mengecek kesehatan koneksi (Health Check) ke endpoint webhook POS kasir.
    Mengembalikan tuple (ok: bool, latency_ms: int, message: str).
    """
    if not merchant or not merchant.webhook_url:
        return False, 0, "URL Webhook belum diatur"
    import time as _t
    t0 = _t.time()
    sign = hashlib.md5(f"{merchant.merchant_id}{merchant.secret_key}ping".encode()).hexdigest()
    payload = {
        "event": "ping",
        "merchant_id": merchant.merchant_id,
        "status": "ok",
        "sign": sign
    }
    try:
        resp = requests.post(merchant.webhook_url, json=payload, headers={'Content-Type': 'application/json'}, timeout=6)
        latency = int((_t.time() - t0) * 1000)
        if 200 <= resp.status_code < 400:
            return True, latency, f"HTTP {resp.status_code} ({latency} ms)"
        return False, latency, f"HTTP {resp.status_code}: {(resp.text or '')[:100]}"
    except Exception as e:
        latency = int((_t.time() - t0) * 1000)
        return False, latency, f"Gagal terhubung: {str(e)[:120]}"


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
        format_wib,
        call_telegram_api
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
        resp = call_telegram_api('post', f"bot{token}/sendMessage", json={
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
            "event": "provision.updated",
            "status": "REJECTED",
            "request_id": prov.request_id,
            "tenant_id": prov.tenant_id,
            "reason": reason
        }
        Thread(target=_send_webhook_worker, args=(prov.callback_url, cb_payload), daemon=True).start()

    return prov, None


def push_credentials_to_pos(merchant):
    """
    Menyinkronkan / meng-inject ulang kredensial Merchant (Merchant ID, API Key, Secret Key)
    ke server POS (ipaypos.my.id) baik melalui tabel MerchantProvisionRequest maupun push webhook/callback.
    Mengembalikan tuple (ok: bool, message: str).
    """
    if not merchant:
        return False, "Merchant tidak ditemukan"

    from app.models.merchant import MerchantProvisionRequest, ensure_merchant_provision_table
    ensure_merchant_provision_table()

    user = merchant.user
    norm_phone = normalize_phone_08(user.phone) if user and user.phone else ""

    # Cari record provisioning terkait merchant_id atau user_id atau phone
    prov = MerchantProvisionRequest.query.filter(
        (MerchantProvisionRequest.merchant_id == merchant.merchant_id) |
        (MerchantProvisionRequest.user_id == merchant.user_id) |
        ((MerchantProvisionRequest.phone == norm_phone) if norm_phone else False)
    ).order_by(MerchantProvisionRequest.id.desc()).first()

    target_urls = []
    if prov:
        prov.status = 'APPROVED'
        prov.merchant_id = merchant.merchant_id
        prov.api_key = merchant.api_key
        prov.secret_key = merchant.secret_key
        if merchant.webhook_url:
            prov.webhook_url = merchant.webhook_url
        prov.updated_at = get_wib_datetime()
        db.session.commit()
        if prov.callback_url:
            target_urls.append(prov.callback_url)

    if merchant.webhook_url and merchant.webhook_url not in target_urls:
        target_urls.append(merchant.webhook_url)

    resolved_tenant = (prov.tenant_id if prov and prov.tenant_id else None) or (merchant.get_tenant_id() if hasattr(merchant, 'get_tenant_id') else None)
    m_key = getattr(merchant, 'master_recovery_key', None)

    # Tambahkan localhost port 3001 untuk memastikan sinyal sampai jika di VPS yang sama
    local_pos_url = f"http://127.0.0.1:3001/api/ppob/webhook?tenant_id={resolved_tenant}"
    if local_pos_url not in target_urls:
        target_urls.append(local_pos_url)

    payload = {
        "event": "credentials.synced",
        "status": "APPROVED",
        "request_id": prov.request_id if prov else f"SYNC_{merchant.merchant_id}",
        "tenant_id": resolved_tenant,
        "store_name": merchant.name,
        "owner_name": user.name if user else merchant.name,
        "phone": norm_phone,
        "merchant_id": merchant.merchant_id,
        "api_key": merchant.api_key,
        "secret_key": merchant.secret_key,
        "mode": "LIVE",
        "master_key": m_key,
        "recovery_key": m_key,
        "credentials": {
            "merchant_id": merchant.merchant_id,
            "api_key": merchant.api_key,
            "secret_key": merchant.secret_key,
            "mode": "LIVE",
            "master_key": m_key,
            "recovery_key": m_key
        }
    }

    pushed_ok = False
    last_detail = "Tersimpan di antrean Auto-Provisioning (Siap ditarik POS)"
    for url in target_urls:
        try:
            resp = requests.post(url, json=payload, headers={'Content-Type': 'application/json'}, timeout=6)
            if 200 <= resp.status_code < 400:
                pushed_ok = True
                last_detail = f"Push sukses ke {url} (HTTP {resp.status_code})"
            else:
                last_detail = f"Respon {url}: HTTP {resp.status_code}"
        except Exception as e:
            last_detail = f"Gagal push langsung ke {url}: {str(e)[:80]}"

    return True, last_detail


def dispatch_pos_broadcast(broadcast_obj):
    """
    Mengirimkan push pengumuman / broadcast ke seluruh (atau satu) webhook kasir POS aktif.
    """
    if not broadcast_obj or not broadcast_obj.is_active:
        return

    query = MerchantApiKey.query.filter_by(is_active=True)
    if broadcast_obj.target_merchant_id and broadcast_obj.target_merchant_id != 'ALL':
        query = query.filter_by(merchant_id=broadcast_obj.target_merchant_id)

    merchants = query.all()
    for m in merchants:
        if not m.webhook_url:
            continue
        sign = hashlib.md5(f"{m.merchant_id}{m.secret_key}{broadcast_obj.id}".encode()).hexdigest()
        payload = {
            "event": "pos.broadcast",
            "merchant_id": m.merchant_id,
            "broadcast": {
                "id": broadcast_obj.id,
                "title": broadcast_obj.title,
                "message": broadcast_obj.message,
                "level": broadcast_obj.level,
                "target_merchant_id": broadcast_obj.target_merchant_id or "ALL",
                "created_at": broadcast_obj.formatted_created_at
            },
            "sign": sign
        }
        Thread(target=_send_webhook_worker, args=(m.webhook_url, payload), daemon=True).start()

