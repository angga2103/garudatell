import requests
import hashlib
import time

class PaymentKitaService:
    def __init__(self, config):
        self.config = config
        # Base URL PaymentKita (Pastikan sesuai dengan dokumentasi resmi)
        self.base_url = "https://api.paymentkita.com/v1" 

    def sign(self):
        merchant = self.config.get("merchant_id", "")
        secret = self.config.get("secret", "")
        return hashlib.md5(f"{merchant}:{secret}".encode()).hexdigest()

    def balance(self):
        try:
            res = requests.get(
                f"{self.base_url}/merchant/balance",
                params={
                    "merchant": self.config.get("merchant_id"),
                    "signature": self.sign()
                },
                timeout=10
            )
            return res.json()
        except Exception as e:
            return {"status": False, "error": str(e)}

    def create_order(self, ref_id, nominal, metode):
        try:
            res = requests.get(
                f"{self.base_url}/order",
                params={
                    "merchant": self.config.get("merchant_id"),
                    "secret": self.config.get("secret"),
                    "ref_id": ref_id,
                    "nominal": nominal,
                    "metode": metode
                },
                timeout=15
            )
            return res.json()
        except Exception as e:
            return {"status": False, "error": str(e)}

    def check_order(self, ref_id):
        try:
            res = requests.get(
                f"{self.base_url}/check-order",
                params={
                    "merchant_id": self.config.get("merchant_id"),
                    "secret": self.config.get("secret"),
                    "ref_id": ref_id
                },
                timeout=10
            )
            return res.json()
        except Exception as e:
            return {"status": False, "error": str(e)}
