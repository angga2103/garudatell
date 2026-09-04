from app.extensions import db

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku_code = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50), nullable=False, index=True)
    brand = db.Column(db.String(50), nullable=False, index=True)
    base_price = db.Column(db.Float, nullable=False)
    sell_price = db.Column(db.Float, nullable=False)
    is_active = db.Column(db.Boolean, default=True, index=True)
    
    # Kolom baru pendeteksi edit manual
    is_manual_margin = db.Column(db.Boolean, default=False)

    __table_args__ = (
        db.Index('idx_product_category_active', 'category', 'is_active'),
        db.Index('idx_product_brand_active', 'brand', 'is_active'),
        db.Index('idx_product_cat_brand_active', 'category', 'brand', 'is_active'),
    )
