#!/usr/bin/env python3

import sys
from pathlib import Path

# Root project
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import hashlib

from app import create_app
from app.models.provider import Provider

app = create_app()

with app.app_context():

    p = Provider.query.filter_by(
        provider_type="payment",
        active=True
    ).first()

    if not p:
        print("Provider PaymentKita aktif tidak ditemukan.")
        raise SystemExit

    merchant = (p.merchant_id or "").strip()
    secret = (p.secret_key or "").strip()

    print("=" * 70)
    print("PAYMENTKITA SIGNATURE DOCTOR")
    print("=" * 70)
    print("Merchant :", merchant)
    print("Secret   :", "*" * len(secret))
    print("=" * 70)

    candidates = {
        "merchant:secret": f"{merchant}:{secret}",
        "merchant+secret": f"{merchant}{secret}",
        "secret+merchant": f"{secret}{merchant}",
        "merchant|secret": f"{merchant}|{secret}",
        "merchant.secret": f"{merchant}.{secret}",
        "secret:merchant": f"{secret}:{merchant}",
    }

    for name, raw in candidates.items():
        print(name)
        print("RAW :", raw)
        print("MD5 :", hashlib.md5(raw.encode()).hexdigest())
        print("-" * 70)
