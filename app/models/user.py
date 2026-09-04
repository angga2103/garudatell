from flask_login import UserMixin
from app.extensions import db

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    pin_hash = db.Column(db.String(200), nullable=True)
    balance = db.Column(db.Float, default=0.0)
    points = db.Column(db.Integer, default=0)
    role = db.Column(db.String(20), default='user')
    is_active = db.Column(db.Boolean, default=True)
    referral_code = db.Column(db.String(20), unique=True, nullable=True)

    def set_password(self, password):
        from werkzeug.security import generate_password_hash
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        from werkzeug.security import check_password_hash
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

