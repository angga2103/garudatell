from datetime import datetime, timedelta
from app.extensions import db

class DeviceSessionLog(db.Model):
    __tablename__ = 'device_session_log'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    phone = db.Column(db.String(20), nullable=True, index=True)
    event_type = db.Column(db.String(30), nullable=False, index=True)  # 'LOGIN', 'LOGOUT', 'EMERGENCY_SWITCH', 'ADMIN_KICKOUT', 'AUTO_EXPIRED'
    device_name = db.Column(db.String(150), nullable=True)
    ip_address = db.Column(db.String(50), nullable=True)
    details = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    user = db.relationship('User', backref=db.backref('session_logs', lazy='dynamic', cascade='all, delete-orphan'))

    @property
    def created_at_wib(self):
        if self.created_at:
            wib = self.created_at + timedelta(hours=7)
            return wib.strftime('%d-%m-%Y %H:%M:%S WIB')
        return '-'

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'phone': self.phone,
            'event_type': self.event_type,
            'device_name': self.device_name,
            'ip_address': self.ip_address,
            'details': self.details,
            'created_at': self.created_at_wib
        }
