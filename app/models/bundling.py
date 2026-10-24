from app.extensions import db
from datetime import datetime

class PromoBundle(db.Model):
    __tablename__ = 'promo_bundles'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    badge_label = db.Column(db.String(50), default="Hemat Rp 500")
    description = db.Column(db.Text, nullable=True)

    # Produk 1
    sku_1 = db.Column(db.String(50), nullable=False)
    name_1 = db.Column(db.String(150), nullable=False)
    target_label_1 = db.Column(db.String(100), default="Nomor HP")

    # Produk 2
    sku_2 = db.Column(db.String(50), nullable=False)
    name_2 = db.Column(db.String(150), nullable=False)
    target_label_2 = db.Column(db.String(100), default="Nomor Meter / ID Pelanggan")

    # Nominal Potongan / Diskon Paket (Rp)
    discount_amount = db.Column(db.Float, default=500.0)

    # Status & Metrik
    is_active = db.Column(db.Boolean, default=True, index=True)
    total_sold = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def get_products(self):
        """Mengambil instance model Product untuk masing-masing item bundle."""
        from app.models.product import Product
        p1 = Product.query.filter_by(sku_code=self.sku_1).first()
        p2 = Product.query.filter_by(sku_code=self.sku_2).first()
        return p1, p2

    def calculate_prices(self, user=None):
        """
        Menghitung total harga normal dan harga bundling sesuai tier user (Member/Reseller/VIP).
        """
        from app.services.tier_service import get_user_product_price
        p1, p2 = self.get_products()
        price_1 = float(get_user_product_price(user, p1)) if p1 else 0.0
        price_2 = float(get_user_product_price(user, p2)) if p2 else 0.0
        total_normal = price_1 + price_2
        discount = float(self.discount_amount or 0.0)
        bundle_price = max(0.0, total_normal - discount)

        base_hpp_1 = float(p1.base_price or 0.0) if p1 else 0.0
        base_hpp_2 = float(p2.base_price or 0.0) if p2 else 0.0
        total_hpp = base_hpp_1 + base_hpp_2
        gross_profit = max(0.0, bundle_price - total_hpp)

        return {
            'product_1': p1,
            'product_2': p2,
            'price_1': price_1,
            'price_2': price_2,
            'total_normal': total_normal,
            'discount': discount,
            'discount_amount': discount,
            'bundle_price': bundle_price,
            'final_price': bundle_price,
            'total_hpp': total_hpp,
            'gross_profit': gross_profit,
            'is_available': bool(p1 and p1.is_active and p2 and p2.is_active)
        }
