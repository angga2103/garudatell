from app.repositories.base_repository import BaseRepository
from app.models.product import Product
from app.extensions import db

class ProductRepository(BaseRepository):

    model=Product

    @classmethod
    def by_sku(cls,sku):
        return Product.query.filter_by(sku_code=sku).first()

    @classmethod
    def categories(cls):
        return db.session.query(Product.category).distinct().all()

    @classmethod
    def search(cls,q):
        return Product.query.filter(
            Product.name.contains(q) |
            Product.sku_code.contains(q)
        )
