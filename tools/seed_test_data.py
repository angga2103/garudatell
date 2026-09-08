import os
import sys
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, BASE_DIR)

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.product import Product

def seed_data():
    app = create_app()
    with app.app_context():
        # 1. Akun VIP Owner untuk Pengujian Localhost
        phone = "081234567890"
        user = User.query.filter_by(phone=phone).first()
        wib_now = datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)
        
        if not user:
            user = User(
                name="Owner Toko VIP",
                phone=phone,
                role="vip",
                role_expires_at=wib_now + timedelta(days=30),
                balance=500000.0,
                is_device_lock_enabled=False
            )
            user.set_password("password123")
            db.session.add(user)
            print(f"[*] Akun VIP Uji Coba Dibuat:")
            print(f"    No HP   : 081234567890")
            print(f"    Password: password123")
            print(f"    Saldo   : Rp 500.000")
            print(f"    Role    : VIP (Aktif 30 hari)")
        else:
            user.role = "vip"
            user.role_expires_at = wib_now + timedelta(days=30)
            user.balance = max(user.balance or 0.0, 500000.0)
            user.set_password("password123")
            print(f"[*] Akun VIP Uji Coba Diperbarui (081234567890 / password123 / Saldo Rp {user.balance:,.0f})")

        # 2. Sampel Produk untuk Layar POS Kasir
        sample_products = [
            # Pulsa Telkomsel
            {"sku_code": "TSEL5", "name": "Telkomsel 5.000", "category": "PULSA", "brand": "TELKOMSEL", "base_price": 5100.0, "sell_price": 5500.0},
            {"sku_code": "TSEL10", "name": "Telkomsel 10.000", "category": "PULSA", "brand": "TELKOMSEL", "base_price": 10100.0, "sell_price": 10500.0},
            {"sku_code": "TSEL20", "name": "Telkomsel 20.000", "category": "PULSA", "brand": "TELKOMSEL", "base_price": 20050.0, "sell_price": 20500.0},
            {"sku_code": "TSEL50", "name": "Telkomsel 50.000", "category": "PULSA", "brand": "TELKOMSEL", "base_price": 49800.0, "sell_price": 50500.0},
            # Pulsa Indosat
            {"sku_code": "ISAT5", "name": "Indosat 5.000", "category": "PULSA", "brand": "INDOSAT", "base_price": 5200.0, "sell_price": 5600.0},
            {"sku_code": "ISAT10", "name": "Indosat 10.000", "category": "PULSA", "brand": "INDOSAT", "base_price": 10200.0, "sell_price": 10600.0},
            # Pulsa XL
            {"sku_code": "XL5", "name": "XL 5.000", "category": "PULSA", "brand": "XL", "base_price": 5150.0, "sell_price": 5550.0},
            {"sku_code": "XL10", "name": "XL 10.000", "category": "PULSA", "brand": "XL", "base_price": 10150.0, "sell_price": 10550.0},
            # PLN
            {"sku_code": "PLN20", "name": "Token PLN 20.000", "category": "PLN", "brand": "PLN", "base_price": 20100.0, "sell_price": 20600.0},
            {"sku_code": "PLN50", "name": "Token PLN 50.000", "category": "PLN", "brand": "PLN", "base_price": 50100.0, "sell_price": 50600.0},
            # E-Wallet
            {"sku_code": "DANA10", "name": "Saldo DANA 10.000", "category": "EMONEY", "brand": "DANA", "base_price": 10150.0, "sell_price": 10500.0},
            {"sku_code": "DANA20", "name": "Saldo DANA 20.000", "category": "EMONEY", "brand": "DANA", "base_price": 20150.0, "sell_price": 20500.0},
            # Games
            {"sku_code": "FF50D", "name": "Free Fire 50 Diamond", "category": "GAMES", "brand": "FREE FIRE", "base_price": 6800.0, "sell_price": 7500.0},
            {"sku_code": "FF100D", "name": "Free Fire 100 Diamond", "category": "GAMES", "brand": "FREE FIRE", "base_price": 13500.0, "sell_price": 14500.0}
        ]

        added_count = 0
        for sp in sample_products:
            p = Product.query.filter_by(sku_code=sp['sku_code']).first()
            if not p:
                new_p = Product(
                    sku_code=sp['sku_code'],
                    name=sp['name'],
                    category=sp['category'],
                    brand=sp['brand'],
                    base_price=sp['base_price'],
                    sell_price=sp['sell_price'],
                    is_active=True
                )
                db.session.add(new_p)
                added_count += 1

        db.session.commit()
        print(f"[*] {added_count} produk sampel berhasil ditambahkan ke katalog.")
        print("[SUCCESS] Data pengujian siap! Anda dapat menjalankan: python run.py")

if __name__ == '__main__':
    seed_data()
