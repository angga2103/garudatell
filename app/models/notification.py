from datetime import datetime, timedelta
from app.extensions import db

class Notification(db.Model):
    __tablename__ = 'notifications'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    type = db.Column(db.String(30), default='info')  # 'info', 'promo', 'warning', 'system'
    link = db.Column(db.String(255), nullable=True)   # Optional URL / deep-link
    target_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # None = Broadcast all
    is_broadcast = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relasi ke target user (opsional)
    target_user = db.relationship('User', foreign_keys=[target_user_id], backref='direct_notifications', lazy=True)

    @property
    def created_at_wib(self):
        wib = self.created_at + timedelta(hours=7)
        return wib.strftime("%d %b %Y, %H:%M WIB")

    @property
    def time_ago(self):
        diff = datetime.utcnow() - self.created_at
        seconds = diff.total_seconds()
        if seconds < 60:
            return "Baru saja"
        elif seconds < 3600:
            return f"{int(seconds // 60)} menit lalu"
        elif seconds < 86400:
            return f"{int(seconds // 3600)} jam lalu"
        elif seconds < 604800:
            return f"{int(seconds // 86400)} hari lalu"
        else:
            return self.created_at_wib

    def __repr__(self):
        return f"<Notification #{self.id} [{self.type}] {self.title}>"


class NotificationRead(db.Model):
    __tablename__ = 'notification_reads'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    notification_id = db.Column(db.Integer, db.ForeignKey('notifications.id', ondelete='CASCADE'), nullable=False)
    read_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User', backref=db.backref('notification_reads', cascade='all, delete-orphan'))
    notification = db.relationship('Notification', backref=db.backref('readers', cascade='all, delete-orphan'))

    __table_args__ = (
        db.UniqueConstraint('user_id', 'notification_id', name='uq_user_notification_read'),
    )

    def __repr__(self):
        return f"<NotificationRead User:{self.user_id} Notif:{self.notification_id}>"

