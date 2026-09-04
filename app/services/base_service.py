from app.extensions import db

class BaseService:

    def commit(self):
        db.session.commit()

    def rollback(self):
        db.session.rollback()

    def save(self,obj):
        db.session.add(obj)
        db.session.commit()
        return obj

    def delete(self,obj):
        db.session.delete(obj)
        db.session.commit()
