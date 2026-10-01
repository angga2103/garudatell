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
