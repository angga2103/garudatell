import os
import hashlib
import requests
import logging
import socket
from dotenv import load_dotenv
import urllib3.util.connection as urllib3_cn

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

def clean_str(val):
    if not val:
        return ''
    return str(val).replace("'", "").replace('"', '').strip(" \t\n\r")

def force_ipv4():
    """
    Memaksa koneksi urllib3/requests selalu menggunakan IPv4 (socket.AF_INET).
    Mencegah penolakan 'IP 2001:... is not permitted' oleh VIP-Reseller karena
    server Linux dual-stack memprioritaskan rute IPv6 secara default.
    """
    try:
        urllib3_cn.allowed_gai_family = lambda: socket.AF_INET
    except Exception:
        pass

# Aktifkan force IPv4 secara default pada modul VIP-Reseller
force_ipv4()

class VIPReseller:
    """
    Service client untuk VIP-Reseller (VIPayment H2H).
    Dokumentasi resmi:
    - Profile & Balance: https://vip-reseller.co.id/page/api/profile
    - Prepaid: https://vip-reseller.co.id/page/api/prepaid
    - Game Feature: https://vip-reseller.co.id/page/api/game-feature
    """
    def __init__(self, api_id=None, api_key=None):
        if not api_id or not api_key:
            load_dotenv(os.path.join(BASE_DIR, '.env'))
        self.base_url = "https://vip-reseller.co.id/api/prepaid"
        self.game_url = "https://vip-reseller.co.id/api/game-feature"
        self.profile_url = "https://vip-reseller.co.id/api/profile"
        self.api_id = clean_str(api_id or os.getenv('VIP_API_ID'))
        self.api_key = clean_str(api_key or os.getenv('VIP_API_KEY'))

    def _get_sign(self):
        if not self.api_id or not self.api_key:
            return None
        data = f"{self.api_id}{self.api_key}"
        return hashlib.md5(data.encode()).hexdigest()

    def _request(self, payload, url=None):
        force_ipv4()
        sign = self._get_sign()
        if not sign:
            return {"result": False, "message": "API ID atau API Key VIP-Reseller belum disetting di menu Pengaturan Provider."}
        payload['key'] = self.api_key
        payload['sign'] = sign
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        target_url = url if url else self.base_url
        try:
            response = requests.post(target_url, data=payload, headers=headers, timeout=30)
            res_json = response.json()
            return res_json
        except Exception as e:
            logger.error(f"[VIP] Error: {str(e)}")
            return {"result": False, "message": f"Gagal terhubung ke VIP-Reseller: {str(e)}"}

    def get_profile(self):
        """Mengecek profil dan sisa saldo akun VIP-Reseller."""
        return self._request({}, url=self.profile_url)

    def get_services(self, filter_type=None, filter_value=None):
        """Menarik katalog layanan Prepaid (Pulsa, Data, E-Money, dll)."""
        payload = {'type': 'services'}
        if filter_type: payload['filter_type'] = filter_type
        if filter_value: payload['filter_value'] = filter_value
        return self._request(payload, url=self.base_url)

    def get_game_services(self, filter_type=None, filter_value=None):
        """Menarik katalog layanan Game & Streaming Premium dari Game Feature."""
        payload = {'type': 'services'}
        if filter_type: payload['filter_type'] = filter_type
        if filter_value: payload['filter_value'] = filter_value
        return self._request(payload, url=self.game_url)

    def create_order(self, service_code, data_no, is_game=False, data_zone=None):
        """Membuat pesanan baru ke VIP-Reseller."""
        clean_target = str(data_no).strip()
        # Otomatis pisahkan zone jika format target 12345(6789)
        if '(' in clean_target and ')' in clean_target:
            parts = clean_target.split('(')
            clean_target = parts[0].strip()
            data_zone = parts[1].replace(')', '').strip()
            is_game = True

        payload = {'type': 'order', 'service': str(service_code).strip(), 'data_no': clean_target}
        if is_game:
            if data_zone: payload['data_zone'] = str(data_zone).strip()
            return self._request(payload, url=self.game_url)
        return self._request(payload, url=self.base_url)

    def check_status(self, trxid, is_game=False):
        """Pengecekan status transaksi ke VIP-Reseller."""
        payload = {'type': 'status', 'trxid': str(trxid).strip()}
        return self._request(payload, url=self.game_url if is_game else self.base_url)
