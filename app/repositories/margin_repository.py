from app.repositories.base_repository import BaseRepository
from app.models.margin import MarginRule

class MarginRepository(BaseRepository):

    model=MarginRule

    @classmethod
    def by_category(cls,cat):
        return MarginRule.query.filter_by(category=cat).first()
