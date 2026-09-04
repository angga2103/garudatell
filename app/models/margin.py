from app.extensions import db

class MarginTier(db.Model):
    __tablename__ = 'margin_tiers'
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.Integer, unique=True, nullable=False)
    min_price = db.Column(db.Float, nullable=False)
    max_price = db.Column(db.Float, nullable=False)
    margin = db.Column(db.Float, nullable=False)
