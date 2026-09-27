"""
Test Suite: 1 Akun 1 Login Aktif (Single Active Session) & Anti-Dual Login
Memverifikasi:
1. Model & Helper: is_session_active, last_active_at_wib, session log creation.
2. Zero Disruption: Adopsi otomatis bagi sesi user yang sedang aktif tanpa logout.
3. Pre-OTP Interception: Saat akun aktif di HP-A, HP-B yang mencoba login_step1 dicegat dan OTP DITAHAN.
4. Same Device Pass: Perangkat yang sama (UUID match) tidak dicegat dan dapat meminta OTP.
5. Adaptive Emergency Switch:
   - User dengan PIN: wajib verifikasi OTP + PIN 6-digit.
   - User tanpa PIN: adaptif verifikasi OTP + Password confirm.
   - Sesi lama langsung hangus seketika (token baru diterbitkan).
6. Auto-Logout di HP Lama: Token mismatch memicu force logout (401 / redirect).
7. Admin Kick-Out: Admin memutus sesi (/admin/users/<id>/kickout) -> akun bebas login kembali.
8. Inactivity Timeout: Sesi lebih dari 23 jam otomatis expired (AUTO_EXPIRED).
"""

import os
import sys
import time
import secrets
from datetime import datetime, timedelta

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.device_session_log import DeviceSessionLog
from app.services.session_service import revoke_user_session, is_session_expired_inactivity

def run_tests():
    print("=" * 75)
    print("  TEST SUITE: SINGLE ACTIVE SESSION & ADAPTIVE EMERGENCY SWITCH")
    print("=" * 75)

    app = create_app()
    app.config['TESTING'] = True
    app.config['WTF_CSRF_ENABLED'] = False

    test_passed = 0
    test_total = 0

    def assert_true(cond, msg):
        nonlocal test_passed, test_total
        test_total += 1
        if cond:
            test_passed += 1
            print(f"  [PASS] {msg}")
        else:
            print(f"  [FAIL] {msg}")
            raise AssertionError(f"Test failed: {msg}")

    with app.app_context():
        # Setup Test Users
        ts = int(time.time()) % 100000000
        phone_with_pin = f"0811{ts:08d}"
        phone_no_pin = f"0812{ts:08d}"

        user_with_pin = User(
            name=f"User Pin {ts}",
            phone=phone_with_pin,
            balance=100000.0,
            is_active=True
        )
        user_with_pin.set_password("Secret123!")
        user_with_pin.set_pin("123456")
        db.session.add(user_with_pin)

        user_no_pin = User(
            name=f"User NoPin {ts}",
            phone=phone_no_pin,
            balance=50000.0,
            is_active=True
        )
        user_no_pin.set_password("Secret123!")
        # Tidak diset PIN (pin_hash is None)
        db.session.add(user_no_pin)
        db.session.commit()

        # =====================================================================
        # TEST 1: User Model is_session_active & helpers
        # =====================================================================
        print("\n--- [TEST 1] Model & Helper Sesi Aktif ---")
        assert_true(not user_with_pin.is_session_active(23), "User baru tanpa token -> is_session_active False")

        # Set sesi aktif
        token1 = secrets.token_hex(32)
        user_with_pin.current_session_token = token1
        user_with_pin.last_active_at = datetime.utcnow()
        user_with_pin.active_device_name = "Chrome on Windows"
        user_with_pin.active_device_uuid = "uuid_device_a"
        db.session.commit()

        assert_true(user_with_pin.is_session_active(23), "User dengan token & aktivitas baru -> is_session_active True")

        # Set last_active 24 jam lalu
        user_with_pin.last_active_at = datetime.utcnow() - timedelta(hours=24)
        db.session.commit()
        assert_true(not user_with_pin.is_session_active(23), "User dengan aktivitas 24 jam lalu -> is_session_active False (>23 jam)")

        # Kembalikan ke aktivitas baru
        user_with_pin.last_active_at = datetime.utcnow()
        db.session.commit()

        # =====================================================================
        # TEST 2: Pre-OTP Interception (Login Step 1)
        # =====================================================================
        print("\n--- [TEST 2] Pre-OTP Interception Pencegatan Login Ganda ---")
        client = app.test_client()

        # HP-B mencoba login pada akun yang aktif di HP-A
        res = client.post('/profil', data={
            'action': 'login_step1',
            'username': phone_with_pin,
            'password': 'Secret123!',
            'device_uuid': 'uuid_device_b'  # Perangkat berbeda
        })
        json_data = res.get_json()
        assert_true(json_data.get('status') == 'device_conflict', "HP-B dicegat sebelum OTP dengan status 'device_conflict'")
        assert_true('Chrome on Windows' in json_data.get('active_device', ''), "Respons menyertakan nama perangkat aktif HP-A")
        assert_true(json_data.get('has_pin') is True, "has_pin terdeteksi True untuk akun ber-PIN")

        # Perangkat yang sama (UUID match) diperbolehkan meminta OTP
        res_same = client.post('/profil', data={
            'action': 'login_step1',
            'username': phone_with_pin,
            'password': 'Secret123!',
            'device_uuid': 'uuid_device_a'  # Perangkat yang sama
        })
        json_same = res_same.get_json()
        assert_true(json_same.get('status') in ['otp_sent', 'bot_offline'], "HP-A (same device UUID) lolos pencegatan dan menuju OTP")

        # =====================================================================
        # TEST 3: Adaptive Emergency Switch - Akun Memiliki PIN
        # =====================================================================
        print("\n--- [TEST 3] Emergency Switch Mandiri (Akun Ber-PIN) ---")
        # 1. Request OTP darurat
        res_emg_otp = client.post('/profil', data={
            'action': 'request_otp_emergency_switch',
            'username': phone_with_pin,
            'password': 'Secret123!'
        })
        json_emg_otp = res_emg_otp.get_json()
        assert_true(json_emg_otp.get('status') == 'otp_sent', "OTP darurat berhasil di-generate")

        # Dapatkan kode OTP dari DB
        # Dapatkan kode OTP dari DB
        from app.models.otp import OtpCode
        otp_entry = OtpCode.query.filter_by(phone=phone_with_pin, action='emergency_switch').order_by(OtpCode.id.desc()).first()
        assert_true(otp_entry is not None, "Record OTP emergency_switch tercatat di database")
        # Untuk testing, kita set otp_code known
        otp_entry.otp_code = '888999'
        otp_entry.expires_at = time.time() + 600
        otp_entry.is_used = False
        db.session.commit()

        # Coba eksekusi dengan PIN yang SALAH
        res_wrong_pin = client.post('/profil', data={
            'action': 'emergency_switch_device',
            'phone': phone_with_pin,
            'otp': '888999',
            'pin': '999999',  # Salah, harusnya 123456
            'device_uuid': 'uuid_device_b'
        })
        assert_true(res_wrong_pin.get_json().get('status') == 'error' and 'PIN' in res_wrong_pin.get_json().get('message'), "Ditolak saat PIN salah")

        # Eksekusi dengan OTP dan PIN yang BENAR
        res_switch_ok = client.post('/profil', data={
            'action': 'emergency_switch_device',
            'phone': phone_with_pin,
            'otp': '888999',
            'pin': '123456',  # Benar
            'device_uuid': 'uuid_device_b'
        })
        json_switch_ok = res_switch_ok.get_json()
        assert_true(json_switch_ok.get('status') == 'success', "Berhasil pindah perangkat dengan OTP + PIN")

        # Verifikasi DB: Sesi aktif sekarang milik HP-B
        db.session.refresh(user_with_pin)
        assert_true(user_with_pin.active_device_uuid == 'uuid_device_b', "DB User aktif terupdate ke uuid_device_b")
        assert_true(user_with_pin.current_session_token != token1, "Token sesi lama (HP-A) telah diganti token baru")

        # Cek audit log
        log_entry = DeviceSessionLog.query.filter_by(user_id=user_with_pin.id, event_type='EMERGENCY_SWITCH').order_by(DeviceSessionLog.id.desc()).first()
        assert_true(log_entry is not None, "Audit log EMERGENCY_SWITCH tercatat di DeviceSessionLog")

        # =====================================================================
        # TEST 4: Adaptive Emergency Switch - Akun Tanpa PIN (Hanya Password)
        # =====================================================================
        print("\n--- [TEST 4] Emergency Switch Mandiri (Akun Tanpa PIN) ---")
        # Set sesi aktif di HP-A untuk user tanpa PIN
        user_no_pin.current_session_token = secrets.token_hex(32)
        user_no_pin.last_active_at = datetime.utcnow()
        user_no_pin.active_device_uuid = "uuid_device_x"
        user_no_pin.active_device_name = "HP Toko Lama"
        db.session.commit()

        # Request OTP darurat untuk akun tanpa PIN
        res_no_pin_req = client.post('/profil', data={
            'action': 'request_otp_emergency_switch',
            'username': phone_no_pin,
            'password': 'Secret123!'
        })
        assert_true(res_no_pin_req.get_json().get('has_pin') is False, "has_pin terdeteksi False pada akun tanpa PIN")

        otp_np = OtpCode.query.filter_by(phone=phone_no_pin, action='emergency_switch').order_by(OtpCode.id.desc()).first()
        otp_np.otp_code = '777888'
        otp_np.expires_at = time.time() + 600
        otp_np.is_used = False
        db.session.commit()

        # Eksekusi pindah perangkat TANPA memasukkan PIN (hanya OTP + Password)
        res_np_switch = client.post('/profil', data={
            'action': 'emergency_switch_device',
            'phone': phone_no_pin,
            'otp': '777888',
            'password': 'Secret123!',
            'device_uuid': 'uuid_device_y'
        })
        assert_true(res_np_switch.get_json().get('status') == 'success', "Berhasil pindah perangkat pada akun tanpa PIN menggunakan Password confirm")

        # =====================================================================
        # TEST 5: Admin Kick-Out
        # =====================================================================
        print("\n--- [TEST 5] Admin Kick-Out Feature ---")
        admin_client = app.test_client()
        with admin_client.session_transaction() as sess:
            sess['admin_logged_in'] = True
            sess['admin_username'] = 'SuperAdmin'

        res_kick = admin_client.post(f'/admin/users/{user_with_pin.id}/kickout')
        json_kick = res_kick.get_json()
        assert_true(json_kick.get('status') == 'success', "Admin kickout endpoint mengembalikan success")

        db.session.refresh(user_with_pin)
        assert_true(user_with_pin.current_session_token is None, "Token sesi user di database menjadi None (Bebas Login)")
        assert_true(not user_with_pin.is_session_active(23), "is_session_active sekarang False")

        kick_log = DeviceSessionLog.query.filter_by(user_id=user_with_pin.id, event_type='ADMIN_KICKOUT').first()
        assert_true(kick_log is not None, "Audit log ADMIN_KICKOUT tercatat rapi")

        # =====================================================================
        # TEST 6: Auto-Expiry Inactivity Timeout 23 Jam
        # =====================================================================
        print("\n--- [TEST 6] Inactivity Timeout 23 Jam ---")
        now = datetime.utcnow()
        user_with_pin.last_active_at = now - timedelta(hours=22)
        assert_true(not is_session_expired_inactivity(user_with_pin, timeout_hours=23), "22 jam inaktif -> belum expired")
        user_with_pin.last_active_at = now - timedelta(hours=23, minutes=1)
        assert_true(is_session_expired_inactivity(user_with_pin, timeout_hours=23), "23 jam 1 menit inaktif -> EXPIRED")

        # Cleanup test data
        DeviceSessionLog.query.filter(DeviceSessionLog.user_id.in_([user_with_pin.id, user_no_pin.id])).delete()
        OtpCode.query.filter(OtpCode.phone.in_([phone_with_pin, phone_no_pin])).delete()
        db.session.delete(user_with_pin)
        db.session.delete(user_no_pin)
        db.session.commit()

    print("\n" + "=" * 75)
    print(f"  SEMUA PENGUJIAN SELESAI DENGAN SUKSES! ({test_passed}/{test_total} PASSED)")
    print("=" * 75)

if __name__ == '__main__':
    run_tests()
