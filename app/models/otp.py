from app.extensions import db
from datetime import datetime
import time

class OtpCode(db.Model):
    __tablename__ = 'otp_codes'

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), index=True, nullable=False)
    otp_code = db.Column(db.String(10), nullable=False)
    action = db.Column(db.String(50), default='register')
    username = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    expires_at = db.Column(db.Float, nullable=False)
    is_used = db.Column(db.Boolean, default=False)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def is_expired(self, current_time=None):
        now = current_time or time.time()
        return now > self.expires_at

