from app.extensions import db
from datetime import datetime

class TrustedDevice(db.Model):
    __tablename__ = 'trusted_device'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    device_uuid = db.Column(db.String(64), nullable=False, index=True)
    device_name = db.Column(db.String(100), nullable=False)  # Contoh: "Cabang 1 - Pasar Baru"
    device_info = db.Column(db.String(255), nullable=True)   # Browser / OS info
    ip_address = db.Column(db.String(50), nullable=True)
    status = db.Column(db.String(20), default='pending', index=True)  # 'pending', 'approved', 'rejected', 'revoked'
    approval_token = db.Column(db.String(64), unique=True, nullable=True, index=True)
    approval_expires_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'device_uuid', name='uq_user_device'),
        db.Index('idx_user_dev_status', 'user_id', 'status'),
    )

    @property
    def created_at_wib(self):
        from datetime import timedelta
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return '-'

    @property
    def last_used_at_wib(self):
        from datetime import timedelta
        if self.last_used_at:
            wib = self.last_used_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M')
        return 'Belum pernah'

    def is_token_expired(self):
        if not self.approval_expires_at:
            return True
        return datetime.utcnow() > self.approval_expires_at

