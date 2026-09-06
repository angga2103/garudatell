from app.extensions import db
from datetime import datetime
import time

class OtpManualRequest(db.Model):
    __tablename__ = 'otp_manual_requests'

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), index=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    action = db.Column(db.String(50), default='register') # register, login, reset_password
    otp_code = db.Column(db.String(10), nullable=True)
    temp_data = db.Column(db.Text, nullable=True) # JSON string untuk menyimpan data sementara
    status = db.Column(db.String(20), default='PENDING', index=True) # PENDING, APPROVED, REJECTED, USED, EXPIRED, UNBLOCKED
    rejection_reason = db.Column(db.String(255), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    approved_at = db.Column(db.DateTime, nullable=True)
    expires_at = db.Column(db.Float, nullable=True)

    def is_expired(self, current_time=None):
        if not self.expires_at:
            return False
        now = current_time or time.time()
        return now > self.expires_at

    def to_dict(self):
        return {
            'id': self.id,
            'phone': self.phone,
            'name': self.name or '-',
            'action': self.action,
            'status': self.status,
            'rejection_reason': self.rejection_reason,
            'created_at': self.created_at.strftime('%d/%m/%Y %H:%M:%S') if self.created_at else '-',
            'approved_at': self.approved_at.strftime('%d/%m/%Y %H:%M:%S') if self.approved_at else '-',
            'is_expired': self.is_expired()
        }

