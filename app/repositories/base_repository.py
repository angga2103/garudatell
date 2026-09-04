from app.extensions import db

class BaseRepository:

    model = None

    @classmethod
    def all(cls):
        return cls.model.query.all()

    @classmethod
    def get(cls,id):
        return cls.model.query.get(id)

    @classmethod
    def create(cls,**kwargs):
        obj=cls.model(**kwargs)
        db.session.add(obj)
        db.session.commit()
        return obj

    @classmethod
    def delete(cls,obj):
        db.session.delete(obj)
        db.session.commit()

    @classmethod
    def save(cls):
        db.session.commit()
