import requests
import json
import logging

logger = logging.getLogger(__name__)

def is_wa_bot_connected():
    """Mengecek apakah Mesin Baileys Node.js di port 3000 aktif dan terhubung ke WhatsApp."""
    for host in ['127.0.0.1', 'localhost']:
        try:
            res = requests.get(f'http://{host}:3000/api/status', timeout=2)
            if res.status_code == 200:
                data = res.json()
                if data.get('connected') is True:
                    return True
        except Exception:
            continue
    return False

def kirim_wa_otp(target_number, kode_otp, action='register'):
    try:
        # 1. Bersihkan format nomor WA
        clean_num = ''.join(filter(str.isdigit, str(target_number)))
        if clean_num.startswith('0'):
            clean_num = '62' + clean_num[1:]
            
        if action == 'login':
            pesan = (
                f"*[GARUDATEL - KODE MASUK (LOGIN)]*\n\n"
                f"Kode OTP Anda adalah: *{kode_otp}*\n\n"
                f"⚠️ Kode ini bersifat rahasia dan berlaku selama 10 menit. "
                f"Jangan berikan kepada siapa pun termasuk pihak yang mengatasnamakan GarudaTel."
            )
        elif action == 'reset_password':
            pesan = (
                f"*[GARUDATEL - RESET KATA SANDI]*\n\n"
                f"Kode OTP pemulihan kata sandi Anda: *{kode_otp}*\n\n"
                f"⚠️ Kode ini bersifat rahasia dan berlaku selama 10 menit. "
                f"Jika Anda tidak merasa meminta reset password, abaikan pesan ini."
            )
        else:
            pesan = (
                f"*[GARUDATEL PPOB - VERIFIKASI DAFTAR]*\n\n"
                f"Kode OTP pendaftaran akun Anda adalah: *{kode_otp}*\n\n"
                f"⚠️ Kode ini bersifat rahasia dan berlaku selama 10 menit. "
                f"Jangan berikan kepada siapa pun."
            )
        
        # 2. Kirim langsung via HTTP POST ke Microservice Baileys Node.js (port 3000)
        payload = {"number": clean_num, "message": pesan}
        for host in ['127.0.0.1', 'localhost']:
            try:
                res = requests.post(
                    f'http://{host}:3000/api/send',
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=8
                )
                if res.status_code == 200:
                    res_data = res.json()
                    if res_data.get('status') == 'success':
                        return True
                    else:
                        logger.warning(f"[-] Respons bot WA: {res.text}")
                        return False
                else:
                    logger.warning(f"[-] HTTP {res.status_code} dari bot WA: {res.text}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                continue
            except Exception as e:
                logger.error(f"[-] Gagal mengirim WA OTP: {e}")
                return False
                
        return False
            
    except Exception as e:
        logger.error(f"[-] Gagal mengirim WA OTP (Fatal): {e}")
        return False

def kirim_wa_otp_login(target_number, kode_otp):
    return kirim_wa_otp(target_number, kode_otp, action='login')

def kirim_wa_otp_reset(target_number, kode_otp):
    return kirim_wa_otp(target_number, kode_otp, action='reset_password')

def kirim_wa(target_number, message):
    try:
        clean_num = ''.join(filter(str.isdigit, str(target_number)))
        if clean_num.startswith('0'):
            clean_num = '62' + clean_num[1:]

        payload = {"number": clean_num, "message": message}
        res = requests.post(
            'http://127.0.0.1:3000/api/send',
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=5
        )
        if res.status_code == 200:
            res_data = res.json()
            return res_data.get('status') == 'success'
        return False
    except Exception as e:
        logger.warning(f"[-] Gagal kirim WA ke {target_number}: {e}")
        return False