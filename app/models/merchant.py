from datetime import datetime, timezone, timedelta
from app.extensions import db

def get_wib_datetime():
    return datetime.now(timezone(timedelta(hours=7))).replace(tzinfo=None)

class MerchantApiKey(db.Model):
    __tablename__ = 'merchant_api_keys'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    merchant_id = db.Column(db.String(32), unique=True, nullable=False, index=True)
    api_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    secret_key = db.Column(db.String(64), nullable=False)
    name = db.Column(db.String(100), default='Kasir Utama', nullable=False)
    webhook_url = db.Column(db.String(255), nullable=True)
    ip_whitelist = db.Column(db.String(255), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=get_wib_datetime, index=True)
    last_used_at = db.Column(db.DateTime, nullable=True)

    # Relasi ke User
    user = db.relationship('User', backref=db.backref('merchant_api_keys', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f"<MerchantApiKey {self.merchant_id} user_id={self.user_id} active={self.is_active}>"
