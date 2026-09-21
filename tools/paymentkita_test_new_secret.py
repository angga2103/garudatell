import hashlib
import json
import requests
import os

merchant = os.getenv("PAYMENTKITA_MERCHANT_ID", "PKM_YOUR_MERCHANT_ID")
secret = os.getenv("PAYMENTKITA_SECRET", "PKSK_YOUR_SECRET_KEY")

signature = hashlib.md5(
    f"{merchant}:{secret}".encode("utf-8")
).hexdigest()

print("="*70)
print("PAYMENTKITA NEW SECRET TEST")
print("="*70)
print("Merchant :", merchant)
print("Signature:", signature)
print("="*70)

url = "https://api.paymentkita.com/v1/merchant/balance"

r = requests.get(
    url,
    params={
        "merchant": merchant,
        "signature": signature
    },
    timeout=30
)

print("HTTP :", r.status_code)
print("URL  :", r.url)
print("="*70)

try:
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
except Exception:
    print(r.text)

print("="*70)
