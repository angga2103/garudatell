import os
import hashlib
import requests
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

class VIPReseller:
    def __init__(self):
        load_dotenv(os.path.join(BASE_DIR, '.env'), override=True)
        self.base_url = "https://vip-reseller.co.id/api/prepaid"
        self.game_url = "https://vip-reseller.co.id/api/game-feature"
        self.api_id = os.getenv('VIP_API_ID')
        self.api_key = os.getenv('VIP_API_KEY')

    def _get_sign(self):
        if not self.api_id or not self.api_key:
            return None
        data = f"{self.api_id}{self.api_key}"
        return hashlib.md5(data.encode()).hexdigest()

    def _request(self, payload, url=None):
        sign = self._get_sign()
        if not sign:
            return {"result": False, "message": "API ID atau Key belum disetting."}
        payload['key'] = self.api_key
        payload['sign'] = sign
        headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json'
        }
        target_url = url if url else self.base_url
        try:
            response = requests.post(target_url, data=payload, headers=headers, timeout=30)
            return response.json()
        except Exception as e:
            logger.error(f"[VIP] Error: {str(e)}")
            return {"result": False, "message": "Gagal terhubung ke VIP."}

    def get_services(self):
        return self._request({'type': 'services'})

    def get_game_services(self):
        # Menyedot langsung dari Gudang Game Feature
        return self._request({'type': 'services'}, url=self.game_url)

    def create_order(self, service_code, data_no, is_game=False, data_zone=None):
        payload = {'type': 'order', 'service': service_code, 'data_no': data_no}
        if is_game:
            if data_zone: payload['data_zone'] = data_zone
            return self._request(payload, url=self.game_url)
        return self._request(payload)

    def check_status(self, trxid, is_game=False):
        payload = {'type': 'status', 'trxid': trxid}
        return self._request(payload, url=self.game_url if is_game else self.base_url)
