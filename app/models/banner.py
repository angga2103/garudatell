from datetime import datetime
from app.extensions import db

class Banner(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    link_url = db.Column(db.String(500), nullable=True, default='')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Banner #{self.id} {self.title}>"

