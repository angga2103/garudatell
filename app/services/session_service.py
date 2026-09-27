import secrets
from datetime import datetime, timedelta
from app.extensions import db
from app.models.user import User
from app.models.device_session_log import DeviceSessionLog
from app.wa_helper import kirim_wa

def parse_device_info(user_agent_str):
    """Mengekstrak informasi perangkat yang mudah dibaca dari User-Agent string."""
    if not user_agent_str:
        return "Perangkat Web"
    
    ua = str(user_agent_str)
    os_name = "Perangkat Lain"
    browser = "Browser"

    # Deteksi OS
    if "Android" in ua:
        os_name = "Android"
    elif "iPhone" in ua:
        os_name = "iPhone"
    elif "iPad" in ua:
        os_name = "iPad"
    elif "Windows" in ua:
        os_name = "Windows PC"
    elif "Macintosh" in ua or "Mac OS" in ua:
        os_name = "Mac"
    elif "Linux" in ua:
        os_name = "Linux PC"

    # Deteksi Browser
    if "Edg/" in ua or "Edge/" in ua:
        browser = "Edge"
    elif "Chrome/" in ua and "Mobile" in ua:
        browser = "Chrome Mobile"
    elif "Chrome/" in ua:
        browser = "Chrome"
    elif "Safari/" in ua and "Chrome" not in ua:
        browser = "Safari"
    elif "Firefox/" in ua:
        browser = "Firefox"
    elif "Opera" in ua or "OPR/" in ua:
        browser = "Opera"

    return f"{os_name} ({browser})"

def get_client_ip(req):
    """Mengambil alamat IP pengguna dengan aman melalui proxy/Cloudflare/Nginx."""
    if not req:
        return "127.0.0.1"
    x_forwarded = req.headers.get('X-Forwarded-For')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return req.remote_addr or "127.0.0.1"

def log_session_event(user_id, phone, event_type, device_name=None, ip_address=None, details=None):
    """Mencatat aktivitas audit sesi ke tabel device_session_log."""
    try:
        log = DeviceSessionLog(
            user_id=user_id,
            phone=phone,
            event_type=event_type,
            device_name=str(device_name or '')[:150],
            ip_address=str(ip_address or '')[:50],
            details=details,
            created_at=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
        return True
    except Exception as e:
        db.session.rollback()
        return False

def adopt_session_gracefully(user, req, sess):
    """
    Mengadopsi sesi pengguna aktif secara mulus jika database belum memiliki token (Zero Disruption).
    Pengguna yang sedang login saat update TIDAK akan ter-logout.
    """
    try:
        new_token = secrets.token_hex(32)
        user.current_session_token = new_token
        user.last_active_at = datetime.utcnow()
        user.active_device_name = parse_device_info(req.headers.get('User-Agent'))
        user.active_device_ip = get_client_ip(req)
        
        # Simpan device_uuid jika dikirimkan oleh browser atau generate baru
        device_uuid = sess.get('device_uuid') or req.headers.get('X-Device-UUID') or secrets.token_hex(16)
        user.active_device_uuid = device_uuid
        
        db.session.commit()
        
        sess['session_token'] = new_token
        sess['device_uuid'] = device_uuid
        
        # Catat event adopsi sesi
        log_session_event(
            user_id=user.id,
            phone=user.phone,
            event_type='LOGIN',
            device_name=user.active_device_name,
            ip_address=user.active_device_ip,
            details='Sesi aktif produksi berhasil diadopsi otomatis (Zero Disruption)'
        )
        return new_token
    except Exception as e:
        db.session.rollback()
        return None

def is_session_expired_inactivity(user, timeout_hours=23):
    """Memeriksa apakah sesi telah kedaluwarsa setelah tidak aktif selama timeout_hours (default 23 jam)."""
    if not user.last_active_at:
        return False
    delta = datetime.utcnow() - user.last_active_at
    return delta.total_seconds() > timeout_hours * 3600

def revoke_user_session(user, reason='ADMIN_KICKOUT', actor_name=None):
    """Memutus sesi aktif pengguna (Kick Out / Reset Sesi)."""
    if not user:
        return False, "Pengguna tidak ditemukan."
    
    old_device = user.active_device_name or "Tidak diketahui"
    old_ip = user.active_device_ip or "-"
    
    user.current_session_token = None
    user.last_active_at = None
    user.active_device_uuid = None
    
    details_msg = f"Sesi diputus oleh {actor_name or 'Sistem'}. Perangkat sebelumnya: {old_device} ({old_ip})"
    log_session_event(
        user_id=user.id,
        phone=user.phone,
        event_type=reason,
        device_name=old_device,
        ip_address=old_ip,
        details=details_msg
    )
    
    db.session.commit()
    return True, "Sesi akun berhasil diputus. Akun kini dalam keadaan bebas login."

def send_emergency_switch_otp(user, req):
    """Mengirim kode OTP darurat pemindahan perangkat ke WhatsApp pemilik akun."""
    from app.services.otp_service import create_otp
    otp_code = create_otp(user.phone, action='emergency_switch', username=user.name)
    
    new_device = parse_device_info(req.headers.get('User-Agent'))
    new_ip = get_client_ip(req)
    
    pesan = (
        f"🚨 *[PERINGATAN KEAMANAN GARUDATEL]*\n\n"
        f"Halo *{user.name}*,\n"
        f"Permintaan *PEMINDAHAN PERANGKAT AKUN* terdeteksi menuju:\n"
        f"📱 Perangkat: *{new_device}*\n"
        f"🌐 Alamat IP: *{new_ip}*\n\n"
        f"Kode OTP Pemindahan Akun Anda adalah:\n"
        f"👉 *{otp_code}*\n\n"
        f"⚠️ *PENTING*: Jika Anda tidak merasa melakukan pemindahan perangkat ini, "
        f"JANGAN berikan kode ini kepada siapapun dan segera hubungi Admin untuk mengamankan saldo Anda!"
    )
    
    from flask import current_app
    if current_app.config.get('TESTING'):
        return True, otp_code

    terkirim = kirim_wa(user.phone, pesan)
    return terkirim, otp_code

def send_switch_success_notification(user, new_device, new_ip):
    """Mengirim pesan notifikasi bahwa akun telah resmi dipindahkan ke perangkat baru."""
    from flask import current_app
    if current_app.config.get('TESTING'):
        return True

    wib_now = (datetime.utcnow() + timedelta(hours=7)).strftime('%d-%m-%Y %H:%M WIB')
    pesan = (
        f"⚠️ *[PEMBERITAHUAN KEAMANAN GARUDATEL]*\n\n"
        f"Halo *{user.name}*,\n"
        f"Akun Anda telah *RESMI DIPINDAHKAN* ke perangkat baru:\n"
        f"📱 Perangkat: *{new_device}*\n"
        f"🌐 Alamat IP: *{new_ip}*\n"
        f"⏰ Waktu: *{wib_now}*\n\n"
        f"🔒 *Perangkat sebelumnya telah di-logout otomatis secara instan.*\n"
        f"Jika ini bukan Anda, segera hubungi Admin GarudaTel untuk penguncian akun darurat."
    )
    try:
        kirim_wa(user.phone, pesan)
    except Exception:
        pass
