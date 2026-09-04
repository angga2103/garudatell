from app.models.product import Product
from app.extensions import db

class ProductService:

    @staticmethod
    def all():
        return Product.query.all()

    @staticmethod
    def by_id(pid):
        return Product.query.get(pid)

    @staticmethod
    def by_sku(sku):
        return Product.query.filter_by(sku_code=sku).first()

    @staticmethod
    def categories():
        rows=db.session.query(Product.category).distinct().all()
        return [r[0] for r in rows]

    @staticmethod
    def search(keyword):
        return Product.query.filter(
            Product.name.contains(keyword) |
            Product.sku_code.contains(keyword)
        )
