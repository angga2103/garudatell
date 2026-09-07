import secrets
from datetime import datetime, timezone, timedelta
from app.extensions import db
from app.models.trusted_device import TrustedDevice
from app.models.user import User
from app.models.transaction import Transaction
from app.wa_helper import kirim_wa
import logging

logger = logging.getLogger(__name__)

def now_wib():
    """Mengembalikan datetime objek dalam zona waktu WIB (UTC+7)."""
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)

def register_device_request(user, device_uuid, device_name, user_agent=None, ip_address=None, base_url=None):
    """
    Mendaftarkan atau memperbarui permintaan otorisasi perangkat kasir cabang toko.
    Hanya dapat digunakan oleh akun VIP yang aktif.
    """
    if not user or not user.is_vip_active():
        return False, None, "Fitur Kunci Kasir & Multi-Cabang hanya tersedia untuk akun VIP aktif."

    if not device_uuid or not str(device_uuid).strip():
        return False, None, "Token identitas perangkat tidak valid."

    clean_device_name = str(device_name or '').strip()
    if not clean_device_name:
        return False, None, "Nama Cabang / Perangkat kasir wajib diisi (contoh: Cabang 1 - Pasar Baru)."

    # Format info perangkat
    clean_ua = str(user_agent or 'Browser Web').strip()[:250]
    clean_ip = str(ip_address or '-').strip()[:50]

    # Generate approval token unik (berlaku 15 menit)
    approval_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(minutes=15)

    # Cek apakah device sudah ada untuk user ini
    device = TrustedDevice.query.filter_by(user_id=user.id, device_uuid=device_uuid).first()
    if device:
        # Jika sebelumnya sudah approved, perbarui nama/info tanpa mereset jika tidak diminta
        device.device_name = clean_device_name
        device.device_info = clean_ua
        device.ip_address = clean_ip
        device.approval_token = approval_token
        device.approval_expires_at = expires_at
        device.status = 'pending'
    else:
        device = TrustedDevice(
            user_id=user.id,
            device_uuid=device_uuid,
            device_name=clean_device_name,
            device_info=clean_ua,
            ip_address=clean_ip,
            status='pending',
            approval_token=approval_token,
            approval_expires_at=expires_at,
            created_at=datetime.utcnow()
        )
        db.session.add(device)

    db.session.commit()

    # Kirim notifikasi WhatsApp interaktif 1-klik ke Owner
    domain = (base_url or 'https://ipay.my.id').rstrip('/')
    approve_url = f"{domain}/vip/device/approve/{approval_token}"
    reject_url = f"{domain}/vip/device/reject/{approval_token}"

    wib_str = now_wib().strftime('%d-%m-%Y %H:%M WIB')

    pesan_wa = (
        f"🦅 *[GARUDATELL - OTORISASI KASIR CABANG]*\n\n"
        f"Halo *{user.name}*, ada permintaan pendaftaran perangkat kasir baru untuk toko Anda:\n\n"
        f"🏪 *Nama Cabang:* {clean_device_name}\n"
        f"💻 *Perangkat:* {clean_ua[:80]}\n"
        f"🌐 *Alamat IP:* {clean_ip}\n"
        f"⏰ *Waktu:* {wib_str}\n\n"
        f"Apakah Anda mengizinkan perangkat ini melakukan transaksi menggunakan *Saldo Toko* Anda?\n\n"
        f"✅ *SETUJUI PERANGKAT (1-KLIK):*\n"
        f"{approve_url}\n\n"
        f"❌ *TOLAK PERANGKAT:*\n"
        f"{reject_url}\n\n"
        f"⚠️ _Tautan persetujuan ini berlaku selama 15 menit. Hanya setujui jika perangkat ini adalah staf/kasir resmi toko Anda._"
    )

    try:
        wa_sent = kirim_wa(user.phone, pesan_wa)
        if not wa_sent:
            logger.warning(f"[-] Bot WA gagal mengirim pesan otorisasi ke {user.phone}")
    except Exception as e:
        logger.error(f"[-] Error kirim WA otorisasi kasir: {e}")

    return True, device, "Permintaan izin telah dikirim ke WhatsApp Owner toko. Menunggu persetujuan..."

def approve_device_by_token(token):
    """
    Otorisasi perangkat kasir via tautan 1-klik dari WhatsApp Owner.
    """
    if not token:
        return False, None, "Token persetujuan tidak valid."

    device = TrustedDevice.query.filter_by(approval_token=token).first()
    if not device:
        return False, None, "Tautan persetujuan tidak valid atau sudah pernah digunakan."

    if device.is_token_expired():
        return False, device, "Tautan persetujuan telah kedaluwarsa (lebih dari 15 menit). Silakan ajukan ulang dari perangkat kasir."

    device.status = 'approved'
    device.approved_at = datetime.utcnow()
    device.approval_token = None  # Reset token agar tidak bisa digunakan berulang

    # Aktifkan lock kasir akun secara otomatis jika belum aktif
    owner = User.query.get(device.user_id)
    if owner and not owner.is_device_lock_enabled:
        owner.is_device_lock_enabled = True

    db.session.commit()
    return True, device, f"Perangkat kasir '{device.device_name}' berhasil disetujui resmi! Perangkat ini sekarang dapat bertransaksi menggunakan saldo toko."

def reject_device_by_token(token):
    """
    Menolak perangkat kasir via tautan 1-klik dari WhatsApp Owner.
    """
    if not token:
        return False, None, "Token penolakan tidak valid."

    device = TrustedDevice.query.filter_by(approval_token=token).first()
    if not device:
        return False, None, "Tautan tidak valid atau sudah diproses."

    device.status = 'rejected'
    device.approval_token = None
    db.session.commit()
    return True, device, f"Perangkat kasir '{device.device_name}' telah ditolak."

def approve_device_manual(user_id, device_id):
    """
    Persetujuan manual langsung oleh Owner dari dashboard web VIP.
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, "Perangkat kasir tidak ditemukan."

    device.status = 'approved'
    device.approved_at = datetime.utcnow()
    device.approval_token = None

    owner = User.query.get(user_id)
    if owner and not owner.is_device_lock_enabled:
        owner.is_device_lock_enabled = True

    db.session.commit()
    return True, f"Perangkat '{device.device_name}' berhasil disetujui."

def revoke_device(user_id, device_id):
    """
    Mencabut izin perangkat kasir oleh Owner dari dashboard.
    """
    device = TrustedDevice.query.filter_by(id=device_id, user_id=user_id).first()
    if not device:
        return False, "Perangkat kasir tidak ditemukan."

    device.status = 'revoked'
    device.approval_token = None
    db.session.commit()
    return True, f"Akses transaksi untuk '{device.device_name}' berhasil dicabut."

def toggle_device_lock(user, enabled):
    """
    Mengaktifkan atau menonaktifkan sakelar proteksi Kunci Kasir Toko.
    """
    if not user or not user.is_vip_active():
        return False, "Hanya akun VIP aktif yang dapat mengatur proteksi Kunci Kasir."

    user.is_device_lock_enabled = bool(enabled)
    db.session.commit()
    status_str = "diaktifkan" if enabled else "dinonaktifkan"
    return True, f"Proteksi Kunci Kasir Toko berhasil {status_str}."

def verify_device_for_transaction(user, device_uuid):
    """
    Memeriksa izin transaksi Saldo berdasarkan aturan Kunci Perangkat Kasir.
    - Jika user bukan VIP atau is_device_lock_enabled == False: lolos tanpa proteksi.
    - Jika user VIP dan is_device_lock_enabled == True: WAJIB lolos verifikasi approved device.
    Mengembalikan (allowed: bool, device_obj: TrustedDevice, error_message: str)
    """
    if not user or not user.is_vip_active():
        return True, None, None

    if not user.is_device_lock_enabled:
        # Jika fitur kunci kasir tidak diaktifkan oleh Owner, transaksi diizinkan
        # Namun jika ada cookie device approved, tetap kita catat device-nya untuk laporan
        if device_uuid:
            dev = TrustedDevice.query.filter_by(user_id=user.id, device_uuid=device_uuid, status='approved').first()
            if dev:
                dev.last_used_at = datetime.utcnow()
                db.session.commit()
                return True, dev, None
        return True, None, None

    # Proteksi AKTIF: Wajib ada token perangkat
    if not device_uuid:
        return False, None, "Transaksi Saldo Ditolak: Fitur Kunci Kasir Toko Aktif. Perangkat ini belum diotorisasi resmi oleh Owner toko."

    device = TrustedDevice.query.filter_by(user_id=user.id, device_uuid=device_uuid).first()
    if not device:
        return False, None, "Transaksi Saldo Ditolak: Perangkat ini belum terdaftar sebagai Kasir Resmi Toko. Hubungi Owner untuk pendaftaran."

    if device.status != 'approved':
        status_map = {
            'pending': 'Menunggu Persetujuan Owner Toko',
            'rejected': 'Ditolak oleh Owner Toko',
            'revoked': 'Akses Toko Telah Dicabut oleh Owner'
        }
        status_desc = status_map.get(device.status, device.status)
        return False, device, f"Transaksi Saldo Ditolak: Perangkat kasir ini berstatus [{status_desc}]. Transaksi tidak diizinkan."

    # Perangkat valid dan disetujui
    device.last_used_at = datetime.utcnow()
    db.session.commit()
    return True, device, None

def get_branch_usage_report(user_id, period='today'):
    """
    Menghasilkan data agregasi pemakaian saldo deposit per cabang toko dan riwayat transaksi.
    """
    from sqlalchemy import func

    now = now_wib()
    query = Transaction.query.filter(
        Transaction.user_id == user_id,
        Transaction.payment_method == 'SALDO'
    )

    if period == 'today':
        wib_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        utc_start = wib_start - timedelta(hours=7)
        query = query.filter(Transaction.created_at >= utc_start)
    elif period == 'month':
        wib_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        utc_start = wib_start - timedelta(hours=7)
        query = query.filter(Transaction.created_at >= utc_start)

    transactions = query.order_by(Transaction.created_at.desc()).all()

    # Rekapitulasi per nama cabang
    branch_map = {}
    total_trx = 0
    total_amount = 0.0

    for trx in transactions:
        b_name = trx.device_name or 'Perangkat Utama / Tanpa Nama'
        if b_name not in branch_map:
            branch_map[b_name] = {
                'branch_name': b_name,
                'total_trx': 0,
                'success_trx': 0,
                'total_spent': 0.0,
                'last_time': trx.created_at_wib
            }
        branch_map[b_name]['total_trx'] += 1
        if trx.status == 'SUCCESS':
            branch_map[b_name]['success_trx'] += 1
        branch_map[b_name]['total_spent'] += float(trx.amount or 0)

        total_trx += 1
        total_amount += float(trx.amount or 0)

    # Urutkan cabang berdasarkan total pemakaian saldo tertinggi
    branches = sorted(branch_map.values(), key=lambda x: x['total_spent'], reverse=True)

    return {
        'total_trx': total_trx,
        'total_amount': total_amount,
        'branches': branches,
        'recent_transactions': transactions[:30]
    }

