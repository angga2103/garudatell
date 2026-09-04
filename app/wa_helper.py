import requests
import json
import logging

logger = logging.getLogger(__name__)

def kirim_wa_otp(target_number, kode_otp):
    try:
        # 1. Bersihkan format nomor WA
        clean_num = ''.join(filter(str.isdigit, str(target_number)))
        if clean_num.startswith('0'):
            clean_num = '62' + clean_num[1:]
            
        pesan = f"*[GARUDATEL PPOB - VERIFIKASI]*\n\nKode OTP Anda adalah: *{kode_otp}*\nKode ini bersifat rahasia dan berlaku selama 15 menit. Jangan berikan kepada siapa pun."
        
        # 2. Kirim langsung via HTTP POST ke Microservice Baileys Node.js (port 3000)
        payload = {"number": clean_num, "message": pesan}
        res = requests.post(
            'http://127.0.0.1:3000/api/send',
            json=payload,
            headers={'Content-Type': 'application/json'},
            timeout=10
        )
        
        # 3. Cek hasil
        if res.status_code == 200:
            res_data = res.json()
            if res_data.get('status') == 'success':
                return True
            else:
                logger.warning(f"[-] Respons bot WA: {res.text}")
                return False
        else:
            logger.warning(f"[-] HTTP {res.status_code} dari bot WA: {res.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.error("[-] Gagal: Timeout menghubungi Bot WA")
        return False
    except requests.exceptions.ConnectionError:
        logger.error("[-] Gagal: Bot WA tidak aktif di http://127.0.0.1:3000")
        return False
    except Exception as e:
        logger.error(f"[-] Gagal mengirim WA OTP (Fatal): {e}")
        return False

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