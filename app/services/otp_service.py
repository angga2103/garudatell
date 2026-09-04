from app.extensions import db
from app.models.otp import OtpCode
import random
import time
import json
import os
import logging

logger = logging.getLogger(__name__)
BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
LEGACY_JSON_PATH = os.path.join(BASE_DIR, 'otp_database.json')

def get_phone_variants(phone):
    """Menghasilkan variasi format nomor HP lokal Indonesia (08... dan 628...)."""
    clean = ''.join(filter(str.isdigit, str(phone)))
    variants = [clean]
    if clean.startswith('0'):
        variants.append('62' + clean[1:])
    elif clean.startswith('62'):
        variants.append('0' + clean[2:])
    return list(set(variants))

def create_otp(phone, action='register', username=None, password_hash=None, expiry_seconds=900):
    """
    Generate kode OTP 6-digit dan simpan ke tabel database OtpCode.
    Juga menuliskan mirror ke otp_database.json untuk kompatibilitas.
    """
    clean_phone = ''.join(filter(str.isdigit, str(phone)))
    phone_variants = get_phone_variants(clean_phone)
    otp_code = str(random.randint(100000, 999999))
    expires_at = time.time() + expiry_seconds

    try:
        # Jika ini OTP Darurat Manual dan user_data kosong, warisi data username/password dari registrasi pending
        if action == 'manual' and not username and not password_hash:
            last_pending = OtpCode.query.filter(OtpCode.phone.in_(phone_variants)).order_by(OtpCode.id.desc()).first()
            if last_pending:
                username = username or last_pending.username
                password_hash = password_hash or last_pending.password_hash

        # Nonaktifkan OTP lama yang belum terpakai untuk variasi nomor ini
        old_otps = OtpCode.query.filter(OtpCode.phone.in_(phone_variants), OtpCode.is_used == False).all()
        for old in old_otps:
            old.is_used = True

        new_otp = OtpCode(
            phone=clean_phone,
            otp_code=otp_code,
            action=action,
            username=username,
            password_hash=password_hash,
            expires_at=expires_at,
            is_used=False
        )
        db.session.add(new_otp)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"[OTP Service] Gagal simpan ke DB: {e}")

    # Mirror ke JSON untuk redundansi dan fallback kompatibilitas
    try:
        otp_data = {}
        if os.path.exists(LEGACY_JSON_PATH):
            try:
                with open(LEGACY_JSON_PATH, 'r') as f:
                    otp_data = json.load(f)
            except Exception:
                otp_data = {}

        for p_var in phone_variants:
            otp_data[p_var] = {
                'otp': otp_code,
                'expiry': expires_at,
                'action': action,
                'username': username,
                'password_hash': password_hash
            }
        with open(LEGACY_JSON_PATH, 'w') as f:
            json.dump(otp_data, f)
    except Exception as e:
        logger.warning(f"[OTP Service] Gagal mirror ke JSON: {e}")

    return otp_code


def verify_otp(phone, otp_input, action=None):
    """
    Verifikasi kode OTP pengguna.
    Mendukung OTP darurat manual (action='manual') sebagai universal override.
    Mengembalikan tuple: (is_valid: bool, message: str, user_data: dict)
    """
    clean_phone = ''.join(filter(str.isdigit, str(phone)))
    phone_variants = get_phone_variants(clean_phone)
    otp_input_str = str(otp_input).strip()

    if not otp_input_str:
        return False, "Masukkan kode OTP!", {}

    # 1. Cek di Database OtpCode terlebih dahulu
    try:
        from sqlalchemy import or_
        query = OtpCode.query.filter(OtpCode.phone.in_(phone_variants), OtpCode.is_used == False)
        if action:
            # Mengizinkan OTP dengan action yang sesuai ATAU OTP darurat manual (master override)
            query = query.filter(or_(OtpCode.action == action, OtpCode.action == 'manual'))
        latest_otp = query.order_by(OtpCode.id.desc()).first()

        if latest_otp:
            if latest_otp.is_expired():
                return False, "Kode OTP sudah kedaluwarsa. Silakan minta ulang.", {}

            if latest_otp.otp_code != otp_input_str:
                return False, "Kode OTP salah!", {}

            # OTP Benar -> Tandai terpakai
            latest_otp.is_used = True
            db.session.commit()

            # Hapus juga dari mirror JSON jika ada
            for p_var in phone_variants:
                _cleanup_legacy_json(p_var)

            return True, "Verifikasi berhasil!", {
                'username': latest_otp.username,
                'password_hash': latest_otp.password_hash,
                'action': latest_otp.action
            }
    except Exception as e:
        db.session.rollback()
        logger.error(f"[OTP Service] Error saat query DB: {e}")

    # 2. Fallback: Cek di legacy JSON jika tidak ditemukan di DB
    if os.path.exists(LEGACY_JSON_PATH):
        try:
            with open(LEGACY_JSON_PATH, 'r') as f:
                otp_data = json.load(f)
        except Exception:
            otp_data = {}

        entry = otp_data.get(clean_phone)
        if entry:
            if time.time() > entry.get('expiry', 0):
                return False, "Kode OTP sudah kedaluwarsa. Silakan minta ulang.", {}

            if str(entry.get('otp')) != otp_input_str:
                return False, "Kode OTP salah!", {}

            # Valid -> Hapus dari JSON
            del otp_data[clean_phone]
            try:
                with open(LEGACY_JSON_PATH, 'w') as f:
                    json.dump(otp_data, f)
            except Exception:
                pass

            return True, "Verifikasi berhasil!", {
                'username': entry.get('username'),
                'password_hash': entry.get('password_hash'),
                'action': entry.get('action', action)
            }

    return False, "OTP tidak ditemukan atau Anda belum meminta OTP.", {}


def _cleanup_legacy_json(phone):
    """Menghapus nomor yang sudah diverifikasi dari file JSON cadangan."""
    if os.path.exists(LEGACY_JSON_PATH):
        try:
            with open(LEGACY_JSON_PATH, 'r') as f:
                otp_data = json.load(f)
            if phone in otp_data:
                del otp_data[phone]
                with open(LEGACY_JSON_PATH, 'w') as f:
                    json.dump(otp_data, f)
        except Exception:
            pass

